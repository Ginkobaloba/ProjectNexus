#!/usr/bin/env python3
"""
Registry-driven weights fetcher for the family of models.

Downloads a member's GGUF from Hugging Face into a storage tier, named
per the canonical convention (`weights_filename()`), so the model
manager's `ensure_hot()` finds it without ceremony:

    python scripts/fetch_weights.py --member vera                # -> cold tier
    python scripts/fetch_weights.py --member jeffery --tier hot
    python scripts/fetch_weights.py --member vera --list         # just show files
    python scripts/fetch_weights.py --all --dest D:/family_weights/cold

Auth: reads the Hugging Face token from HF_TOKEN, HUGGINGFACE_TOKEN, or
HUGGING_FACE_HUB_TOKEN (checked in that order). Per SECURITY.md the
token lives in a gitignored .env — `docker/.env` on the hub host — so
either export it first or run through something that sources the file:

    set -a; . docker/.env; set +a          # bash
    Get-Content docker/.env | ...           # or set it in PowerShell

Public repos (both registry defaults are apache-2.0) work without a
token; the token matters for gated/private repos and rate limits.

The download source is the registry's `gguf_repo` when set (base repos
usually ship safetensors only), else `source`. Split GGUFs are kept
under their own part names — llama.cpp loads from part 1 — and a single
file is placed under the canonical name.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "nodes"))
sys.path.insert(0, str(REPO_ROOT))

from core.family import FamilyMember, load_registry  # noqa: E402
from model_manager_4090.manager import weights_filename  # noqa: E402
from model_manager_4090.tiering import select_gguf_files  # noqa: E402

TOKEN_ENV_VARS = ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")

# Default tier mounts mirror nodes/model_manager_4090/config.py; override
# with --dest for anything else.
DEFAULT_TIER_DIRS = {
    "hot": "D:/family_weights/hot",
    "warm": "E:/family_weights/warm",
    "cold": "Z:/family_weights/cold",
}


def _token() -> str | None:
    for var in TOKEN_ENV_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()
    return None


def _hf_repo(spec: str) -> str:
    if not spec.startswith("hf:"):
        raise SystemExit(
            f"only hf: sources are fetchable; got {spec!r}. "
            "Local-path sources are already on disk by definition."
        )
    return spec[len("hf:"):]


def fetch_member(member: FamilyMember, dest: Path, list_only: bool, token: str | None) -> int:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError:
        raise SystemExit(
            "huggingface_hub is not installed: pip install huggingface_hub"
        )

    repo = _hf_repo(member.model.gguf_repo or member.model.source)
    api = HfApi(token=token)
    files = api.list_repo_files(repo)
    picks = select_gguf_files(files, member.model.quant)

    print(f"[{member.id}] repo {repo}, quant {member.model.quant}: "
          f"{len(picks)} matching file(s)")
    for f in picks:
        print(f"    {f}")
    if list_only:
        return 0
    if not picks:
        print(f"[{member.id}] ERROR: no {member.model.quant} gguf in {repo}")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    canonical = weights_filename(member)
    for i, remote_name in enumerate(picks):
        local = hf_hub_download(repo_id=repo, filename=remote_name, token=token)
        if len(picks) == 1:
            target = dest / canonical
        else:
            # Split model: keep part names (llama.cpp loads from part 1)
            # but note the canonical stem for the manager's benefit.
            target = dest / Path(remote_name).name
        print(f"[{member.id}] placing {target.name} ({i + 1}/{len(picks)})")
        shutil.copyfile(local, target)
    if len(picks) > 1:
        print(
            f"[{member.id}] NOTE: split model — {len(picks)} parts. "
            f"ensure_hot()/the registry expect {canonical!r}; point the "
            "manager at part 1 or merge with llama-gguf-split."
        )
    print(f"[{member.id}] done -> {dest}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--member", help="member or concierge id from the registry")
    who.add_argument("--all", action="store_true", help="every member + the concierge")
    parser.add_argument("--tier", choices=DEFAULT_TIER_DIRS, default="cold",
                        help="destination tier (default: cold — stage up with ensure_hot)")
    parser.add_argument("--dest", help="explicit destination dir (overrides --tier)")
    parser.add_argument("--list", action="store_true",
                        help="list matching repo files, download nothing")
    args = parser.parse_args()

    registry = load_registry(REPO_ROOT / "family" / "registry.yaml", REPO_ROOT)
    roster = list(registry.members) + (
        [registry.concierge] if registry.concierge else []
    )
    if args.member:
        roster = [x for x in roster if x.id == args.member]
        if not roster:
            raise SystemExit(f"no member or concierge {args.member!r} in the registry")

    token = _token()
    if token is None:
        print("note: no HF token in env (HF_TOKEN / HUGGINGFACE_TOKEN / "
              "HUGGING_FACE_HUB_TOKEN); fine for public repos. "
              "See docker/.env per SECURITY.md.")

    dest = Path(args.dest) if args.dest else Path(DEFAULT_TIER_DIRS[args.tier])
    rc = 0
    for entry in roster:
        rc |= fetch_member(entry, dest, args.list, token)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
