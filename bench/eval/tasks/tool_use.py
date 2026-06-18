"""
Task 3: Agentic tool use / compound decomposition. STUB.

Design note (one-sentence per Card 4 plan):
    Score task success on held-out compound requests, cross-checked against a
    public AgentBench / tau-bench slice, with tool-selection accuracy and
    steps-to-success vs gold as secondaries.

Skeleton behavior matches Task 2.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ..base import EvalTaskBase, Problem


class ToolUseTask(EvalTaskBase):
    task_id = "tool_use"
    primary_metric = "task_success"
    secondary_metrics = ["tool_selection_accuracy", "steps_to_success_delta"]
    stub_placeholder = True
    dataset_id = "tool_use_stub_v0"

    def load_problems(self) -> Sequence[Problem]:
        return [
            Problem(
                problem_id="tool_use_stub_001",
                prompt="(stub) Find a flight to Boston next Tuesday under $400.",
                reference={"gold_tools": [], "gold_steps": 0},
                meta={"family": "tool_use", "stub": True},
            ),
        ]

    def build_prompt(self, problem: Problem) -> str:
        return problem.prompt

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        return {
            "task_success": 0.0,
            "tool_selection_accuracy": 0.0,
            "steps_to_success_delta": 0.0,
        }

    def task_meta(self) -> Dict[str, Any]:
        meta = super().task_meta()
        meta["n_problems"] = 1
        meta["design_note"] = (
            "Compound-request task success + tool-selection accuracy, anchored "
            "against an AgentBench slice. To be wired in a follow-on card."
        )
        return meta


def get_task() -> ToolUseTask:
    return ToolUseTask()
