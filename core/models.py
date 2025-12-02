from pydantic import BaseModel
from typing import Literal, Optional, Dict, Any
from datetime import datetime


class Heartbeat(BaseModel):
    agent_id: str
    role: str = "generic"
    host: str
    timestamp: datetime
    status: Literal["online", "offline", "degraded"] = "online"
    meta: Dict[str, Any] = {}


class AgentCommand(BaseModel):
    target_agent_id: str
    command: str
    params: Dict[str, Any] = {}
    issued_at: datetime
