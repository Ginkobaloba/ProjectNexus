#!/usr/bin/env python3
"""
Sprint 3b token CLI.

Mints, lists, and revokes brainstem bearer tokens. Operates directly on
the token store JSON file the brainstem reads. Designed to be run from
inside the brainstem container so the plaintext token never crosses the
network:

    docker compose exec brainstem python scripts/create_token.py --name laptop

The plaintext token is printed once. Hash + metadata land in the token
store. The brainstem picks up the new entry on the next request (the
store rereads when its mtime changes).

Examples:
    python scripts/create_token.py --name laptop          # mint
    python scripts/create_token.py --list                 # list all
    python scripts/create_token.py --revoke laptop        # remove
    python scripts/create_token.py --store /tmp/t.json    # custom path

See docs/auth_middleware.md for the storage format and the rationale.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


# Make the brainstem package importable when running from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "nodes"))
sys.path.insert(0, str(REPO_ROOT))


# Match the brainstem's default. Override with --store or the
# BRAINSTEM_TOKEN_STORE_PATH env var so this script works inside the
# container (where the volume mount is /data/auth) and outside it.
DEFAULT_STORE = os.environ.get(
    "BRAINSTEM_TOKEN_STORE_PATH",
    "/data/auth/tokens.json",
)


def _resolve_store_path(args: argparse.Namespace) -> Path:
    raw = args.store or DEFAULT_STORE
    return Path(raw).expanduser()


def _action_create(args: argparse.Namespace) -> int:
    from brainstem_4070.auth import TokenStore

    store_path = _resolve_store_path(args)
    store = TokenStore.load(store_path)
    try:
        token, entry = store.create(args.name)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    print()
    print(f"  Token name : {entry.name}")
    print(f"  Created at : {entry.created_at}")
    print(f"  Store      : {store_path}")
    print()
    print("  Paste this into the client's config (or NEXUS_AUTH_TOKEN env var).")
    print("  This is the only time the plaintext token will be shown.")
    print()
    print(f"  {token}")
    print()
    return 0


def _action_list(args: argparse.Namespace) -> int:
    from brainstem_4070.auth import TokenStore

    store_path = _resolve_store_path(args)
    store = TokenStore.load(store_path)
    entries = store.list_entries()
    if not entries:
        print(f"  (no tokens in {store_path})")
        return 0
    print()
    print(f"  Tokens in {store_path}:")
    print()
    fmt = "  {name:<20} {created:<32} {last:<32} {uses}"
    print(fmt.format(name="name", created="created_at", last="last_used_at", uses="uses"))
    print(fmt.format(name="-" * 4, created="-" * 10, last="-" * 12, uses="-" * 4))
    for e in entries:
        print(fmt.format(
            name=e.name,
            created=e.created_at or "-",
            last=e.last_used_at or "-",
            uses=str(e.use_count),
        ))
    print()
    return 0


def _action_revoke(args: argparse.Namespace) -> int:
    from brainstem_4070.auth import TokenStore

    store_path = _resolve_store_path(args)
    store = TokenStore.load(store_path)
    removed = store.revoke(args.revoke)
    if not removed:
        print(f"[warn] no token named '{args.revoke}' in {store_path}", file=sys.stderr)
        return 1
    print(f"  Revoked token '{args.revoke}'.")
    print(f"  Brainstem will deny requests with that token on the next file mtime tick.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Mint, list, and revoke Nexus brainstem bearer tokens.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--store",
        default=None,
        help=(
            "path to the token store JSON file "
            f"(default: $BRAINSTEM_TOKEN_STORE_PATH or {DEFAULT_STORE})"
        ),
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--name",
        default=None,
        help="mint a new token under this name and print it once",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="list every token name with created/last-used/use-count",
    )
    group.add_argument(
        "--revoke",
        default=None,
        help="revoke the token with this name",
    )
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.name:
        return _action_create(args)
    if args.list:
        return _action_list(args)
    if args.revoke:
        return _action_revoke(args)
    # argparse's mutually-exclusive required group prevents this.
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
