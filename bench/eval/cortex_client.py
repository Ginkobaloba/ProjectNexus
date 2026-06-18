# bench/eval/cortex_client.py
"""
Minimal OpenAI-compatible client for the vLLM Cortex endpoint.

Stdlib-only (urllib), matching the dependency-light style of bench/latency_bench.py
so the harness runs from any node without an install step. The Cortex is the
canonical 4090 baseline: cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit served by
vLLM on :8000 with an OpenAI /v1/chat/completions surface.

The client supports n-sampling in a single request (vLLM `n`), which is what
makes verifier-guided best-of-N cheap: the 8 candidates are decoded as a batched
beam on one GPU pass rather than 8 sequential round trips.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class CortexError(RuntimeError):
    """Raised when the Cortex endpoint is unreachable or returns an error."""


@dataclass
class ChatResult:
    """One chat completion call. `texts` holds the n sampled completions."""

    texts: List[str]
    finish_reasons: List[str]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.texts)


class CortexClient:
    """Thin client over an OpenAI-compatible /v1 surface.

    model: pass None to auto-detect the served id from /v1/models. The vLLM
    instance reports the full HF id (e.g. cyankiwi/Qwen3-30B-...), which is the
    id the chat endpoint expects, so auto-detect is the safe default.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 180.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.model = model or self._detect_model()

    # -- internal HTTP -------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise CortexError(f"HTTP {exc.code} from {path}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CortexError(f"Cortex unreachable at {self.base_url}{path}: {exc}") from exc

    def _detect_model(self) -> str:
        req = urllib.request.Request(f"{self.base_url}/v1/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise CortexError(
                f"Could not auto-detect model from {self.base_url}/v1/models: {exc}. "
                f"Pass model= explicitly or start the cortex."
            ) from exc
        data = payload.get("data") or []
        if not data:
            raise CortexError(f"/v1/models returned no models: {payload}")
        return data[0]["id"]

    def model_meta(self) -> Dict[str, Any]:
        """Served model metadata (id, max_model_len) for the run record."""
        req = urllib.request.Request(f"{self.base_url}/v1/models", headers=self._headers())
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read())
        m = (payload.get("data") or [{}])[0]
        return {"id": m.get("id"), "max_model_len": m.get("max_model_len")}

    def server_version(self) -> Optional[str]:
        """vLLM version string for the run record, or None if unavailable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/version", headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("version")
        except Exception:  # noqa: BLE001 - version is best-effort metadata
            return None

    # -- public API ----------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        top_p: float = 1.0,
        n: int = 1,
        seed: Optional[int] = None,
        max_tokens: int = 4096,
    ) -> ChatResult:
        """One chat completion. Returns n sampled texts (n=1 for greedy)."""
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "n": n,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            body["seed"] = seed
        t0 = time.monotonic()
        payload = self._post("/v1/chat/completions", body)
        latency_ms = (time.monotonic() - t0) * 1000.0
        choices = payload.get("choices") or []
        texts = [(c.get("message") or {}).get("content") or "" for c in choices]
        finishes = [c.get("finish_reason") or "" for c in choices]
        usage = payload.get("usage") or {}
        return ChatResult(
            texts=texts,
            finish_reasons=finishes,
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
            latency_ms=latency_ms,
            raw=payload,
        )
