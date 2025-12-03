import requests
from typing import List, Dict, Any


class NASClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def write_semantic(
        self,
        text: str,
        embedding: List[float],
        metadata: Dict[str, Any] = None,
    ) -> str:
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
