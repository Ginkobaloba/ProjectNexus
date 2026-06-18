"""Task 5 (HumanEval+/MBPP skeleton) scorer is deterministic on a fixed
completion. Uses the bundled local stand-in dataset; no HF fetch."""
from __future__ import annotations

import pytest

from bench.eval.tasks.code_pub import (
    CodePubTask,
    _extract_python_block,
    _run_unit_test,
)


def test_extract_python_block():
    fenced = "```python\ndef add(a,b):\n    return a+b\n```"
    assert _extract_python_block(fenced).strip().startswith("def add")
    plain = "def f():\n    return 1"
    assert _extract_python_block(plain) == plain
    assert _extract_python_block("no code here") is None


def test_run_unit_test_passing():
    program = "def add(a,b):\n    return a+b"
    test = "assert add(1,2)==3"
    ok, err = _run_unit_test(program, test, timeout_s=5)
    assert ok is True
    assert err == ""


def test_run_unit_test_failing():
    program = "def add(a,b):\n    return a-b"  # buggy
    test = "assert add(1,2)==3"
    ok, err = _run_unit_test(program, test, timeout_s=5)
    assert ok is False


def test_run_unit_test_timeout():
    program = "def loop():\n    import time\n    time.sleep(10)"
    test = "loop()"
    ok, err = _run_unit_test(program, test, timeout_s=1.0)
    assert ok is False
    assert err == "timeout"


def test_code_pub_score_is_deterministic_given_fixed_completion():
    task = CodePubTask()
    problems = list(task.load_problems())
    assert problems, "skeleton dataset must have at least one problem"
    p = problems[0]  # the cp_001 add() problem
    completion = (
        "```python\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        "```"
    )
    m1 = task.score(p, completion)
    m2 = task.score(p, completion)
    assert m1 == m2
    assert m1["pass_at_1"] == 1.0


def test_code_pub_score_zero_on_bad_solution():
    task = CodePubTask()
    p = list(task.load_problems())[0]
    completion = (
        "```python\n"
        "def add(a, b):\n"
        "    return 0\n"
        "```"
    )
    m = task.score(p, completion)
    assert m["pass_at_1"] == 0.0
