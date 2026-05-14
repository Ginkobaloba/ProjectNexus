# nodes/brainstem_4070/server.py
from typing import List, Optional
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import uuid
import logging

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.nas_client import NASClient
from brainstem_4070.config import settings
from brainstem_4070.embed import embed_texts
from brainstem_4070.stm_buffer import STMItem, stm_buffer
from brainstem_4070.filter import basic_validation
from brainstem_4070.cortex_client import CortexClient, CortexError
from bench.probes import JsonlSink, MetricRecord, now_ns
from bench.stats import summarize

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("brainstem_4070")

app = FastAPI(
    title="Nexus Brainstem (4070)",
    description="Embedding, filtering, STM buffer, Cortex relay, and the Phase 0 metric harness.",
    version="0.3.0",
)

nas = NASClient(settings.nas_url)
cortex = CortexClient(
    settings.cortex_url,
    timeout=settings.cortex_timeout,
    health_timeout=settings.cortex_health_timeout,
)

# Phase 0 metric harness. The JSONL file is the persistent data layer;
# the in-process ring buffer is what the live dashboard reads each poll.
metrics_sink = JsonlSink(settings.metrics_path)
recent_roundtrips: deque = deque(maxlen=settings.metrics_window)

# Static node identity for the fabric status view.
NODE_4070 = {
    "id": "brainstem_4070",
    "name": "BROOKFIELD_PC (RTX 4070)",
    "role": "orchestrator / brainstem",
}
NODE_4090 = {
    "id": "cortex_4090",
    "name": "DREWSPC (RTX 4090)",
    "role": "heavy inference / cortex",
}
DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"

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


class GenerateRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    max_tokens: int = 512
    temperature: float = 0.7


class GenerateResponse(BaseModel):
    text: str
    model: str
    finish_reason: Optional[str] = None
    usage: dict
    source: str = "cortex_4090"


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


@app.get("/cortex/health")
def cortex_health():
    """Reachability check for the 4090 Cortex inference peer."""
    status = cortex.health()
    status["cortex_url"] = settings.cortex_url
    return status


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    """Relay a prompt to the 4090 Cortex and return its generated text.

    This is the 4070 -> 4090 leg of the fabric: brainstem accepts the
    request locally and the heavy reasoning happens on the 4090. The
    Phase 0 metric harness times every call and decomposes the latency
    into brainstem overhead and the Cortex round trip (LAN hop + 4090
    compute), so raw model generation time does not hide the link cost.
    """
    t_ingress = now_ns()
    payload_bytes = len((req.prompt or "").encode("utf-8"))
    if req.system:
        payload_bytes += len(req.system.encode("utf-8"))

    t_pre = now_ns()
    try:
        result = cortex.generate(
            prompt=req.prompt,
            system=req.system,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        t_post = now_ns()
        ok, err = True, None
    except CortexError as exc:
        t_post = now_ns()
        ok, err, result = False, str(exc), None

    t_egress = now_ns()
    cortex_roundtrip_ms = (t_post - t_pre) / 1e6
    total_ms = (t_egress - t_ingress) / 1e6
    brainstem_overhead_ms = total_ms - cortex_roundtrip_ms

    usage = (result or {}).get("usage", {}) or {}
    completion_tokens = usage.get("completion_tokens", 0) or 0
    tokens_per_s = (
        completion_tokens / (cortex_roundtrip_ms / 1000.0)
        if ok and cortex_roundtrip_ms > 0 and completion_tokens
        else 0.0
    )

    record = MetricRecord(
        probe_id="brainstem.generate",
        stage="generate",
        ingress_ns=t_ingress,
        egress_ns=t_egress,
        payload_bytes=payload_bytes,
        ok=ok,
        extra={
            "pre_cortex_ns": t_pre,
            "post_cortex_ns": t_post,
            "total_ms": round(total_ms, 3),
            "cortex_roundtrip_ms": round(cortex_roundtrip_ms, 3),
            "brainstem_overhead_ms": round(brainstem_overhead_ms, 3),
            "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
            "completion_tokens": completion_tokens,
            "tokens_per_s": round(tokens_per_s, 2),
            "cortex_model": (result or {}).get("model"),
            "finish_reason": (result or {}).get("finish_reason"),
            "error": err,
        },
    )
    try:
        metrics_sink.write(record)
    except Exception:  # never let metric I/O break a request
        logger.warning("metric sink write failed", exc_info=True)
    recent_roundtrips.append(record.to_dict())

    if not ok:
        logger.error("Cortex relay failed: %s", err)
        raise HTTPException(status_code=502, detail=f"Cortex unreachable: {err}")

    logger.info(
        "Cortex relay ok: model=%s total=%.1fms cortex=%.1fms overhead=%.1fms tok/s=%.1f",
        result["model"], total_ms, cortex_roundtrip_ms, brainstem_overhead_ms, tokens_per_s,
    )
    return GenerateResponse(
        text=result["text"],
        model=result["model"],
        finish_reason=result.get("finish_reason"),
        usage=usage,
    )


# --------------------------------------------------------------------------
# Phase 0 metric harness: fabric status + dashboard
# --------------------------------------------------------------------------

def _check_cortex() -> dict:
    """Live reachability and served-model check for the 4090 Cortex peer."""
    t0 = now_ns()
    health = cortex.health()
    rtt_ms = (now_ns() - t0) / 1e6
    models = health.get("models") or []
    return {
        "status": "up" if health.get("reachable") else "down",
        "url": settings.cortex_url,
        "model": models[0] if models else None,
        "probe_rtt_ms": round(rtt_ms, 2),
        "detail": health.get("error"),
    }


def _check_nas() -> dict:
    """Live reachability check for the NAS memory service."""
    url = settings.nas_url.rstrip("/")
    t0 = now_ns()
    try:
        res = requests.get(f"{url}/health", timeout=4)
        res.raise_for_status()
        return {
            "status": "up",
            "url": url,
            "probe_rtt_ms": round((now_ns() - t0) / 1e6, 2),
            "detail": res.json(),
        }
    except requests.RequestException as exc:
        return {
            "status": "down",
            "url": url,
            "probe_rtt_ms": round((now_ns() - t0) / 1e6, 2),
            "detail": str(exc),
        }


def _metrics_summary() -> dict:
    """Aggregate the recent-roundtrip ring buffer into the numbers the
    dashboard plots. Only successful calls feed the latency stats."""
    rows = list(recent_roundtrips)
    ok_rows = [r for r in rows if r.get("ok")]
    return {
        "window": settings.metrics_window,
        "count": len(rows),
        "ok_count": len(ok_rows),
        "fail_count": len(rows) - len(ok_rows),
        "metrics_path": settings.metrics_path,
        "total_ms": summarize([r["total_ms"] for r in ok_rows if "total_ms" in r]),
        "cortex_roundtrip_ms": summarize(
            [r["cortex_roundtrip_ms"] for r in ok_rows if "cortex_roundtrip_ms" in r]
        ),
        "brainstem_overhead_ms": summarize(
            [r["brainstem_overhead_ms"] for r in ok_rows if "brainstem_overhead_ms" in r]
        ),
        "tokens_per_s": summarize(
            [r["tokens_per_s"] for r in ok_rows if r.get("tokens_per_s")]
        ),
    }


@app.get("/fabric/status")
def fabric_status():
    """Live fabric snapshot for the dashboard: both nodes, the 4070->4090
    link, the NAS memory service, and the rolling latency metrics.
    Recomputed on every poll."""
    cortex_status = _check_cortex()
    nas_status = _check_nas()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "nodes": {
            "brainstem_4070": {**NODE_4070, "status": "up"},
            "cortex_4090": {**NODE_4090, **cortex_status},
        },
        "link": {
            "from": "brainstem_4070",
            "to": "cortex_4090",
            "target": settings.cortex_url,
            "healthy": cortex_status["status"] == "up",
        },
        "nas": {**nas_status, "url_configured": settings.nas_url},
        "metrics": _metrics_summary(),
        "recent_roundtrips": list(recent_roundtrips)[-25:][::-1],  # newest first
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Self-refreshing fabric dashboard. Polls /fabric/status client-side."""
    try:
        return HTMLResponse(DASHBOARD_HTML.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="dashboard.html not found")


@app.get("/")
def root():
    """Pointer to the human-facing dashboard and the machine endpoints."""
    return {
        "service": "Nexus Brainstem (4070)",
        "dashboard": "/dashboard",
        "endpoints": ["/health", "/cortex/health", "/fabric/status", "/generate", "/embed", "/stm/write"],
    }
