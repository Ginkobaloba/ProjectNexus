"""Shared pytest fixtures for the bench.eval suite.

The suite runs entirely offline: every test uses StubProvider, writes into a
tmp_path, and never touches the network or the real cortex.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make sure the repo root is on sys.path so `import bench.eval` works without
# an editable install. The tests/ dir is one level below the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def tmp_results_dir(tmp_path: Path) -> Path:
    d = tmp_path / "results"
    d.mkdir()
    return d
