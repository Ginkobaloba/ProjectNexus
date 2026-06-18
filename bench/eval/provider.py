"""
bench.eval.provider: BYO-LLM adapter (the runner is provider-agnostic).

Per Drew's standing tenet (Gantry brand direction): the bench client must work
against any OpenAI-compatible endpoint. Default config points at the 4090
cortex (vLLM serving cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit on
http://localhost:8000/v1). To swap to the GPT-5.1 gov endpoint or any other
provider, override DEFAULT_PROVIDER via env vars or pass --provider on the CLI.

Env vars (read at provider construction):
    NEXUS_BENCH_PROVIDER     "openai_compat" (default) | "stub"
    NEXUS_BENCH_BASE_URL     default http://localhost:8000/v1
    NEXUS_BENCH_MODEL        default "cortex"
    NEXUS_BENCH_API_KEY      default "" (vLLM ignores it; gov endpoint needs it)
    NEXUS_BENCH_TIMEOUT_S    default 120.0

The runner records the full ProviderConfig snapshot into every SeedResult so
that any future re-run can validate it hit the same endpoint, model, and
sampling.

Adding a new provider: subclass LLMProvider, implement complete(), register it
in PROVIDER_REGISTRY at the bottom of this file. The CLI picks it up via
--provider <kind>.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from .base import ProviderConfig, Sampling


# ---------------------------------------------------------------------------
# Public protocol
# ---------------------------------------------------------------------------


class LLMProvider(Protocol):
    """Minimal completion interface used by the runner."""

    config: ProviderConfig

    def complete(self, prompt: str, sampling: Sampling) -> "CompletionResponse":
        ...


@dataclass
class CompletionResponse:
    """Normalized completion response. Token counts may be approximate when the
    backend does not return them; bench records what the provider gave us."""
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    raw: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (default; vLLM on the 4090 cortex)
# ---------------------------------------------------------------------------


class OpenAICompatProvider:
    """Talks to any /v1/chat/completions endpoint that follows OpenAI's shape.

    Default base_url = http://localhost:8000/v1, default model = "cortex".
    Both are what `automation/scripts/setup-cortex-llm.sh` configures for the
    4090 vLLM serving Qwen3-30B-A3B-Instruct-2507-AWQ-4bit.

    Implementation note: this uses urllib (stdlib only) on purpose. No openai-
    python dep. Keeps the bench runnable on a stock Python install.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 120.0,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.config = ProviderConfig(
            kind="openai_compat",
            base_url=self.base_url,
            model=self.model,
            extra=dict(extra or {}),
        )

    def complete(self, prompt: str, sampling: Sampling) -> CompletionResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_tokens": sampling.max_tokens,
            "seed": sampling.seed,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise ProviderError(
                f"OpenAI-compat HTTP {e.code}: {err_body}"
            ) from e
        except urllib.error.URLError as e:
            raise ProviderError(f"OpenAI-compat URL error: {e}") from e
        latency_s = time.perf_counter() - t0
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        return CompletionResponse(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_s=latency_s,
            raw=data,
        )


class ProviderError(RuntimeError):
    """Raised when the provider call fails. The runner records this as a
    per-problem `error` field and counts the problem as zero on every metric."""


# ---------------------------------------------------------------------------
# Stub provider (offline; for tests and dry runs)
# ---------------------------------------------------------------------------


class StubProvider:
    """Returns a canned response for every prompt. Used by the test suite and
    by `python -m bench.eval --provider stub` for dry-running the wiring.

    Accepts either a fixed string or a callable (prompt, sampling) -> str. The
    callable form lets tests assert per-problem behavior."""

    def __init__(
        self,
        canned: str = "",
        canned_fn: Optional[Callable[[str, Sampling], str]] = None,
        base_url: str = "stub://local",
        model: str = "stub",
    ):
        self.canned = canned
        self.canned_fn = canned_fn
        self.config = ProviderConfig(
            kind="stub",
            base_url=base_url,
            model=model,
            extra={},
        )

    def complete(self, prompt: str, sampling: Sampling) -> CompletionResponse:
        if self.canned_fn is not None:
            text = self.canned_fn(prompt, sampling)
        else:
            text = self.canned
        return CompletionResponse(
            text=text,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(text.split()),
            latency_s=0.0,
            raw={"stub": True},
        )


# ---------------------------------------------------------------------------
# Registry + env-driven default
# ---------------------------------------------------------------------------


def default_provider_from_env() -> LLMProvider:
    """Build a provider from NEXUS_BENCH_* env vars. Default: OpenAI-compat
    against http://localhost:8000/v1, model="cortex". This is the 4090 cortex.

    To swap to the GPT-5.1 gov endpoint (or any OpenAI-compat target):
        NEXUS_BENCH_BASE_URL=https://gov.example/v1
        NEXUS_BENCH_MODEL=gpt-5.1
        NEXUS_BENCH_API_KEY=<key>
    """
    kind = os.environ.get("NEXUS_BENCH_PROVIDER", "openai_compat")
    if kind == "stub":
        return StubProvider(canned="STUB_COMPLETION")
    base_url = os.environ.get("NEXUS_BENCH_BASE_URL", "http://localhost:8000/v1")
    model = os.environ.get("NEXUS_BENCH_MODEL", "cortex")
    api_key = os.environ.get("NEXUS_BENCH_API_KEY", "")
    timeout_s = float(os.environ.get("NEXUS_BENCH_TIMEOUT_S", "120.0"))
    return OpenAICompatProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_s=timeout_s,
    )


PROVIDER_REGISTRY: Dict[str, str] = {
    "openai_compat": "bench.eval.provider:OpenAICompatProvider",
    "stub": "bench.eval.provider:StubProvider",
}
