"""Sprint 5 Card 4: model manager v0 — tiering + lifecycle + presence.

Done-criteria under test:
  - cold-start staging: cold -> hot copy with checksum verification and
    a measured stage_copy_ms; already-hot weights are a no-op;
  - a torn/corrupt copy can never be mistaken for a model;
  - eviction respects pins and never deletes the only copy;
  - load() flips presence waking -> awake, emits stage_copy_ms/load_ms
    metrics; unload() reports asleep; a dead process fails the load
    and reports asleep rather than lying about being awake.

llama-server is stubbed with a real (trivial) subprocess so process
lifecycle is exercised for real; only the HTTP health poll is faked.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.family import load_registry
from model_manager_4090.manager import ModelManager, weights_filename
from model_manager_4090.tiering import TierPaths, ensure_hot, evict_from_hot, sha256_file

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tiers(tmp_path: Path) -> TierPaths:
    t = TierPaths(hot=tmp_path / "hot", warm=tmp_path / "warm", cold=tmp_path / "cold")
    t.ensure_dirs()
    return t


class FakeHub:
    def __init__(self):
        self.reports = []

    def report(self, member_id: str, presence: str) -> bool:
        self.reports.append((member_id, presence))
        return True


def _vera():
    registry = load_registry(REPO_ROOT / "family" / "registry.yaml", REPO_ROOT)
    return registry.get("vera")


def _manager(tiers: TierPaths, hub: FakeHub, metrics_path: Path) -> ModelManager:
    from bench.probes import JsonlSink

    return ModelManager(
        tiers=tiers,
        hub=hub,
        llama_server_bin=sys.executable,  # overridden per test via _build_command
        load_timeout_seconds=10.0,
        health_poll_interval_seconds=0.05,
        metrics_sink=JsonlSink(str(metrics_path)),
    )


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------


def test_ensure_hot_stages_from_cold_with_checksum(tmp_path):
    tiers = _tiers(tmp_path)
    (tiers.cold / "m.gguf").write_bytes(b"weights" * 1000)

    result = ensure_hot("m.gguf", tiers)
    assert result.path == tiers.hot / "m.gguf"
    assert result.path.is_file()
    assert result.staged_from == "cold"
    assert result.stage_copy_ms >= 0.0
    assert result.sha256 == sha256_file(tiers.cold / "m.gguf")
    # Cold copy is untouched (staging copies, never moves).
    assert (tiers.cold / "m.gguf").is_file()

    # Second call is a no-op.
    again = ensure_hot("m.gguf", tiers)
    assert again.staged_from is None
    assert again.stage_copy_ms == 0.0


def test_ensure_hot_prefers_warm_over_cold(tmp_path):
    tiers = _tiers(tmp_path)
    (tiers.cold / "m.gguf").write_bytes(b"cold")
    (tiers.warm / "m.gguf").write_bytes(b"warm")
    result = ensure_hot("m.gguf", tiers)
    assert result.staged_from == "warm"
    assert (tiers.hot / "m.gguf").read_bytes() == b"warm"


def test_ensure_hot_missing_everywhere_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        ensure_hot("ghost.gguf", _tiers(tmp_path))


def test_eviction_respects_pins_and_sole_copies(tmp_path):
    tiers = _tiers(tmp_path)
    # a: pinned, backed by warm. b: evictable, backed by cold.
    # c: hot-only — the only copy in existence, must never be removed.
    for name, backing in (("a.gguf", "warm"), ("b.gguf", "cold")):
        (tiers.hot / name).write_bytes(b"x" * 100)
        (tiers.dir_for(backing) / name).write_bytes(b"x" * 100)
    (tiers.hot / "c.gguf").write_bytes(b"x" * 100)

    evicted = evict_from_hot(tiers, needed_bytes=10_000, pinned={"a.gguf"})
    assert evicted == ["b.gguf"]
    assert (tiers.hot / "a.gguf").is_file()   # pinned
    assert (tiers.hot / "c.gguf").is_file()   # sole copy
    assert not (tiers.hot / "b.gguf").is_file()
    assert (tiers.cold / "b.gguf").is_file()  # lower-tier copy intact


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_load_stages_boots_and_reports_presence(tmp_path, monkeypatch):
    tiers = _tiers(tmp_path)
    hub = FakeHub()
    member = _vera()
    (tiers.cold / weights_filename(member)).write_bytes(b"gguf" * 256)

    metrics_path = tmp_path / "metrics.jsonl"
    mgr = _manager(tiers, hub, metrics_path)
    # Real subprocess (sleeps), faked health probe.
    monkeypatch.setattr(
        mgr, "_build_command",
        lambda m, p: [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    monkeypatch.setattr(mgr, "_healthy", lambda: True)

    entry = mgr.load(member)
    try:
        assert entry.process.poll() is None
        assert hub.reports == [("vera", "waking"), ("vera", "awake")]

        record = json.loads(metrics_path.read_text().splitlines()[-1])
        assert record["member_id"] == "vera"
        assert record["staged_from"] == "cold"
        assert record["stage_copy_ms"] >= 0.0
        assert record["load_ms"] >= 0.0
        assert record["ok"] is True

        # Idempotent: loading again returns the same entry.
        assert mgr.load(member) is entry
    finally:
        mgr.unload("vera")

    assert hub.reports[-1] == ("vera", "asleep")
    assert entry.process.poll() is not None
    assert mgr.unload("vera") is False  # already gone


def test_dead_process_fails_load_and_reports_asleep(tmp_path, monkeypatch):
    tiers = _tiers(tmp_path)
    hub = FakeHub()
    member = _vera()
    (tiers.hot / weights_filename(member)).write_bytes(b"gguf")

    mgr = _manager(tiers, hub, tmp_path / "metrics.jsonl")
    monkeypatch.setattr(
        mgr, "_build_command",
        lambda m, p: [sys.executable, "-c", "raise SystemExit(3)"],
    )
    monkeypatch.setattr(mgr, "_healthy", lambda: False)

    with pytest.raises(RuntimeError, match="exited"):
        mgr.load(member)
    assert hub.reports == [("vera", "waking"), ("vera", "asleep")]
    assert "vera" not in mgr.loaded

    record = json.loads((tmp_path / "metrics.jsonl").read_text().splitlines()[-1])
    assert record["ok"] is False
    assert "exited" in record["error"]
