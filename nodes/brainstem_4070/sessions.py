# nodes/brainstem_4070/sessions.py
"""
Hub-minted persistent sessions (Sprint 5, Card 2).

One session per (person, member) pair, minted by the hub the first time
that person talks to that member and reused forever after. The store
persists to a JSON file so a brainstem restart no longer resets turn
counters — the wart documented in the Sprint 2 notes where turn_idx
resumed from 0 after every restart.

The persisted turn_idx is the durable copy; the brainstem's in-memory
per-session counter remains the runtime authority and is seeded from
here on first use after a restart.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger("brainstem_4070.sessions")


class HubSessionStore:
    """JSON-backed (person, member) -> {session_id, turn_idx} map.

    Writes are atomic (tmp file + os.replace), mirroring the token
    store's flush discipline. The file is tiny — one entry per
    relationship — so rewriting it wholesale on every change is fine.
    """

    def __init__(self, path: os.PathLike | str):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict] = {}
        self._load()

    @staticmethod
    def _key(person: str, member_id: str) -> str:
        return f"{person}::{member_id}"

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A corrupt session file should not stop the hub from
            # booting; relationships restart at turn 0, which is the
            # pre-Card-2 status quo, and the error is surfaced loudly.
            logger.error("session store unreadable (%s): %s — starting empty", self._path, exc)
            return
        if isinstance(raw, dict):
            self._sessions = {
                k: v for k, v in raw.items()
                if isinstance(v, dict) and "session_id" in v
            }

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._sessions, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def get_or_mint(self, person: str, member_id: str) -> Tuple[str, int]:
        """Return (session_id, stored_turn_idx) for the pair, minting
        and persisting a fresh session on first contact."""
        key = self._key(person, member_id)
        with self._lock:
            entry = self._sessions.get(key)
            if entry is None:
                entry = {
                    "session_id": f"sess_{uuid.uuid4().hex[:12]}",
                    "turn_idx": 0,
                }
                self._sessions[key] = entry
                self._flush()
                logger.info(
                    "minted session %s for person=%s member=%s",
                    entry["session_id"], person, member_id,
                )
            return entry["session_id"], int(entry.get("turn_idx", 0))

    def record_turn(self, person: str, member_id: str, turn_idx: int) -> None:
        """Persist the latest turn counter for the pair. Called after a
        successful memory write so the durable copy tracks the runtime
        counter."""
        key = self._key(person, member_id)
        with self._lock:
            entry = self._sessions.get(key)
            if entry is None:
                return
            entry["turn_idx"] = turn_idx
            try:
                self._flush()
            except OSError as exc:
                # Same posture as the token store: a flush failure must
                # not fail the request. Next turn retries.
                logger.warning("session store flush failed: %s", exc)
