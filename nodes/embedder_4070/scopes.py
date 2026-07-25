# nodes/embedder_4070/scopes.py
"""
Memory scopes + provenance (Sprint 5, Card 3).

Every memory row carries a scope, and retrieval is ALWAYS filtered
server-side to the querying member's visible set:

    private:<member> + shared:household + experiential:<member>

Cross-member recall is forbidden by construction — the filter lives
here, in the service that owns the store, not in the callers. This
amends Sprint 2's deliberate no-filter design: cross-session recall
*within* a member survives; cross-member reads do not exist.

Pure functions only (no Chroma, no model) so the privacy rules are
testable without loading anything heavy.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SHARED_SCOPE = "shared:household"
HOUSEHOLD_MEMBER_ID = "household"

# origin values a memory row can carry (V2 doc Section 4.3; the
# delegated_task origin lands with the concierge in V1.5 but the
# vocabulary is fixed now so rows never need re-labelling).
ORIGINS = (
    "conversation",
    "sensor",
    "promotion",
    "vector_platform",
    "delegated_task",
)


def private_scope(member_id: str) -> str:
    return f"private:{member_id}"


def experiential_scope(member_id: str) -> str:
    return f"experiential:{member_id}"


def readable_scopes(member_id: str) -> List[str]:
    """Everything member `member_id` may ever retrieve. There is no
    variant of this list without the filter — that's the point."""
    return [private_scope(member_id), SHARED_SCOPE, experiential_scope(member_id)]


def validate_write_scope(scope: str, member_id: str) -> None:
    """A member may write to its own private/experiential scope or to
    the shared household scope — never into another member's scopes."""
    if scope not in readable_scopes(member_id):
        raise ValueError(
            f"scope {scope!r} is not writable for member {member_id!r}; "
            f"allowed: {readable_scopes(member_id)}"
        )


def validate_origin(origin: str) -> None:
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin {origin!r}; expected one of {ORIGINS}")


def build_where(
    member_id: str,
    session_id_filter: Optional[str] = None,
    exclude_parent_turn_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The Chroma `where` clause for a query by `member_id`. The scope
    condition is unconditional; the others are opt-in refinements."""
    conds: List[Dict[str, Any]] = [{"scope": {"$in": readable_scopes(member_id)}}]
    if session_id_filter:
        conds.append({"session_id": session_id_filter})
    if exclude_parent_turn_id:
        conds.append({"parent_turn_id": {"$ne": exclude_parent_turn_id}})
    return conds[0] if len(conds) == 1 else {"$and": conds}


def participants_to_meta(participants: Optional[List[str]]) -> str:
    """Chroma metadata values must be scalars; participants are stored
    as a comma-joined string, order preserved, blanks dropped."""
    return ",".join(p.strip() for p in (participants or []) if p and p.strip())


def plan_scope_backfill(
    ids: List[str],
    metadatas: List[Optional[Dict[str, Any]]],
    member_id: str,
    participants: Optional[List[str]] = None,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Migration planner: given existing rows, return (ids, merged
    metadatas) for exactly the rows that lack a scope. Pre-V2 rows are
    grandfathered into `private:<member_id>` with origin=conversation —
    they were all 1-on-1 turns with member #1's predecessor. Rows that
    already carry a scope are untouched (the migration is idempotent).
    """
    update_ids: List[str] = []
    update_metas: List[Dict[str, Any]] = []
    for row_id, meta in zip(ids, metadatas):
        meta = dict(meta or {})
        if meta.get("scope"):
            continue
        meta.update(
            scope=private_scope(member_id),
            member_id=member_id,
            origin="conversation",
            participants=participants_to_meta(participants),
        )
        update_ids.append(row_id)
        update_metas.append(meta)
    return update_ids, update_metas
