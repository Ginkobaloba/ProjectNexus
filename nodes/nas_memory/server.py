# nodes/nas-memory/server.py
import logging
from typing import List

from fastapi import FastAPI, HTTPException

from .config import settings
from . import semantic_store, episodic_store
from .schemas import (
    HealthResponse,
    SemanticWriteRequest,
    SemanticWriteResult,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchHit,
    EpisodicWriteRequest,
    EpisodicListResponse,
    EpisodicEvent,
)

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("nas-memory")


app = FastAPI(
    title="Nexus NAS Memory Node",
    description="Semantic + episodic memory service for ProjectNexus.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
def health_check():
    # Very basic health signals
    semantic_ok = True
    episodic_ok = settings.episodic_log_file is not None
    return HealthResponse(
        status="ok",
        semantic_ok=semantic_ok,
        episodic_ok=episodic_ok,
    )


@app.post("/semantic/write", response_model=SemanticWriteResult)
def semantic_write(req: SemanticWriteRequest):
    if not req.items:
        raise HTTPException(status_code=400, detail="No items provided")

    prepared = []
    for item in req.items:
        if not item.embedding:
            raise HTTPException(
                status_code=400, detail="Item missing embedding"
            )
        _id = item.id or f"mem-{len(item.embedding)}-{hash(item.text)}"
        prepared.append((_id, item.text, item.embedding, item.metadata))

    ids = semantic_store.write_items(prepared)
    logger.info("Stored %d semantic items", len(ids))
    return SemanticWriteResult(ids=ids)


@app.post("/semantic/search", response_model=SemanticSearchResponse)
def semantic_search(req: SemanticSearchRequest):
    if not req.query_embedding:
        raise HTTPException(status_code=400, detail="Missing query_embedding")

    ids, docs, scores, metas = semantic_store.search(
        req.query_embedding, req.top_k
    )

    hits: List[SemanticSearchHit] = []
    for i, d, s, m in zip(ids, docs, scores, metas):
        hits.append(
            SemanticSearchHit(
                id=i,
                text=d,
                score=s,
                metadata=m or {},
            )
        )

    return SemanticSearchResponse(hits=hits)


@app.post("/episodic/write")
def episodic_write(req: EpisodicWriteRequest):
    event_id = episodic_store.write_event(req.event_type, req.payload)
    logger.info("Wrote episodic event %s", event_id)
    return {"id": event_id, "stored": True}


@app.get("/episodic/list", response_model=EpisodicListResponse)
def episodic_list(limit: int = 100):
    events_raw = episodic_store.list_events(limit)
    events = [
        EpisodicEvent(
            id=e["id"],
            event_type=e["event_type"],
            payload=e["payload"],
            timestamp=e["timestamp"],
        )
        for e in events_raw
    ]
    return EpisodicListResponse(events=events)
