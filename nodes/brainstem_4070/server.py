# nodes/brainstem_4070/server.py
from typing import List, Optional
import uuid
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.nas_client import NASClient
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

nas = NASClient(settings.nas_url)

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


@app.post("/embed")
def embed(req: EmbedRequest):
    #create embedding vectors
    vectors = embed_texts(req.texts)

    memory_ids = []

    #for each embedding, write a semantic memory to NAS
    for text, vector in zip(req.texts, vectors):

        # Write semantic memories to NAS
        mem_id = nas.write_semantic(
            text=text,
            embedding=vector,
            metadata={"source": "brainstem_4070"}
        )
        memory_ids.append(mem_id)

        # Log the event in episodic memory
        nas.log_event(
            event_type="semantic_memory_created",
            details={
                "memory_id": mem_id,
                "vector_dim": len(vector),
                "text_snippet": text[:50],
                "source": "brainstem_4070",
                "tags": [],  # Could add tag processing later
            }
        )

    return {
        "embeddings": vectors,
        "memory_ids": memory_ids,
        }



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
