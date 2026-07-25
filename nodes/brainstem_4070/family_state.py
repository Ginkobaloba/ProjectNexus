# nodes/brainstem_4070/family_state.py
"""
Per-member presence + inbox v0 (Sprint 5, Card 2).

Presence is owned by the model manager (Card 4); until it exists, the
hub keeps this in-memory store and exposes an authenticated endpoint
for the manager — or an operator — to set it. The inbox here is the
in-memory v0 behind the 202-queued contract; Card 5 makes it durable
and drains it on wake. Queued messages are custody, not memory: nothing
touches any memory scope until the member actually processes the turn.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.family import PRESENCE_STATES


class UnknownMemberError(KeyError):
    pass


class FamilyState:
    """Thread-safe presence + queue state for every registry member."""

    def __init__(self, member_ids: List[str], default_presence: str = "awake"):
        if default_presence not in PRESENCE_STATES:
            raise ValueError(f"invalid default presence {default_presence!r}")
        self._lock = threading.Lock()
        self._presence: Dict[str, str] = {m: default_presence for m in member_ids}
        # msg_id -> record, insertion-ordered per member (dicts preserve
        # insertion order, which is the drain order Card 5 needs).
        self._inbox: Dict[str, Dict[str, dict]] = {m: {} for m in member_ids}

    def _check(self, member_id: str) -> None:
        if member_id not in self._presence:
            raise UnknownMemberError(member_id)

    # -- presence ----------------------------------------------------------

    def presence(self, member_id: str) -> str:
        self._check(member_id)
        return self._presence[member_id]

    def set_presence(self, member_id: str, state: str) -> None:
        self._check(member_id)
        if state not in PRESENCE_STATES:
            raise ValueError(
                f"invalid presence {state!r}; expected one of {PRESENCE_STATES}"
            )
        with self._lock:
            self._presence[member_id] = state

    # -- inbox v0 ----------------------------------------------------------

    def enqueue(
        self,
        member_id: str,
        *,
        prompt: str,
        system: Optional[str],
        person: str,
        max_tokens: int,
        temperature: Optional[float],
    ) -> str:
        """Queue a message for a member that can't take it live.
        Returns the msg_id the sender polls on."""
        self._check(member_id)
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._inbox[member_id][msg_id] = {
                "msg_id": msg_id,
                "member_id": member_id,
                "person": person,
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "status": "queued",
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "result": None,
            }
        return msg_id

    def queue_depth(self, member_id: str) -> int:
        self._check(member_id)
        with self._lock:
            return sum(
                1 for m in self._inbox[member_id].values()
                if m["status"] == "queued"
            )

    def get_message(self, member_id: str, msg_id: str) -> Optional[dict]:
        self._check(member_id)
        with self._lock:
            record = self._inbox[member_id].get(msg_id)
            return dict(record) if record else None
