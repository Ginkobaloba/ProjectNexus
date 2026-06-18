"""Stub tasks (2, 3, 4, 6) return the documented placeholder."""
from __future__ import annotations

import pytest

from bench.eval.tasks import all_task_ids, get_task


STUB_IDS = ["routing", "tool_use", "rag_qa", "guards"]
WIRED_IDS = ["builder", "code_pub"]


@pytest.mark.parametrize("task_id", STUB_IDS)
def test_stub_task_marked_placeholder(task_id):
    task = get_task(task_id)
    assert task.stub_placeholder is True
    meta = task.task_meta()
    assert meta["stub_placeholder"] is True
    # one-sentence design note exists, per Card 4 acceptance criterion
    assert "design_note" in meta
    assert isinstance(meta["design_note"], str)
    assert len(meta["design_note"]) > 20


@pytest.mark.parametrize("task_id", STUB_IDS)
def test_stub_task_score_is_fixed_zero(task_id):
    task = get_task(task_id)
    p = next(iter(task.load_problems()))
    metrics = task.score(p, "anything")
    primary = task.primary_metric
    assert primary in metrics
    assert metrics[primary] == 0.0


@pytest.mark.parametrize("task_id", WIRED_IDS)
def test_wired_task_not_placeholder(task_id):
    task = get_task(task_id)
    assert task.stub_placeholder is False
    assert task.task_meta()["stub_placeholder"] is False


def test_registry_covers_six_tasks():
    ids = all_task_ids()
    assert set(ids) == set(STUB_IDS) | set(WIRED_IDS)
    assert len(ids) == 6
