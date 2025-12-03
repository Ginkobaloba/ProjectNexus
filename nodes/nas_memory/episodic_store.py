# nodes/nas-memory/episodic_store.py
import json
import time
import uuid
from typing import Dict, List

from .config import settings


def _ensure_file():
    if not settings.episodic_log_file.exists():
        settings.episodic_log_file.write_text("", encoding="utf-8")


def write_event(event_type: str, payload: Dict) -> str:
    _ensure_file()
    event_id = str(uuid.uuid4())
    record = {
        "id": event_id,
        "event_type": event_type,
        "payload": payload,
        "timestamp": time.time(),
    }
    with settings.episodic_log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return event_id


def list_events(limit: int = 100) -> List[Dict]:
    _ensure_file()
    events: List[Dict] = []
    with settings.episodic_log_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return events[-limit:]
