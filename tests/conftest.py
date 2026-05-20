"""
Shared pytest config for the Nexus test suite.

Makes the in-repo `nodes/` and the repo root importable without an
install step. The brainstem package layout lives under `nodes/`, which
mirrors how the docker image lays the code out at `/app`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "nodes"))
sys.path.insert(0, str(REPO_ROOT))
