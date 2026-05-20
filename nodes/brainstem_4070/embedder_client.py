# nodes/brainstem_4070/embedder_client.py
"""
HTTP client for the embedder service. The brainstem no longer owns the
embedding model or the Chroma store; it routes both write-on-turn and
retrieve-before-generate through this client.

Kept deliberately small: one class, four methods, requests-based.
Async can come later if write/retrieve start showing up in turn p95.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("brainstem_4070.embedder_client")


class EmbedderError(RuntimeError):
    """Raised when the embedder service is unreachable or returns an error."""


class EmbedderClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- internals ----------------------------------------------------
    def _post(
        self,
        path: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            res = requests.post(url, json=payload, headers=headers or {}, timeout=self.timeout)
            res.raise_for_status()
            return res.json()
        except requests.RequestException as exc:
            raise EmbedderError(f"POST {url} failed: {exc}") from exc

    # -- public API ---------------------------------------------------
    def health(self) -> Dict[str, Any]:
        try:
            res = requests.get(f"{self.base_url}/health", timeout=5)
            res.raise_for_status()
            return {"reachable": True, **res.json()}
        except requests.RequestException as exc:
            return {"reachable": False, "error": str(exc)}

    def embed(self, texts: List[str]) -> Dict[str, Any]:
        return self._post("/embed", {"texts": texts})

    def memory_write(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        turn_idx: int,
        ts: str,
        model_used: str = "",
        user_token_count: int = 0,
        assistant_token_count: int = 0,
        source_service: str = "brainstem_4070",
        tool_calls_present: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "user_text": user_text,
            "assistant_text": assistant_text,
            "turn_idx": turn_idx,
            "ts": ts,
            "model_used": model_used,
            "user_token_count": user_token_count,
            "assistant_token_count": assistant_token_count,
            "source_service": source_service,
            "tool_calls_present": tool_calls_present,
        }
        return self._post("/memory/write", payload, headers={"X-Session-Id": session_id})

    def memory_query(
        self,
        session_id: str,
        query: str,
        k: int = 5,
        session_id_filter: Optional[str] = None,
        exclude_parent_turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query, "k": k}
        if session_id_filter:
            payload["session_id_filter"] = session_id_filter
        if exclude_parent_turn_id:
            payload["exclude_parent_turn_id"] = exclude_parent_turn_id
        return self._post("/memory/query", payload, headers={"X-Session-Id": session_id})
