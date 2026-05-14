# nodes/brainstem_4070/cortex_client.py
"""
4070-side HTTP client to the 4090 Cortex inference service.

Cortex runs vLLM with an OpenAI-compatible API (default http://192.168.1.140:8000).
This client is the brainstem's outbound leg of the 4070 <-> 4090 fabric link.

Scope for this milestone ("the two boxes can talk"): a plain one-shot
request/response client. The bidirectional callback channel the architecture
calls for is a later step and is intentionally not implemented here yet.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("brainstem_4070.cortex_client")


class CortexError(RuntimeError):
    """Raised when the Cortex endpoint is unreachable or returns an error."""


class CortexClient:
    """Minimal OpenAI-compatible client for the 4090 vLLM endpoint.

    The served model id is discovered from ``/v1/models`` and cached, so the
    caller does not have to hard-code the model name. One retry is attempted on
    transient connection failures, which is sufficient for Phase 0.
    """

    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._model_id: Optional[str] = None

    # -- internals ---------------------------------------------------------
    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                res = requests.get(url, timeout=self.timeout)
                res.raise_for_status()
                return res.json()
            except requests.RequestException as exc:  # transient: retry once
                last_exc = exc
                logger.warning("GET %s failed (attempt %d/2): %s", url, attempt, exc)
        raise CortexError(f"GET {url} failed: {last_exc}") from last_exc

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                res = requests.post(url, json=payload, timeout=self.timeout)
                res.raise_for_status()
                return res.json()
            except requests.RequestException as exc:  # transient: retry once
                last_exc = exc
                logger.warning("POST %s failed (attempt %d/2): %s", url, attempt, exc)
        raise CortexError(f"POST {url} failed: {last_exc}") from last_exc

    # -- public API --------------------------------------------------------
    def list_models(self) -> List[str]:
        """Return the model ids the Cortex endpoint is serving."""
        data = self._get("/v1/models")
        return [m["id"] for m in data.get("data", [])]

    def resolve_model(self, refresh: bool = False) -> str:
        """Return (and cache) the served model id from the Cortex endpoint."""
        if self._model_id is None or refresh:
            models = self.list_models()
            if not models:
                raise CortexError("Cortex endpoint reports no served models")
            self._model_id = models[0]
            logger.info("Resolved Cortex model: %s", self._model_id)
        return self._model_id

    def health(self) -> Dict[str, Any]:
        """Lightweight reachability check. Does not raise; returns a status dict."""
        try:
            models = self.list_models()
            return {"reachable": True, "models": models}
        except CortexError as exc:
            return {"reachable": False, "error": str(exc)}

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a chat completion against Cortex.

        Returns a dict with the assistant ``text``, the ``model`` that produced
        it, the ``finish_reason``, and token ``usage``.
        """
        payload = {
            "model": model or self.resolve_model(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = self._post("/v1/chat/completions", payload)
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise CortexError(f"Unexpected Cortex response shape: {data}") from exc
        return {
            "text": text,
            "model": data.get("model", payload["model"]),
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage", {}),
        }

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """Convenience wrapper: build a messages list from a plain prompt."""
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
