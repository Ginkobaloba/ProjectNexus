from datetime import datetime, timedelta
from typing import Dict, Any
from .logging_config import get_logger

logger = get_logger("nexus.core.registry")


class AgentRegistry:
    """In-memory registry of active agents.
    Replaceable with Redis/DB in the future.
    """

    def __init__(self, expiry_seconds: int = 90):
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._expiry = timedelta(seconds=expiry_seconds)

    def update_heartbeat(self, agent_id: str, payload: dict) -> None:
        now = datetime.utcnow()
        self._agents[agent_id] = {
            "last_seen": now,
            "payload": payload,
        }
        logger.debug(f"Updated heartbeat for {agent_id}")

    def get_active_agents(self) -> Dict[str, Dict[str, Any]]:
        now = datetime.utcnow()
        active = {}

        for agent_id, info in list(self._agents.items()):
            last_seen = info["last_seen"]
            if now - last_seen <= self._expiry:
                active[agent_id] = info
            else:
                logger.info(f"Agent {agent_id} expired from registry")
                self._agents.pop(agent_id, None)

        return active
