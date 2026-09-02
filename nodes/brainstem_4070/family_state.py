# nodes/brainstem_4070/family_state.py
"""
Per-member presence + durable inbox (Sprint 5, Cards 2 + 5).

Presence is owned by the model manager (Card 4); until it exists, the
hub keeps this in-memory store and exposes an authenticated endpoint
for the manager — or an operator — to set it.

The inbox is durable (Card 5): queued messages persist to a JSON file
with the same atomic-write discipline as the token and session stores,
so a hub restart loses nothing. On wake, the hub drains a member's
queue in arrival order through the normal chat path. Queued messages
are custody, not memory: nothing touches any memory scope until the
member actually processes the turn.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.family import PRESENCE_STATES

logger = logging.getLogger("brainstem_4070.family_state")


class UnknownMemberError(KeyError):
    pass


class FamilyState:
    """Thread-safe presence + durable queue state for every registry
    member. Presence is runtime state (starts fresh each boot); the
    inbox is persistent."""

    def __init__(
        self,
        member_ids: List[str],
        default_presence: str = "awake",
        store_path: Optional[os.PathLike | str] = None,
    ):
        if default_presence not in PRESENCE_STATES:
            raise ValueError(f"invalid default presence {default_presence!r}")
        self._lock = threading.Lock()
        self._presence: Dict[str, str] = {m: default_presence for m in member_ids}
        # msg_id -> record, insertion-ordered per member (dicts preserve
        # insertion order, which is the drain order).
        self._inbox: Dict[str, Dict[str, dict]] = {m: {} for m in member_ids}
        # Sprint 6 R2: sleep/wake transition timestamps, persisted with
        # the inbox so "since you fell asleep" survives a hub restart.
        self._presence_log: Dict[str, Dict[str, str]] = {m: {} for m in member_ids}
        self._store_path = Path(store_path) if store_path else None
        self._load()

    def _check(self, member_id: str) -> None:
        if member_id not in self._presence:
            raise UnknownMemberError(member_id)

    # -- persistence ---------------------------------------------------

    def _load(self) -> None:
        if self._store_path is None or not self._store_path.is_file():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("inbox store unreadable (%s): %s — starting empty",
                         self._store_path, exc)
            return
        if not isinstance(raw, dict):
            return
        # v2 files carry {"version": 2, "inbox": ..., "presence_log": ...};
        # v1 files (Sprint 5) are the bare inbox map — read either.
        inbox_raw = raw.get("inbox") if "version" in raw else raw
        presence_raw = raw.get("presence_log", {}) if "version" in raw else {}
        for member_id, msgs in (inbox_raw or {}).items():
            # Messages for members no longer in the registry are kept on
            # disk (never silently dropped) but not loaded.
            if member_id in self._inbox and isinstance(msgs, dict):
                self._inbox[member_id] = msgs
        for member_id, log in (presence_raw or {}).items():
            if member_id in self._presence_log and isinstance(log, dict):
                self._presence_log[member_id] = log

    def _flush_locked(self) -> None:
        """Write the store to disk. Caller holds the lock. A flush
        failure must not fail the request (same posture as the token
        and session stores)."""
        if self._store_path is None:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
            payload = {
                "version": 2,
                "inbox": self._inbox,
                "presence_log": self._presence_log,
            }
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self._store_path)
        except OSError as exc:
            logger.warning("inbox store flush failed: %s", exc)

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
            # R2: sleep and wake edges are what the briefing windows on.
            now = datetime.now(timezone.utc).isoformat()
            if state == "asleep":
                self._presence_log[member_id]["last_asleep_at"] = now
            elif state == "awake":
                self._presence_log[member_id]["last_awake_at"] = now
            self._flush_locked()

    def last_asleep_at(self, member_id: str) -> Optional[str]:
        """When the member most recently went to sleep, or None if it
        has never slept on this store's watch."""
        self._check(member_id)
        with self._lock:
            return self._presence_log[member_id].get("last_asleep_at")

    # -- inbox ---------------------------------------------------------

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
            self._flush_locked()
        return msg_id

    def queue_depth(self, member_id: str) -> int:
        self._check(member_id)
        with self._lock:
            return sum(
                1 for m in self._inbox[member_id].values()
                if m["status"] == "queued"
            )

    def queued_messages(self, member_id: str) -> List[dict]:
        """Snapshot of pending messages in arrival order (drain order)."""
        self._check(member_id)
        with self._lock:
            return [
                dict(m) for m in self._inbox[member_id].values()
                if m["status"] == "queued"
            ]

    def get_message(self, member_id: str, msg_id: str) -> Optional[dict]:
        self._check(member_id)
        with self._lock:
            record = self._inbox[member_id].get(msg_id)
            return dict(record) if record else None

    def complete_message(self, member_id: str, msg_id: str, result: dict) -> None:
        """Mark a queued message answered, with the reply attached for
        the sender's poll."""
        self._check(member_id)
        with self._lock:
            record = self._inbox[member_id].get(msg_id)
            if record is None:
                return
            record["status"] = "answered"
            record["result"] = result
            record["answered_at"] = datetime.now(timezone.utc).isoformat()
            self._flush_locked()
