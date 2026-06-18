"""
bench.eval.base: uniform interfaces and result schema.

All 6 task families implement the same `EvalTask` protocol. The runner does not
care whether a task is fully wired (Tasks 1, 5) or a stub (Tasks 2, 3, 4, 6); it
calls the same methods and writes the same JSON shape so Card 5 baselines can
ingest every result without per-task parsing.

Result schema, deterministic field order, lives in `SeedResult` and `TaskSummary`.
See bench/README.md section "Result schema" for the canonical reference.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Protocol, Sequence


# Flag used by stub tasks. The bench runner records it on every per-seed result
# so Card 5 baselines can render stub tasks as "not yet measured" rather than
# "scored zero".
STUB_PLACEHOLDER_FIELD = "stub_placeholder"


@dataclass(frozen=True)
class Sampling:
    """Frozen sampling config recorded into every result. No defaults that
    silently differ across providers; the runner sets these explicitly."""
    temperature: float
    top_p: float
    max_tokens: int
    seed: int


@dataclass(frozen=True)
class ProviderConfig:
    """Provider config snapshot saved into every result. Used for audit."""
    kind: str             # "openai_compat", "stub", future: "anthropic", "vllm_native"
    base_url: str         # e.g. http://localhost:8000/v1
    model: str            # e.g. "cortex"
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Problem:
    """A single problem from a task's dataset."""
    problem_id: str
    prompt: str
    reference: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProblemResult:
    """Per-problem record. metrics carries whatever the task scorer emitted,
    keyed by metric name. The runner does not interpret the values; aggregation
    happens task-side."""
    problem_id: str
    metrics: Dict[str, float]
    completion: str = ""
    completion_tokens: int = 0
    prompt_tokens: int = 0
    latency_s: float = 0.0
    error: Optional[str] = None


@dataclass
class SeedResult:
    """One run of one task at one seed. Written to disk as
    bench/results/<run_label>_<task_id>_seed<seed>.json."""
    run_label: str
    task_id: str
    seed: int
    timestamp_utc: str
    harness_version: str
    git_sha: str
    provider: ProviderConfig
    sampling: Sampling
    task_meta: Dict[str, Any]
    metrics: Dict[str, float]
    per_problem: List[ProblemResult]
    aggregate: Dict[str, float]
    stub_placeholder: bool = False

    def to_json_dict(self) -> Dict[str, Any]:
        # asdict handles nested dataclasses; we just normalize keys + float types
        # for deterministic JSON.
        return _to_json_dict(self)


@dataclass
class TaskSummary:
    """Aggregate across seeds for one task. Written to disk as
    bench/results/<run_label>_<task_id>_summary.json. Card 5 reads this to build
    baseline_v1.json."""
    run_label: str
    task_id: str
    seeds: List[int]
    metrics: Dict[str, Dict[str, Any]]  # metric_name -> {per_seed, mean, ci95}
    primary_metric: str = "score"
    stub_placeholder: bool = False
    notes: str = ""

    def to_json_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


# ---------------------------------------------------------------------------
# Task interface
# ---------------------------------------------------------------------------


class EvalTask(Protocol):
    """Uniform task interface. Every task module exposes a single subclass
    instance via `get_task()`. Stubs implement the same methods and return
    `STUB_PLACEHOLDER: True` in `task_meta` so the runner can record them.

    Implementations:
        task_id              short stable id used in result filenames
        task_meta            metadata recorded into every SeedResult
        primary_metric       metric name aggregated for the headline CI
        load_problems        return the frozen problem set for this task
        build_prompt         render the prompt for one problem
        score                score a model completion against a problem,
                             returning {metric_name: float}
        stub_placeholder     False for real tasks, True for stubs

    The default base class `EvalTaskBase` below implements `run_problem` which
    glues build_prompt + provider call + score together; tasks override only
    what differs.
    """

    task_id: str
    primary_metric: str
    stub_placeholder: bool

    def task_meta(self) -> Dict[str, Any]: ...

    def load_problems(self) -> Sequence[Problem]: ...

    def build_prompt(self, problem: Problem) -> str: ...

    def score(self, problem: Problem, completion: str) -> Dict[str, float]: ...


class EvalTaskBase:
    """Default base providing the boilerplate every task shares. Concrete tasks
    override the four abstract hooks below.

    Important: scorers MUST be deterministic given a fixed problem and
    completion. The pytest suite asserts this for the wired tasks.
    """

    task_id: str = "abstract"
    primary_metric: str = "score"
    secondary_metrics: List[str] = []
    stub_placeholder: bool = False
    dataset_id: str = "abstract"

    def task_meta(self) -> Dict[str, Any]:
        return {
            STUB_PLACEHOLDER_FIELD: self.stub_placeholder,
            "dataset": self.dataset_id,
            "primary_metric": self.primary_metric,
            "secondary_metrics": list(self.secondary_metrics),
        }

    # ----- hooks ------------------------------------------------------------

    def load_problems(self) -> Sequence[Problem]:
        raise NotImplementedError

    def build_prompt(self, problem: Problem) -> str:
        raise NotImplementedError

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _to_json_dict(obj: Any) -> Any:
    """Convert a (possibly nested) dataclass tree into a plain dict with
    deterministic types. Floats are kept as floats; numpy types are coerced."""
    if dataclasses.is_dataclass(obj):
        return {k: _to_json_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_json_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_dict(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    # Coerce anything else (numpy scalars, etc.) via float()
    try:
        return float(obj)
    except (TypeError, ValueError):
        return str(obj)


def write_json(path: str, payload: Any) -> None:
    """Write `payload` to `path` as pretty-printed JSON with sorted keys for
    deterministic diffs."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)
        f.write("\n")


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts. One record per line."""
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out
