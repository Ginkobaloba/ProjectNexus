"""
Task 5: HumanEval+/MBPP (general coding).

Primary metric: pass@1 via unit-test execution (the free oracle).

Dataset sources (when fetched live):
    HumanEval+:  evalplus/humanevalplus on Hugging Face. License: MIT for the
                 underlying HumanEval, MIT for the EvalPlus extensions.
                 See https://huggingface.co/datasets/evalplus/humanevalplus
    MBPP:        mbpp on Hugging Face. License: CC-BY-4.0.
                 See https://huggingface.co/datasets/mbpp

Local cache: bench/eval/datasets/cache/. Files are gitignored; the loader
populates this on first use.

Skeleton mode: this module ships a tiny local stand-in
(bench/eval/datasets/code_pub_skeleton_v1.jsonl) with 3 trivial problems so
the bench wiring is exercised end-to-end in the test suite and in CI without
a network call. Set NEXUS_BENCH_CODEPUB_SOURCE=humanevalplus or =mbpp to
switch to the real dataset; the loader will lazy-import `datasets` and fail
loudly if it is not installed.

Execution sandbox: the scorer runs the model completion + the unit test in a
subprocess with a wall-clock timeout, stdin/stdout captured, no network. This
is not a hardened sandbox; it relies on the caller controlling the inputs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ..base import EvalTaskBase, Problem, load_jsonl


HERE = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = HERE.parent / "datasets" / "code_pub_skeleton_v1.jsonl"
PROMPT_PATH = HERE.parent / "prompts" / "code_pub.txt"
CACHE_DIR = HERE.parent / "datasets" / "cache"

# Default execution timeout per problem.
DEFAULT_EXEC_TIMEOUT_S = 8.0


class CodePubTask(EvalTaskBase):
    task_id = "code_pub"
    primary_metric = "pass_at_1"
    secondary_metrics: List[str] = []
    stub_placeholder = False
    dataset_id = "code_pub_skeleton_v1"

    def __init__(
        self,
        dataset_path: Path | None = None,
        prompt_path: Path = PROMPT_PATH,
        exec_timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
    ):
        self.exec_timeout_s = exec_timeout_s
        self.prompt_path = Path(prompt_path)
        self._prompt_template: str | None = None
        # Source switch via env var so CLI users do not have to plumb args.
        source = os.environ.get("NEXUS_BENCH_CODEPUB_SOURCE", "skeleton")
        if dataset_path is not None:
            self.dataset_path = Path(dataset_path)
            self.dataset_id = dataset_path.stem
        elif source == "skeleton":
            self.dataset_path = DEFAULT_DATASET_PATH
        else:
            # Lazy HF fetch path. Cache and convert to our JSONL shape on first
            # use; subsequent calls reuse the cached file.
            cached = CACHE_DIR / f"{source}_v1.jsonl"
            if not cached.exists():
                _materialize_hf_dataset(source=source, dst=cached)
            self.dataset_path = cached
            self.dataset_id = cached.stem

    # -----------------------------------------------------------------
    # EvalTaskBase hooks
    # -----------------------------------------------------------------

    def load_problems(self) -> Sequence[Problem]:
        records = load_jsonl(str(self.dataset_path))
        out: List[Problem] = []
        for rec in records:
            out.append(
                Problem(
                    problem_id=rec["problem_id"],
                    prompt=rec["prompt"],
                    reference={
                        "entry_point": rec.get("entry_point", ""),
                        "test": rec.get("test", ""),
                    },
                    meta=rec.get("meta", {}),
                )
            )
        return out

    def build_prompt(self, problem: Problem) -> str:
        if self._prompt_template is None:
            self._prompt_template = self.prompt_path.read_text(encoding="utf-8")
        return self._prompt_template.replace("{prompt}", problem.prompt)

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        code = _extract_python_block(completion)
        if code is None:
            return {"pass_at_1": 0.0}
        ok, _err = _run_unit_test(
            program=code,
            test=problem.reference.get("test", ""),
            timeout_s=self.exec_timeout_s,
        )
        return {"pass_at_1": 1.0 if ok else 0.0}

    def task_meta(self) -> Dict[str, Any]:
        meta = super().task_meta()
        meta["n_problems"] = len(self.load_problems())
        meta["dataset_path"] = str(self.dataset_path)
        meta["prompt_path"] = str(self.prompt_path)
        meta["exec_timeout_s"] = self.exec_timeout_s
        meta["source"] = os.environ.get("NEXUS_BENCH_CODEPUB_SOURCE", "skeleton")
        return meta


def get_task() -> CodePubTask:
    return CodePubTask()


# ---------------------------------------------------------------------------
# Scoring internals
# ---------------------------------------------------------------------------


def _extract_python_block(text: str) -> str | None:
    """Pull the first fenced code block out of `text`. Accepts ```python or
    bare ```. Falls back to the raw text if it looks like a def."""
    import re
    pat = re.compile(r"```(?:python|py)?\s*\n(?P<body>.*?)\n```", re.DOTALL)
    m = pat.search(text or "")
    if m is not None:
        return m.group("body")
    stripped = (text or "").strip()
    if stripped.startswith("def "):
        return stripped
    return None


def _run_unit_test(
    program: str,
    test: str,
    timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
) -> tuple[bool, str]:
    """Execute `program` + `test` in a Python subprocess. Returns (passed, err)."""
    if not test:
        return False, "no_test"
    script = program + "\n\n" + test + "\nprint('OK')\n"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        path = f.name
    try:
        try:
            proc = subprocess.run(
                [sys.executable, path],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if proc.returncode != 0:
            return False, f"nonzero_exit: {proc.stderr.strip()[:200]}"
        if "OK" not in (proc.stdout or ""):
            return False, "no_ok_marker"
        return True, ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _materialize_hf_dataset(source: str, dst: Path) -> None:
    """Lazy fetch from Hugging Face, convert to our JSONL shape, cache to dst.
    Raises with a clear hint if `datasets` is not installed."""
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "datasets package not installed. "
            "pip install datasets, or set NEXUS_BENCH_CODEPUB_SOURCE=skeleton "
            "to use the bundled stand-in."
        ) from e
    dst.parent.mkdir(parents=True, exist_ok=True)
    if source == "humanevalplus":
        ds = load_dataset("evalplus/humanevalplus", split="test")
        records = [
            {
                "problem_id": str(row.get("task_id", f"hep_{i:04d}")),
                "prompt": row["prompt"],
                "entry_point": row.get("entry_point", ""),
                "test": row.get("test", ""),
                "meta": {"source": "humanevalplus", "license": "MIT"},
            }
            for i, row in enumerate(ds)
        ]
    elif source == "mbpp":
        ds = load_dataset("mbpp", split="test")
        records = [
            {
                "problem_id": f"mbpp_{row['task_id']:04d}",
                "prompt": row["text"],
                "entry_point": "",  # MBPP does not always pin an entry point
                "test": "\n".join(row["test_list"]),
                "meta": {"source": "mbpp", "license": "CC-BY-4.0"},
            }
            for row in ds
        ]
    else:
        raise ValueError(f"unknown code_pub source: {source}")
    with open(dst, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
