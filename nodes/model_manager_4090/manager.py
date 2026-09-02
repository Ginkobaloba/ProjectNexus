# nodes/model_manager_4090/manager.py
"""
Model manager v0 (Sprint 5, Card 4).

One process owns weights placement and the llama.cpp lifecycle on the
4090 host. Loading a member is:

    ensure_hot()  ->  report `waking`  ->  spawn llama-server
                  ->  poll /health     ->  report `awake`

Unloading stops the server and reports `asleep`. Presence flows to the
hub's POST /members/{id}/presence (Card 2), which also drains the
member's inbox on the awake transition (Card 5) — so "the model
manager finished loading" and "queued messages get answered" are the
same event, with no extra choreography.

V1 runs one member at a time (there's nobody to swap to yet), but
nothing in here assumes that: load/unload are per-member and the
tiering rules already handle contention.
"""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import requests

from bench.probes import JsonlSink, MetricRecord, now_ns
from core.family import FamilyMember

from .tiering import TierPaths, ensure_hot

logger = logging.getLogger("model_manager_4090.manager")


def weights_filename(member: FamilyMember) -> str:
    """Canonical on-disk name for a member's weights: the model repo
    tail plus quant, e.g. `Qwen3-30B-A3B-Instruct-2507.Q4_K_M.gguf`.
    Download-time tooling and the tiers all agree on this one name."""
    source_tail = member.model.source.split("/")[-1]
    return f"{source_tail}.{member.model.quant}.{member.model.format}"


class HubPresenceClient:
    """Reports presence transitions to the hub. Failures are logged,
    not raised — a hub blip must not strand a healthy llama-server."""

    def __init__(self, hub_url: str, token: str, timeout: float = 5.0):
        self.hub_url = hub_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def report(self, member_id: str, presence: str) -> bool:
        try:
            res = requests.post(
                f"{self.hub_url}/members/{member_id}/presence",
                json={"presence": presence},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
            res.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning(
                "presence report failed (member=%s -> %s): %s",
                member_id, presence, exc,
            )
            return False


@dataclass
class LoadedMember:
    member_id: str
    process: subprocess.Popen
    port: int
    weights_path: Path
    loaded_at: float = field(default_factory=time.time)


class ModelManager:
    def __init__(
        self,
        tiers: TierPaths,
        hub: HubPresenceClient,
        llama_server_bin: str = "llama-server",
        llama_host: str = "127.0.0.1",
        llama_port: int = 8000,
        load_timeout_seconds: float = 600.0,
        health_poll_interval_seconds: float = 2.0,
        metrics_sink: Optional[JsonlSink] = None,
    ):
        self.tiers = tiers
        self.hub = hub
        self.llama_server_bin = llama_server_bin
        self.llama_host = llama_host
        self.llama_port = llama_port
        self.load_timeout_seconds = load_timeout_seconds
        self.health_poll_interval_seconds = health_poll_interval_seconds
        self.metrics_sink = metrics_sink
        self.loaded: Dict[str, LoadedMember] = {}

    # -- llama.cpp lifecycle (separable for tests) ----------------------

    def _build_command(self, member: FamilyMember, weights_path: Path) -> List[str]:
        cmd = [
            self.llama_server_bin,
            "--model", str(weights_path),
            "--host", self.llama_host,
            "--port", str(self.llama_port),
            "--ctx-size", str(member.model.context_length),
        ]
        # offload_policy maps to how many layers llama.cpp keeps on the
        # GPU. vram_then_ram lets llama.cpp fill VRAM and spill the rest
        # to system RAM; vram_ram_ssd additionally allows mmap-backed
        # cold weights (the seconds-per-token tradeoff Drew accepted for
        # some workloads).
        if member.runtime.offload_policy in ("vram_then_ram", "vram_ram_ssd"):
            cmd += ["--n-gpu-layers", "999"]
        if member.runtime.offload_policy == "vram_then_ram":
            cmd += ["--no-mmap"]
        return cmd

    def _spawn(self, command: List[str]) -> subprocess.Popen:
        logger.info("spawning: %s", " ".join(command))
        return subprocess.Popen(command)

    def _healthy(self) -> bool:
        try:
            res = requests.get(
                f"http://{self.llama_host}:{self.llama_port}/health", timeout=3
            )
            return res.status_code == 200
        except requests.RequestException:
            return False

    def _wait_healthy(self, process: subprocess.Popen) -> float:
        """Poll until llama-server answers /health; return the wait in
        ms. Raises if the process dies or the timeout passes."""
        t0 = time.monotonic_ns()
        deadline = time.monotonic() + self.load_timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited with code {process.returncode} during load"
                )
            if self._healthy():
                return (time.monotonic_ns() - t0) / 1e6
            time.sleep(self.health_poll_interval_seconds)
        process.terminate()
        raise TimeoutError(
            f"llama-server not healthy after {self.load_timeout_seconds}s"
        )

    # -- public API ------------------------------------------------------

    def load(self, member: FamilyMember) -> LoadedMember:
        """Stage weights hot, boot llama-server, flip presence. Emits
        stage_copy_ms and load_ms per load (Card 4 done-criterion)."""
        if member.id in self.loaded:
            return self.loaded[member.id]

        t_ingress = now_ns()
        filename = weights_filename(member)
        stage = ensure_hot(filename, self.tiers)

        self.hub.report(member.id, "waking")
        ok, err = True, None
        load_ms = 0.0
        try:
            process = self._spawn(self._build_command(member, stage.path))
            load_ms = self._wait_healthy(process)
        except Exception as exc:
            ok, err = False, str(exc)
            self.hub.report(member.id, "asleep")
            raise
        finally:
            self._record(
                member_id=member.id,
                ingress_ns=t_ingress,
                ok=ok,
                stage_copy_ms=stage.stage_copy_ms,
                staged_from=stage.staged_from,
                load_ms=load_ms,
                error=err,
            )

        entry = LoadedMember(
            member_id=member.id,
            process=process,
            port=self.llama_port,
            weights_path=stage.path,
        )
        self.loaded[member.id] = entry
        self.hub.report(member.id, "awake")
        logger.info(
            "member %s awake (stage_copy_ms=%.0f load_ms=%.0f)",
            member.id, stage.stage_copy_ms, load_ms,
        )
        return entry

    def unload(self, member_id: str, grace_seconds: float = 10.0) -> bool:
        """Stop the member's llama-server and report asleep. Returns
        False if the member wasn't loaded."""
        entry = self.loaded.pop(member_id, None)
        if entry is None:
            return False
        entry.process.terminate()
        try:
            entry.process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            logger.warning("llama-server for %s ignored SIGTERM; killing", member_id)
            entry.process.kill()
            entry.process.wait()
        self.hub.report(member_id, "asleep")
        logger.info("member %s asleep", member_id)
        return True

    def status(self) -> Dict[str, dict]:
        out = {}
        for member_id, entry in self.loaded.items():
            alive = entry.process.poll() is None
            out[member_id] = {
                "port": entry.port,
                "weights": str(entry.weights_path),
                "alive": alive,
                "loaded_at": entry.loaded_at,
            }
        return out

    # -- metrics -----------------------------------------------------------

    def _record(self, member_id: str, ingress_ns: int, ok: bool,
                stage_copy_ms: float, staged_from: Optional[str],
                load_ms: float, error: Optional[str]) -> None:
        if self.metrics_sink is None:
            return
        record = MetricRecord(
            probe_id="model_manager.load",
            stage="load",
            ingress_ns=ingress_ns,
            egress_ns=now_ns(),
            payload_bytes=0,
            ok=ok,
            extra={
                "member_id": member_id,
                "stage_copy_ms": round(stage_copy_ms, 3),
                "staged_from": staged_from,
                "load_ms": round(load_ms, 3),
                "error": error,
            },
        )
        try:
            self.metrics_sink.write(record)
        except Exception:
            logger.warning("metric sink write failed", exc_info=True)
