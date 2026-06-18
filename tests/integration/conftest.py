"""
Sprint 3d integration suite fixtures.

The integration tests exercise the brainstem from a generic-client
perspective: bearer token in, JSON out, with the X-Session-Id header
carrying session identity. Downstream services (Cortex on 4090, the
embedder + Chroma) are stubbed in-process so the suite is hermetic and
runs in CI without network access. The fakes preserve the contracts
the real services expose, so a passing suite is genuine evidence that
the brainstem wiring works end-to-end.

The fakes:

* FakeCortex
  A controllable inference peer. `text_factory(prompt, system, ...)`
  builds the assistant message. `down` flips the next call to raise
  CortexError, so the 503 Cortex-down contract gets exercised. The
  unit-level Cortex-down behavior also lives in tests/test_cortex_down.py;
  this suite layers the cross-session recall + auth + header contracts
  on top of the same control.

* FakeMemory
  An in-process stand-in for the embedder's `memory_write` and
  `memory_query` paths. memory_write appends a `{session_id, user_text,
  assistant_text, turn_idx, ts}` row. memory_query returns the rows
  whose `user_text` or `assistant_text` shares a non-stopword token with
  the query, ranked by overlap size. This is dumb on purpose: a real
  embedding store ranks by cosine similarity, but the integration test
  only needs to assert that retrieve-before-generate plumbs the prior
  turn into the prompt seen by Cortex. A token-overlap fake is enough
  to validate that the X-Session-Id propagated, the prior turn was
  written under the right session, and the cross-session query returns
  it.

Tests should NEVER reach into these fakes to fudge an assertion. They
exist to make the brainstem's outbound calls observable.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

import pytest


# ---------------------------------------------------------------------------
# In-process fakes
# ---------------------------------------------------------------------------


_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "of", "in", "on", "at", "to", "for", "with",
    "and", "or", "but", "i", "you", "we", "they", "it", "this", "that",
    "what", "who", "where", "when", "why", "how", "my", "your", "our",
    "from", "as", "by", "about", "into",
}


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", (text or "").lower()) if t and t not in _STOPWORDS]


@dataclass
class FakeCortex:
    """In-process stand-in for the 4090 Cortex peer.

    The brainstem talks to Cortex via `cortex.generate(...)`. We patch
    that method to call this object instead. The object records every
    call so tests can assert on what the brainstem actually sent.
    """

    down: bool = False
    failure_kind: str = "connection"  # or "timeout"
    text_factory: Callable[..., str] = lambda **kw: "stub response"
    calls: List[Dict[str, Any]] = field(default_factory=list)
    model_id: str = "fake-cortex/llama-stub"

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        call = {
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self.calls.append(call)

        if self.down:
            from brainstem_4070.cortex_client import CortexError

            if self.failure_kind == "timeout":
                raise CortexError(
                    "POST http://stubbed/v1/chat/completions failed: "
                    "HTTPSConnectionPool(...): Read timed out."
                )
            raise CortexError(
                "POST http://stubbed/v1/chat/completions failed: "
                "ConnectionRefusedError(111, 'Connection refused')"
            )

        text = self.text_factory(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return {
            "text": text,
            "model": self.model_id,
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": max(1, len(_tokenize(prompt))),
                "completion_tokens": max(1, len(_tokenize(text))),
            },
        }


@dataclass
class FakeMemory:
    """Behavioral stand-in for the embedder's memory_write + memory_query.

    Stores rows in a list. memory_query returns matches ranked by
    token-overlap with the query, optionally scoped by session_id_filter
    when the caller passes one. This is enough to assert that the
    brainstem retrieves prior turns across sessions when no filter is
    set, which is the Sprint 2 cross-session done-criterion.
    """

    rows: List[Dict[str, Any]] = field(default_factory=list)
    last_query: Optional[Dict[str, Any]] = None
    embedder_reachable: bool = True

    # -- embedder.health -------------------------------------------------
    def health(self) -> Dict[str, Any]:
        return {"reachable": self.embedder_reachable}

    # -- embedder.memory_write ------------------------------------------
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
        row_id = f"mem_{len(self.rows)}"
        self.rows.append(
            {
                "id": row_id,
                "session_id": session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "turn_idx": turn_idx,
                "ts": ts,
                "model_used": model_used,
            }
        )
        return {"ok": True, "chunks": 1, "id": row_id}

    # -- embedder.memory_query ------------------------------------------
    def memory_query(
        self,
        session_id: str,
        query: str,
        k: int = 5,
        session_id_filter: Optional[str] = None,
        exclude_parent_turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.last_query = {
            "session_id": session_id,
            "query": query,
            "k": k,
            "session_id_filter": session_id_filter,
        }

        q_tokens = set(_tokenize(query))
        scored: List[tuple[int, Dict[str, Any]]] = []
        for row in self.rows:
            if session_id_filter and row["session_id"] != session_id_filter:
                continue
            row_text = f"{row['user_text']} {row['assistant_text']}"
            overlap = len(q_tokens & set(_tokenize(row_text)))
            if overlap > 0:
                scored.append((overlap, row))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        matches: List[Dict[str, Any]] = []
        for overlap, row in scored[:k]:
            text = f"user: {row['user_text']}\nassistant: {row['assistant_text']}"
            matches.append(
                {
                    "id": row["id"],
                    "text": text,
                    "distance": 1.0 / (overlap + 1),
                    "metadata": {
                        "ts": row["ts"],
                        "session_id": row["session_id"],
                        "turn_idx": row["turn_idx"],
                    },
                }
            )
        return {"matches": matches}


# ---------------------------------------------------------------------------
# Brainstem fixture
# ---------------------------------------------------------------------------


@dataclass
class BrainstemHarness:
    """Bundle of everything an integration test needs to drive the
    brainstem and inspect what it actually did."""

    client: Any  # fastapi.testclient.TestClient
    cortex: FakeCortex
    memory: FakeMemory
    store: Any  # brainstem_4070.auth.TokenStore
    server: Any  # the brainstem_4070.server module
    metrics_path: Path

    def mint_token(self, name: str) -> str:
        token, _entry = self.store.create(name)
        return token

    def revoke(self, name: str) -> bool:
        return self.store.revoke(name)

    def post_generate(
        self,
        prompt: str,
        token: Optional[str],
        session_id: str = "sess_default",
        system: Optional[str] = None,
        max_tokens: int = 64,
        temperature: float = 0.7,
    ):
        headers: Dict[str, str] = {"X-Session-Id": session_id}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body: Dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        return self.client.post("/generate", headers=headers, json=body)


@pytest.fixture
def brainstem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[BrainstemHarness]:
    """Boot the brainstem against tmp paths and fake outbound clients."""
    store_path = tmp_path / "tokens.json"
    metrics_path = tmp_path / "brainstem_metrics.jsonl"

    monkeypatch.setenv("BRAINSTEM_TOKEN_STORE_PATH", str(store_path))
    monkeypatch.setenv("BRAINSTEM_METRICS_PATH", str(metrics_path))

    # Re-import the brainstem package so the new env vars take effect.
    for mod in list(sys.modules):
        if mod.startswith("brainstem_4070"):
            del sys.modules[mod]

    server = importlib.import_module("brainstem_4070.server")
    server.configure_store(store_path)

    cortex = FakeCortex()
    memory = FakeMemory()

    monkeypatch.setattr(server.cortex, "generate", cortex.generate)
    monkeypatch.setattr(server.embedder, "health", memory.health)
    monkeypatch.setattr(server.embedder, "memory_write", memory.memory_write)
    monkeypatch.setattr(server.embedder, "memory_query", memory.memory_query)

    from fastapi.testclient import TestClient
    from brainstem_4070.auth import TokenStore

    with TestClient(server.app) as client:
        store = TokenStore.load(store_path)
        yield BrainstemHarness(
            client=client,
            cortex=cortex,
            memory=memory,
            store=store,
            server=server,
            metrics_path=metrics_path,
        )
