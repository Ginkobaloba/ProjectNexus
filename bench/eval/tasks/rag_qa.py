"""
Task 4: RAG Q&A over memory. STUB.

Design note (one-sentence per Card 4 plan):
    Score answer correctness on questions over recorded session/episodic logs,
    with retrieval recall@k reported separately, using an LLM judge (Opus)
    with a pinned rubric for the correctness call.

Skeleton behavior matches Task 2.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ..base import EvalTaskBase, Problem


class RAGQATask(EvalTaskBase):
    task_id = "rag_qa"
    primary_metric = "answer_correctness"
    secondary_metrics = ["retrieval_recall_at_k", "groundedness"]
    stub_placeholder = True
    dataset_id = "rag_qa_stub_v0"

    def load_problems(self) -> Sequence[Problem]:
        return [
            Problem(
                problem_id="rag_qa_stub_001",
                prompt="(stub) What did Drew decide about Sprint 4 Chunk A?",
                reference={"gold_answer": "stub", "gold_passages": []},
                meta={"family": "rag_qa", "stub": True},
            ),
        ]

    def build_prompt(self, problem: Problem) -> str:
        return problem.prompt

    def score(self, problem: Problem, completion: str) -> Dict[str, float]:
        return {
            "answer_correctness": 0.0,
            "retrieval_recall_at_k": 0.0,
            "groundedness": 0.0,
        }

    def task_meta(self) -> Dict[str, Any]:
        meta = super().task_meta()
        meta["n_problems"] = 1
        meta["design_note"] = (
            "LLM-judge answer correctness + retrieval recall@k on questions "
            "grounded in Nexus episodic memory. To be wired in a follow-on card."
        )
        return meta


def get_task() -> RAGQATask:
    return RAGQATask()
