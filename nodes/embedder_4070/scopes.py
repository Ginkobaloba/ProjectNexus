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


def build_event_metadata(
    sensor_source: str,
    ts: str,
    reported_by: str,
) -> Dict[str, Any]:
    """Metadata for a household sensor event (V2 Section 8): born
    shared, never private. `sensor_source` names the device that saw it
    (e.g. jetson_backdoor_cam); `reported_by` is the service token that
    delivered it, for the same attribution trail conversations get."""
    if not sensor_source or not sensor_source.strip():
        raise ValueError("sensor_source is required for a sensor event")
    return {
        "scope": SHARED_SCOPE,
        "member_id": HOUSEHOLD_MEMBER_ID,
        "origin": "sensor",
        "sensor_source": sensor_source.strip(),
        "reported_by": reported_by,
        "participants": "",
        "ts": ts,
    }


def promoted_id(source_id: str) -> str:
    """Deterministic id for the shared copy of a promoted row. Same
    source promoted twice lands on the same id — promotion is
    idempotent per source row."""
    return f"{source_id}::promoted"


def build_promotion_metadata(
    source_meta: Dict[str, Any],
    member_id: str,
    promoted_by: str,
    source_id: str,
) -> Dict[str, Any]:
    """Metadata for the shared:household copy of a private row.

    Promotion copies, never moves (V2 Section 4.3): the private
    original is untouched and the copy carries the permanent paper
    trail — origin=promotion, promoted_from, promoted_by, and which
    member's private scope it came from. V1 promotes from the member's
    private scope only; experiential promotion arrives with Project
    Vector if ever.
    """
    source_scope = (source_meta or {}).get("scope")
    if source_scope != private_scope(member_id):
        raise ValueError(
            f"row {source_id!r} has scope {source_scope!r}; only rows in "
            f"{private_scope(member_id)!r} can be promoted by member {member_id!r}"
        )
    meta = dict(source_meta)
    meta.update(
        scope=SHARED_SCOPE,
        member_id=HOUSEHOLD_MEMBER_ID,
        origin="promotion",
        promoted_from=source_id,
        promoted_from_member=member_id,
        promoted_by=promoted_by,
    )
    return meta


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
