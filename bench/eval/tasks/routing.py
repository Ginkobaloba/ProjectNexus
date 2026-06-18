"""
Task 2: Intent parse + routing classification. STUB.

Design note (one-sentence per Card 4 plan):
    Score the Nexus Orchestrator's request -> intent-object + chosen-workflow
    mapping with exact-match routing top-1 accuracy and field-level F1 on the
    intent object, on a frozen sample of logged Orchestrator decisions.

Skeleton behavior:
    - returns one synthetic "problem" so the runner produces a valid
      SeedResult shape end-to-end
    - emits routing_top1 = 0.0 and intent_f1 = 0.0
    - stub_placeholder = True is recorded in task_meta and SeedResult; Card 5
      baselines render this task as "not yet measured" rather than scoring it
      zero
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ..base import EvalTaskBase, Problem


class RoutingTask(EvalTaskBase):
    task_id = "routing"
    primary_metric = "routing_top1"
    secondary_metrics = ["intent_f1"]
    stub_placeholder = True
    dataset_id = "routing_stub_v0"

    def load_problems(self) -> Sequence[Problem]:
        return [
            Problem(
                problem_id="routing_stub_001",
                prompt="(stub) Route this request: \"file my receipts.\"",
                reference={"chosen_workflow": "stub", "intent": {}},
                meta={"family": "routing", "stub": True},
            ),
        ]

    def build_prompt(self, problem: Problem) -> str:
        return problem.prompt

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        # Fixed-score result. Card 5 treats this as "not measured" via the
        # stub_placeholder flag in the SeedResult JSON.
        return {"routing_top1": 0.0, "intent_f1": 0.0}

    def task_meta(self) -> Dict[str, Any]:
        meta = super().task_meta()
        meta["n_problems"] = 1
        meta["design_note"] = (
            "Routing top-1 accuracy + intent F1 on logged Orchestrator "
            "decisions. To be wired in a follow-on card."
        )
        return meta


def get_task() -> RoutingTask:
    return RoutingTask()
