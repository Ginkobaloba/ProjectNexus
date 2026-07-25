# nodes/model_manager_4090/server.py
"""
Model manager service (Sprint 5, Card 4). Runs on the 4090 host and
owns which member is loaded. V1 swap is manual — hit /members/{id}/load
— because there's nobody to swap to yet, but the presence states and
the hub's member_loading contract are real from day one.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException

from bench.probes import JsonlSink
from core.family import load_registry

from .config import settings
from .manager import HubPresenceClient, ModelManager, weights_filename
from .tiering import TierPaths, find_weights

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("model_manager_4090")

app = FastAPI(
    title="Nexus Model Manager (4090)",
    description="Weights tiering + llama.cpp lifecycle + presence reporting.",
    version="0.1.0",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_registry_path = Path(settings.family_registry_path)
if not _registry_path.is_absolute():
    _registry_path = REPO_ROOT / _registry_path
registry = load_registry(_registry_path, _registry_path.parent.parent)

manager = ModelManager(
    tiers=TierPaths(
        hot=Path(settings.hot_dir),
        warm=Path(settings.warm_dir),
        cold=Path(settings.cold_dir),
    ),
    hub=HubPresenceClient(settings.hub_url, settings.hub_token),
    llama_server_bin=settings.llama_server_bin,
    llama_host=settings.llama_host,
    llama_port=settings.llama_port,
    load_timeout_seconds=settings.load_timeout_seconds,
    health_poll_interval_seconds=settings.health_poll_interval_seconds,
    metrics_sink=JsonlSink(settings.metrics_path),
)


def _member_or_404(member_id: str):
    try:
        return registry.get(member_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown member '{member_id}'")


@app.get("/health")
def health():
    return {"status": "ok", "loaded": manager.status()}


@app.get("/status")
def status():
    tiers = manager.tiers
    weights = {}
    for m in registry.members:
        located = find_weights(weights_filename(m), tiers)
        weights[m.id] = {
            "filename": weights_filename(m),
            "tier": located[0] if located else None,
        }
    return {"loaded": manager.status(), "weights": weights}


@app.post("/members/{member_id}/load")
def load_member(member_id: str):
    member = _member_or_404(member_id)
    try:
        entry = manager.load(member)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (RuntimeError, TimeoutError, IOError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"member_id": member_id, "port": entry.port, "weights": str(entry.weights_path)}


@app.post("/members/{member_id}/unload")
def unload_member(member_id: str):
    _member_or_404(member_id)
    stopped = manager.unload(member_id)
    return {"member_id": member_id, "stopped": stopped}
