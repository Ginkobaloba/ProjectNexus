"""
Task 6: General-capability regression guards. STUB.

Design note (one-sentence per Card 4 plan):
    Run MMLU-Pro, GPQA-diamond, IFEval, and MT-Bench through
    lm-evaluation-harness as the family-6 regression-tolerance guard so a
    specialist that wins its niche by forgetting how to think gets caught.

Skeleton behavior matches Task 2.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ..base import EvalTaskBase, Problem


class GuardsTask(EvalTaskBase):
    task_id = "guards"
    primary_metric = "guard_aggregate"
    secondary_metrics = ["mmlu_pro", "gpqa_diamond", "ifeval", "mt_bench"]
    stub_placeholder = True
    dataset_id = "guards_stub_v0"

    def load_problems(self) -> Sequence[Problem]:
        return [
            Problem(
                problem_id="guards_stub_001",
                prompt="(stub) family-6 regression guard placeholder",
                reference={"sub_tasks": ["mmlu_pro", "gpqa_diamond", "ifeval", "mt_bench"]},
                meta={"family": "guards", "stub": True},
            ),
        ]

    def build_prompt(self, problem: Problem) -> str:
        return problem.prompt

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        return {
            "guard_aggregate": 0.0,
            "mmlu_pro": 0.0,
            "gpqa_diamond": 0.0,
            "ifeval": 0.0,
            "mt_bench": 0.0,
        }

    def task_meta(self) -> Dict[str, Any]:
        meta = super().task_meta()
        meta["n_problems"] = 1
        meta["design_note"] = (
            "MMLU-Pro + GPQA-diamond + IFEval + MT-Bench via "
            "lm-evaluation-harness, used as regression guards (not targets). "
            "To be wired in a follow-on card."
        )
        return meta


def get_task() -> GuardsTask:
    return GuardsTask()
