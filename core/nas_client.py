import requests
from typing import List, Dict, Any
from core.session import current_session_id
from brainstem_4070.config import settings
from core.time_utils import now_iso, now_timestamp

class NASClient:
    #A simple REST client that allows any node (brainstem, cortex, agents)
    #to write semantic and episodic memories to the NAS memory service.
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def write_semantic(
        self,
        text: str,
        embedding: List[float],
        metadata: Dict[str, Any] = None,
    ) -> str:
    #Stores a semantic memory item:
    #    text: the natural language representation
    #    embedding: vector from brainstem
    #    metadata: tags, source info, timestamps, etc

        payload = {
            "items": [
                {
                    "text": text,
                    "embedding": embedding,
                    "metadata": metadata or {}
                }
            ]
        }
        url = f"{self.base_url}/semantic/write"
        res = requests.post(url, json=payload)
        res.raise_for_status()
        return res.json()["ids"][0]

    def write_episodic(self, event_type: str, payload: Dict[str, Any]):
        url = f"{self.base_url}/episodic/write"
        res = requests.post(url, json={
            "event_type": event_type,
            "payload": payload
        })
        res.raise_for_status()
        return res.json()["id"]

    def log_event(self, event_type: str, details: Dict[str, Any]):
        ##self documentating method to log an episodic event with type and details
        ##Will play a bigger role when cosolidation engine is implemented

        enriched = {
            "node_id": settings.node_id,
            "session": current_session_id(),
            "timestamp_unix": now_timestamp(),
            "timestamp_iso": now_iso(),
            "event_type": event_type,
            "details": details
        }

        return self.write_episodic(event_type,enriched)
