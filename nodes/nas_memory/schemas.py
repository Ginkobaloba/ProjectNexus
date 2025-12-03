# nodes/nas-memory/schemas.py
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    semantic_ok: bool
    episodic_ok: bool


# ---------- Semantic Memory ----------

class SemanticWriteItem(BaseModel):
    id: Optional[str] = None
    text: str
    embedding: List[float]
    metadata: Dict[str, Any] = {}


class SemanticWriteRequest(BaseModel):
    items: List[SemanticWriteItem]


class SemanticWriteResult(BaseModel):
    ids: List[str]


class SemanticSearchRequest(BaseModel):
    query_embedding: List[float]
    top_k: int = 5


class SemanticSearchHit(BaseModel):
    id: str
    text: str
    score: float
    metadata: Dict[str, Any]


class SemanticSearchResponse(BaseModel):
    hits: List[SemanticSearchHit]


# ---------- Episodic Memory ----------

class EpisodicWriteRequest(BaseModel):
    event_type: str
    payload: Dict[str, Any]


class EpisodicEvent(BaseModel):
    id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float


class EpisodicListResponse(BaseModel):
    events: List[EpisodicEvent]
