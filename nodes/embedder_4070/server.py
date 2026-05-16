# nodes/embedder_4070/server.py
"""
Embedder + memory service.

This service owns:
  - the embedding model (BGE-small, locked Sprint 2 Chunk A)
  - the recursive markdown-aware chunker
  - the Chroma persistent `memory` collection

Brainstem talks to this service over the compose network. The thin
client sends `X-Session-Id` to the brainstem, the brainstem forwards
it to this service on writes and queries, and we stash it in chunk
metadata + use it as an optional filter on query.

API:
  GET  /health
  POST /embed         -- raw embedding for legacy callers (proxy target)
  POST /memory/write  -- write a completed turn (chunks if needed)
  POST /memory/query  -- top-k retrieval (no default session filter)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from . import chroma_store
from .chunker import chunk_turn
from .embed import dim, embed_texts, get_model, tokenize

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("embedder_4070")

app = FastAPI(
    title="Nexus Embedder (4070)",
    description=(
        "Embedding model, chunker, and Chroma memory store. Separate "
        "container from the brainstem for clean lifecycle and a "
        "swappable model boundary."
    ),
    version="0.1.0",
)


# ----- request / response models -----------------------------------

class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    model: str
    dim: int


class MemoryWriteRequest(BaseModel):
    user_text: str
    assistant_text: str
    turn_idx: int
    ts: str
    model_used: str = ""
    user_token_count: int = 0
    assistant_token_count: int = 0
    source_service: str = ""
    tool_calls_present: bool = False


class MemoryWriteResponse(BaseModel):
    ids: List[str]
    chunks: int
    parent_turn_id: str


class MemoryQueryRequest(BaseModel):
    query: str
    k: int = 5
    # Optional metadata filters. By default we do NOT scope to the
    # caller's session, because the Sprint 2 done-criterion is
    # cross-session recall. Filtering is opt-in.
    session_id_filter: Optional[str] = None
    exclude_parent_turn_id: Optional[str] = None


class MemoryMatch(BaseModel):
    id: str
    text: str
    metadata: Dict[str, Any]
    distance: Optional[float]


class MemoryQueryResponse(BaseModel):
    matches: List[MemoryMatch]


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    chroma_count: int
    model: str
    dim: int


# ----- helpers ------------------------------------------------------

def _concatenate_turn(user_text: str, assistant_text: str) -> str:
    """Single canonical format for a turn-as-document. Markdown headings
    are natural breaks for the recursive chunker AND read cleanly as
    natural language to BGE."""
    return f"### User\n{user_text.strip()}\n\n### Assistant\n{assistant_text.strip()}"


def _resolve_session_id(header_value: Optional[str]) -> str:
    """X-Session-Id is required for memory ops. Fail loud rather than
    silently writing to a 'unknown' bucket."""
    if not header_value or not header_value.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required")
    return header_value.strip()


# ----- endpoints ---------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    # touch the model lazily; if it has not loaded yet, report so.
    try:
        m = get_model()
        loaded = True
    except Exception:  # pragma: no cover - reported via field
        loaded = False
    return HealthResponse(
        status="ok",
        model_loaded=loaded,
        chroma_count=chroma_store.count() if loaded else 0,
        model=settings.model_name,
        dim=dim() if loaded else 0,
    )


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    vectors = embed_texts(req.texts)
    return EmbedResponse(embeddings=vectors, model=settings.model_name, dim=dim())


@app.post("/memory/write", response_model=MemoryWriteResponse)
def memory_write(
    req: MemoryWriteRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
) -> MemoryWriteResponse:
    session_id = _resolve_session_id(x_session_id)
    parent_turn_id = f"{session_id}:{req.turn_idx}"

    body = _concatenate_turn(req.user_text, req.assistant_text)

    chunks = chunk_turn(
        body,
        tokenize=tokenize,
        threshold=settings.chunk_threshold_tokens,
        target=settings.chunk_target_tokens,
        overlap=settings.chunk_overlap_tokens,
    )
    if not chunks:
        # belt and suspenders: should never happen for non-empty input
        raise HTTPException(status_code=400, detail="empty document after chunking")

    embeddings = embed_texts(chunks)

    ids: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    total = len(chunks)
    for idx, _chunk in enumerate(chunks):
        chunk_id = f"{parent_turn_id}:{idx}"
        ids.append(chunk_id)
        metadatas.append({
            "session_id": session_id,
            "turn_idx": req.turn_idx,
            "ts": req.ts,
            "model_used": req.model_used,
            "user_token_count": req.user_token_count,
            "assistant_token_count": req.assistant_token_count,
            "source_service": req.source_service,
            "tool_calls_present": req.tool_calls_present,
            "chunk_idx": idx,
            "chunk_total": total,
            "parent_turn_id": parent_turn_id,
        })

    chroma_store.add_documents(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    logger.info(
        "memory_write session=%s turn=%d chunks=%d",
        session_id, req.turn_idx, total,
    )
    return MemoryWriteResponse(ids=ids, chunks=total, parent_turn_id=parent_turn_id)


@app.post("/memory/query", response_model=MemoryQueryResponse)
def memory_query(
    req: MemoryQueryRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
) -> MemoryQueryResponse:
    # session id is read but not required for reads; we log it for
    # traceability. Cross-session retrieval is the whole point of
    # Sprint 2's done-criterion.
    _ = x_session_id

    query_vec = embed_texts([req.query])[0]

    where: Optional[Dict[str, Any]] = None
    if req.session_id_filter:
        where = {"session_id": req.session_id_filter}
    # exclude_parent_turn_id is rarely used (we usually do not want to
    # echo back the in-progress turn). Chroma supports $ne via where.
    if req.exclude_parent_turn_id:
        where = {**(where or {}), "parent_turn_id": {"$ne": req.exclude_parent_turn_id}}

    raw = chroma_store.query(query_vec, k=req.k, where=where)
    return MemoryQueryResponse(
        matches=[MemoryMatch(**m) for m in raw]
    )


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "Nexus Embedder (4070)",
        "model": settings.model_name,
        "chroma_collection": settings.chroma_collection,
        "endpoints": ["/health", "/embed", "/memory/write", "/memory/query"],
    }
