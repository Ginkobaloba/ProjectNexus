"""
bench.eval.tasks: one module per task family.

Layout (matches NEXUS_PATH_TO_OUTPERFORM section 1.2):
    builder.py    Task 1: workflow synthesis (Builder) - FULL
    routing.py    Task 2: intent parse + routing                 - STUB
    tool_use.py   Task 3: agentic tool use / decomposition       - STUB
    rag_qa.py     Task 4: RAG Q&A over memory                    - STUB
    code_pub.py   Task 5: HumanEval+/MBPP                        - FULL
    guards.py     Task 6: general-capability regression guards   - STUB

To add a Task N: drop a new module here, expose a `get_task() -> EvalTask`
factory, and register the task_id in `TASK_REGISTRY` below. The runner picks
it up automatically.

The stubs are kept symmetric on purpose: same shape, same JSON output, with
`stub_placeholder=True` so the bench runner doesn't break and Card 5 baselines
record them as "not yet measured" rather than "scored zero".
"""
from __future__ import annotations

from typing import Callable, Dict

from .builder import get_task as _builder
from .routing import get_task as _routing
from .tool_use import get_task as _tool_use
from .rag_qa import get_task as _rag_qa
from .code_pub import get_task as _code_pub
from .guards import get_task as _guards


# Registry: task_id -> zero-arg factory returning a fresh EvalTask.
TASK_REGISTRY: Dict[str, Callable[[], object]] = {
    "builder": _builder,
    "routing": _routing,
    "tool_use": _tool_use,
    "rag_qa": _rag_qa,
    "code_pub": _code_pub,
    "guards": _guards,
}


def get_task(task_id: str):
    """Return a fresh EvalTask instance for `task_id`. Raises KeyError if the
    id is not registered."""
    try:
        return TASK_REGISTRY[task_id]()
    except KeyError as e:
        raise KeyError(
            f"unknown task_id {task_id!r}; known: {sorted(TASK_REGISTRY)}"
        ) from e


def all_task_ids():
    return sorted(TASK_REGISTRY)
