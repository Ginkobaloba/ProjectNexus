#!/usr/bin/env python3
"""
Sprint 5 Card 3 migration: grandfather pre-scope memory rows into
member #1's private scope.

Every row written before the scoped-memory change lacks `scope`
metadata, which makes it invisible to the always-filtered query path.
This script backfills exactly those rows with:

    scope        = private:<member>
    member_id    = <member>
    origin       = conversation
    participants = <--participants, comma-joined; empty by default
                    because pre-V2 rows never recorded who spoke>

Rows that already carry a scope are never touched — the migration is
idempotent and safe to re-run. Nothing is ever deleted.

Designed to run inside the embedder container (it owns the Chroma
volume):

    docker compose exec embedder python scripts/migrate_memory_scopes.py            # dry run
    docker compose exec embedder python scripts/migrate_memory_scopes.py --apply    # do it

The dry run prints the reconciliation plan (total / already-scoped /
to-update) and exits nonzero if applying would still leave unscoped
rows (which would mean a logic error worth stopping for).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "nodes"))
sys.path.insert(0, str(REPO_ROOT))

from embedder_4070.scopes import plan_scope_backfill  # noqa: E402

BATCH = 500


def _load_registry_default_member() -> str:
    from core.family import load_registry

    registry = load_registry(REPO_ROOT / "family" / "registry.yaml", REPO_ROOT)
    return registry.members[0].id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--member",
        help="member id to grandfather rows into (default: first registry member)",
    )
    parser.add_argument(
        "--participants",
        default="",
        help="comma-separated participants to stamp on migrated rows (default: none)",
    )
    parser.add_argument(
        "--persist-dir",
        help="Chroma persist directory (default: embedder service setting)",
    )
    parser.add_argument(
        "--collection",
        help="collection name (default: embedder service setting)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write the updates; without this flag it's a dry run",
    )
    args = parser.parse_args()

    member_id = args.member or _load_registry_default_member()
    participants = [p for p in args.participants.split(",") if p.strip()]

    import chromadb
    from embedder_4070.config import settings

    persist_dir = args.persist_dir or settings.chroma_persist_dir
    collection_name = args.collection or settings.chroma_collection

    client = chromadb.PersistentClient(path=persist_dir)
    coll = client.get_or_create_collection(name=collection_name)

    total = coll.count()
    print(f"collection {collection_name!r} at {persist_dir}: {total} rows")

    updated = 0
    already_scoped = 0
    offset = 0
    while offset < total:
        page = coll.get(limit=BATCH, offset=offset, include=["metadatas"])
        ids = page.get("ids") or []
        metas = page.get("metadatas") or []
        if not ids:
            break
        offset += len(ids)

        upd_ids, upd_metas = plan_scope_backfill(ids, metas, member_id, participants)
        already_scoped += len(ids) - len(upd_ids)
        updated += len(upd_ids)
        if upd_ids and args.apply:
            coll.update(ids=upd_ids, metadatas=upd_metas)

    verb = "updated" if args.apply else "would update"
    print(
        f"reconciliation: total={total} already_scoped={already_scoped} "
        f"{verb}={updated} -> scope=private:{member_id}"
    )
    if already_scoped + updated != total:
        print("ERROR: rows unaccounted for — aborting; nothing further changed.")
        return 1
    if not args.apply:
        print("dry run only; re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
