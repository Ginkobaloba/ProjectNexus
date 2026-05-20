# bench/probes.py
"""
Phase 0 metric harness: probe helper and JSONL sink.

This is the minimal, honest slice of Experiment 1's Component G. It gives
us monotonic-clock timing, a stable per-record schema (Experiment 1
design doc, section 2.2), and an append-only JSONL sink the live
dashboard can tail. The heavier pieces from the design doc (the netem
runner, a Prometheus sink) are deliberately not built yet.

A "record" is one observation of one stage of one event. For the current
build state the only instrumented event is a brainstem /generate request,
recorded as a single composite record with the sub-stage timings carried
as explicit fields in `extra`. When more components land they each emit
their own records against the same schema.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

# One run id per process lifetime. Lets the dashboard and analyze.py group
# records that came from the same service run.
RUN_UUID = os.environ.get("NEXUS_RUN_UUID") or f"run_{uuid.uuid4().hex[:12]}"

_seq_lock = threading.Lock()
_event_seq = 0


def next_seq() -> int:
    """Process-wide, monotonically increasing event sequence number."""
    global _event_seq
    with _seq_lock:
        _event_seq += 1
        return _event_seq


def now_ns() -> int:
    """Monotonic-clock timestamp in ns. Never goes backwards, so it is
    safe for durations. Not wall-clock; pair with ts_wall_iso for a
    human-readable time."""
    return time.monotonic_ns()


@dataclass
class MetricRecord:
    """One metric observation. The required fields match Experiment 1
    design doc section 2.2; stage-specific timings ride in `extra` and
    are flattened to the top level on serialization."""

    probe_id: str
    stage: str
    ingress_ns: int
    egress_ns: int
    payload_bytes: int = 0
    ok: bool = True
    event_seq: int = field(default_factory=next_seq)
    run_uuid: str = RUN_UUID
    phase: str = "phase0"
    build_state: str = field(
        default_factory=lambda: os.environ.get(
            "NEXUS_BUILD_STATE", "brainstem+cortex"
        )
    )
    topology_arm: str = "B"        # stripped-down arm B: edge -> 4070 -> 4090
    wire_format: str = "json"
    t_offered: float = 0.0         # offered rate; 0.0 for ad-hoc (non-sweep) traffic
    schema_version: int = SCHEMA_VERSION
    ts_monotonic_ns: int = 0
    ts_wall_iso: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ts_monotonic_ns:
            self.ts_monotonic_ns = now_ns()
        if not self.ts_wall_iso:
            self.ts_wall_iso = datetime.now(timezone.utc).isoformat()

    @property
    def duration_ms(self) -> float:
        return (self.egress_ns - self.ingress_ns) / 1e6

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra", {}) or {}
        d.update(extra)            # flatten stage-specific fields to top level
        d["duration_ms"] = round(self.duration_ms, 3)
        return d


class JsonlSink:
    """Append-only JSONL sink: one JSON object per line, flushed per
    write so the dashboard can read it live. A lock keeps concurrent
    request handlers from interleaving lines. At Phase 0 request rates a
    per-write append is cheap; batching is a later optimization."""

    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: MetricRecord) -> None:
        line = json.dumps(record.to_dict(), separators=(",", ":"))
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_all(self) -> List[Dict[str, Any]]:
        """Read every record back as dicts. Used by analyze.py; the live
        dashboard uses the in-process ring buffer instead of re-reading
        the file on every poll."""
        out: List[Dict[str, Any]] = []
        if not os.path.exists(self.path):
            return out
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue       # tolerate a torn last line
        return out


class Span:
    """Context manager that records ingress/egress around a block and
    writes a MetricRecord on exit.

        with Span("brainstem.generate", "generate", sink) as span:
            span.mark("pre_cortex_ns")
            ...
            span.mark("post_cortex_ns")
            span.extra["completion_tokens"] = n

    `ok` is set False (and the record still written) if the block raised;
    the exception is not suppressed. Metric I/O failures never propagate
    into the request path."""

    def __init__(
        self,
        probe_id: str,
        stage: str,
        sink: Optional[JsonlSink],
        payload_bytes: int = 0,
        **extra: Any,
    ):
        self.probe_id = probe_id
        self.stage = stage
        self.sink = sink
        self.payload_bytes = payload_bytes
        self.extra: Dict[str, Any] = dict(extra)
        self.ingress_ns = 0
        self.egress_ns = 0
        self.ok = True
        self.record: Optional[MetricRecord] = None

    def __enter__(self) -> "Span":
        self.ingress_ns = now_ns()
        return self

    def mark(self, label: str) -> int:
        """Stamp an intermediate monotonic timestamp into `extra` and
        return it, e.g. span.mark('pre_cortex_ns')."""
        ts = now_ns()
        self.extra[label] = ts
        return ts

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.egress_ns = now_ns()
        self.ok = exc_type is None
        self.record = MetricRecord(
            probe_id=self.probe_id,
            stage=self.stage,
            ingress_ns=self.ingress_ns,
            egress_ns=self.egress_ns,
            payload_bytes=self.payload_bytes,
            ok=self.ok,
            extra=self.extra,
        )
        if self.sink is not None:
            try:
                self.sink.write(self.record)
            except Exception:      # never let metric I/O break a request
                pass
        return False               # do not suppress exceptions
