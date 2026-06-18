"""bench.eval: model-quality eval harness for project-nexus (Sprint 3d Card 4).

See bench/README.md for runner usage, task interface, how to add Task N, how to
swap providers. Headline metric is Task 1 (Builder) valid@1.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .base import (  # noqa: F401
    EvalTask,
    Problem,
    ProblemResult,
    SeedResult,
    TaskSummary,
    ProviderConfig,
    Sampling,
    STUB_PLACEHOLDER_FIELD,
)
from .scoring import bootstrap_ci, percentile  # noqa: F401
from .provider import LLMProvider, OpenAICompatProvider, StubProvider  # noqa: F401
from .runner import BenchRunner  # noqa: F401
