# nodes/brainstem_4070/server.py
from typing import List, Optional
import uuid
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from brainstem_4070.config import settings
from brainstem_4070.embed import embed_texts
from brainstem_4070.stm_buffer import STMItem, stm_buffer
from brainstem_4070.filter import basic_validation

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("brainstem_4070")

app = FastAPI(
    title="Nexus Brainstem (4070)",
    description="Embedding + filtering + STM buffer for ProjectNexus.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    stm_size: int


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]


class STMWriteRequest(BaseModel):
    text: str
    metadata: Optional[dict] = None


class STMWriteResponse(BaseModel):
    id: str
    stored: bool


@app.get("/health", response_model=HealthResponse)
def health_check():
    # lazy check: if model ever got loaded, fine.
    from .embed import _model  # type: ignore

    return HealthResponse(
        status="ok",
        model_loaded=_model is not None,
        stm_size=len(stm_buffer),
    )


@app.post("/embed", response_model=EmbedResponse)
def embed_endpoint(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="No texts provided")
    embeddings = embed_texts(req.texts)
    return EmbedResponse(embeddings=embeddings)


@app.post("/stm/write", response_model=STMWriteResponse)
def stm_write(req: STMWriteRequest):
    payload = {"text": req.text, "metadata": req.metadata or {}}

    if not basic_validation(payload):
        raise HTTPException(status_code=400, detail="Validation failed")

    emb = embed_texts([req.text])[0]
    item_id = str(uuid.uuid4())

    stm_buffer.add(
        STMItem(
            id=item_id,
            text=req.text,
            embedding=emb,
            metadata=req.metadata or {},
        )
    )

    logger.info("STM stored item %s", item_id)

    return STMWriteResponse(id=item_id, stored=True)
