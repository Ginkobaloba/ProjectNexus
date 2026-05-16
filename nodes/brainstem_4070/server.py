# nodes/brainstem_4070/server.py
from typing import Any, Dict, List, Optional
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
import logging
import uuid

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.nas_client import NASClient
from brainstem_4070.config import settings
from brainstem_4070.embedder_client import EmbedderClient, EmbedderError
from brainstem_4070.stm_buffer import STMItem, stm_buffer
from brainstem_4070.filter import basic_validation
from brainstem_4070.cortex_client import CortexClient, CortexError
from bench.probes import JsonlSink, MetricRecord, now_ns
from bench.stats import summarize

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("brainstem_4070")

app = FastAPI(
    title="Nexus Brainstem (4070)",
    description=(
        "Cortex relay, STM buffer, Phase 0 metric harness, and the "
        "write-on-turn / retrieve-before-generate path against the "
        "embedder service."
    ),
    version="0.4.0",
)

nas = NASClient(settings.nas_url)
cortex = CortexClient(
    settings.cortex_url,
    timeout=settings.cortex_timeout,
    health_timeout=settings.cortex_health_timeout,
)
embedder = EmbedderClient(settings.embedder_url, timeout=settings.embedder_timeout)

# Phase 0 metric harness. The JSONL file is the persistent data layer;
# the in-process ring buffer is what the live dashboard reads each poll.
metrics_sink = JsonlSink(settings.metrics_path)
recent_roundtrips: deque = deque(maxlen=settings.metrics_window)

# Per-session monotonic turn index. Phase 0 single-process, in-memory is
# fine: turn ordering is per-session and a service restart starts a new
# logical conversation anyway (the thin client persists session id
# across restarts, so turn_idx after a restart resumes from 0 which is
# acceptable for now and surfaced in the doc).
_turn_idx_by_session: Dict[str, int] = defaultdict(int)

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
    embedder_reachable: bool
    stm_size: int


class EmbedRequest(BaseModel):
    texts: List[str]


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
    session_id: Optional[str] = None
    turn_idx: Optional[int] = None
    memory_written: bool = False


@app.get("/health", response_model=HealthResponse)
def health_check():
    embedder_status = embedder.health()
    return HealthResponse(
        status="ok",
        embedder_reachable=bool(embedder_status.get("reachable")),
        stm_size=len(stm_buffer),
    )


@app.post("/embed")
def embed(req: EmbedRequest):
    """Legacy embedding endpoint. Now a thin proxy through the embedder
    service. Also writes a semantic memory to NAS for each input text to
    preserve the prior side effect for the NAS-based long-term memory
    path. The new Chroma path is reached via /generate or /memory/* on
    the embedder service directly."""
    try:
        res = embedder.embed(req.texts)
    except EmbedderError as exc:
        raise HTTPException(status_code=502, detail=f"embedder unreachable: {exc}")

    vectors = res.get("embeddings", [])
    memory_ids: List[str] = []
    for text, vector in zip(req.texts, vectors):
        mem_id = nas.write_semantic(
            text=text,
            embedding=vector,
            metadata={"source": "brainstem_4070"},
        )
        memory_ids.append(mem_id)
        nas.log_event(
            event_type="semantic_memory_created",
            details={
                "memory_id": mem_id,
                "vector_dim": len(vector),
                "text_snippet": text[:50],
                "source": "brainstem_4070",
                "tags": [],
            },
        )

    return {"embeddings": vectors, "memory_ids": memory_ids, "model": res.get("model")}


@app.post("/stm/write", response_model=STMWriteResponse)
def stm_write(req: STMWriteRequest):
    payload = {"text": req.text, "metadata": req.metadata or {}}

    if not basic_validation(payload):
        raise HTTPException(status_code=400, detail="Validation failed")

    try:
        res = embedder.embed([req.text])
    except EmbedderError as exc:
        raise HTTPException(status_code=502, detail=f"embedder unreachable: {exc}")
    emb = res["embeddings"][0]
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


@app.get("/embedder/health")
def embedder_health():
    """Reachability check for the embedder service."""
    status = embedder.health()
    status["embedder_url"] = settings.embedder_url
    return status


def _resolve_session_id(header_value: Optional[str]) -> str:
    """Sprint 2 contract: X-Session-Id is required on /generate so we
    can attribute write-on-turn correctly. Fail loud rather than write
    to a default bucket."""
    if not header_value or not header_value.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required")
    return header_value.strip()


@app.post("/generate", response_model=GenerateResponse)
def generate(
    req: GenerateRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
):
    """Relay a prompt to the 4090 Cortex, write the completed turn to
    the embedder's `memory` collection synchronously, return the
    generated text.

    Sprint 2 changes from the previous version:
      - X-Session-Id is read off the request and required.
      - Each completed turn is embedded + chunked + written to Chroma
        before returning. Synchronous on purpose so we surface real
        write-on-turn latency in the metric harness.
    """
    session_id = _resolve_session_id(x_session_id)

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

    # --- Sprint 2 write-on-turn -----------------------------------
    memory_written = False
    memory_chunks = 0
    embed_latency_ms = 0.0
    turn_idx = _turn_idx_by_session[session_id]
    if ok:
        t_embed_start = now_ns()
        usage = (result or {}).get("usage", {}) or {}
        try:
            embedder.memory_write(
                session_id=session_id,
                user_text=req.prompt,
                assistant_text=(result or {}).get("text", ""),
                turn_idx=turn_idx,
                ts=datetime.now(timezone.utc).isoformat(),
                model_used=(result or {}).get("model", ""),
                user_token_count=usage.get("prompt_tokens", 0) or 0,
                assistant_token_count=usage.get("completion_tokens", 0) or 0,
                source_service="brainstem_4070",
                tool_calls_present=False,
            )
            memory_written = True
            _turn_idx_by_session[session_id] = turn_idx + 1
        except EmbedderError as exc:
            logger.warning("memory_write failed (continuing): %s", exc)
        embed_latency_ms = (now_ns() - t_embed_start) / 1e6

    t_egress = now_ns()
    cortex_roundtrip_ms = (t_post - t_pre) / 1e6
    total_ms = (t_egress - t_ingress) / 1e6
    brainstem_overhead_ms = total_ms - cortex_roundtrip_ms - embed_latency_ms

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
            "embed_latency_ms": round(embed_latency_ms, 3),
            "retrieve_latency_ms": 0.0,  # populated in Chunk B
            "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
            "completion_tokens": completion_tokens,
            "tokens_per_s": round(tokens_per_s, 2),
            "cortex_model": (result or {}).get("model"),
            "finish_reason": (result or {}).get("finish_reason"),
            "session_id": session_id,
            "turn_idx": turn_idx if memory_written else None,
            "memory_written": memory_written,
            "memory_chunks": memory_chunks,
            "error": err,
        },
    )
    try:
        metrics_sink.write(record)
    except Exception:
        logger.warning("metric sink write failed", exc_info=True)
    recent_roundtrips.append(record.to_dict())

    if not ok:
        logger.error("Cortex relay failed: %s", err)
        raise HTTPException(status_code=502, detail=f"Cortex unreachable: {err}")

    logger.info(
        "generate ok: session=%s turn=%d total=%.1fms cortex=%.1fms embed=%.1fms",
        session_id, turn_idx, total_ms, cortex_roundtrip_ms, embed_latency_ms,
    )
    return GenerateResponse(
        text=result["text"],
        model=result["model"],
        finish_reason=result.get("finish_reason"),
        usage=usage,
        session_id=session_id,
        turn_idx=turn_idx if memory_written else None,
        memory_written=memory_written,
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


def _check_embedder() -> dict:
    """Live reachability for the embedder service."""
    url = settings.embedder_url.rstrip("/")
    t0 = now_ns()
    health = embedder.health()
    return {
        "status": "up" if health.get("reachable") else "down",
        "url": url,
        "probe_rtt_ms": round((now_ns() - t0) / 1e6, 2),
        "detail": health,
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
        "embed_latency_ms": summarize(
            [r["embed_latency_ms"] for r in ok_rows if "embed_latency_ms" in r]
        ),
        "retrieve_latency_ms": summarize(
            [r["retrieve_latency_ms"] for r in ok_rows if "retrieve_latency_ms" in r]
        ),
        "tokens_per_s": summarize(
            [r["tokens_per_s"] for r in ok_rows if r.get("tokens_per_s")]
        ),
    }


@app.get("/fabric/status")
def fabric_status():
    """Live fabric snapshot for the dashboard."""
    cortex_status = _check_cortex()
    nas_status = _check_nas()
    embedder_status = _check_embedder()
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
        "embedder": {**embedder_status, "url_configured": settings.embedder_url},
        "metrics": _metrics_summary(),
        "recent_roundtrips": list(recent_roundtrips)[-25:][::-1],
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
        "endpoints": [
            "/health",
            "/cortex/health",
            "/embedder/health",
            "/fabric/status",
            "/generate",
            "/embed",
            "/stm/write",
        ],
    }
