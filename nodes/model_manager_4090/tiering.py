# nodes/model_manager_4090/tiering.py
"""
Weight tiering (Sprint 5, Card 4; V2 doc Section 7).

Weights live at rest on one of three tiers — hot (Gen4 NVMe), warm
(Gen2 NVMe), cold (HDD/NAS) — and `ensure_hot()` stages them up before
a load, because llama.cpp does not tier for us: mmap'ing a GGUF off
the HDD trades a one-time staged copy for misery on every page fault.

Safety rules, in order of importance:
  1. Never delete the only copy of a weights file. Eviction removes a
     hot copy only when a same-size copy exists on a lower tier.
  2. Copies are checksummed (sha256) and land under a temp name until
     verified — a torn copy can never be mistaken for a model.
  3. Pinned files are never evicted, LRU decides among the rest.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger("model_manager_4090.tiering")

TIER_ORDER = ("hot", "warm", "cold")


@dataclass
class TierPaths:
    hot: Path
    warm: Path
    cold: Path

    def dir_for(self, tier: str) -> Path:
        return {"hot": self.hot, "warm": self.warm, "cold": self.cold}[tier]

    def ensure_dirs(self) -> None:
        for d in (self.hot, self.warm, self.cold):
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class StageResult:
    path: Path              # the hot-tier path, ready to load
    staged_from: Optional[str]  # tier we copied from, None if already hot
    stage_copy_ms: float    # 0.0 when no copy happened
    sha256: Optional[str]   # digest of the staged copy (None if no copy)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def find_weights(filename: str, tiers: TierPaths) -> Optional[Tuple[str, Path]]:
    """Locate a weights file, preferring the hottest copy."""
    for tier in TIER_ORDER:
        candidate = tiers.dir_for(tier) / filename
        if candidate.is_file():
            return tier, candidate
    return None


def ensure_hot(filename: str, tiers: TierPaths) -> StageResult:
    """Stage a weights file onto the hot tier if it isn't there already.

    The copy goes to a `.staging` temp name, gets checksum-verified
    against the source, and only then renames into place — so a crash
    mid-copy leaves garbage with an obvious name instead of a plausible
    but corrupt model.
    """
    tiers.ensure_dirs()
    located = find_weights(filename, tiers)
    if located is None:
        raise FileNotFoundError(
            f"weights {filename!r} not found on any tier "
            f"(hot={tiers.hot}, warm={tiers.warm}, cold={tiers.cold})"
        )
    tier, source = located
    hot_path = tiers.hot / filename
    if tier == "hot":
        return StageResult(path=hot_path, staged_from=None, stage_copy_ms=0.0, sha256=None)

    staging = hot_path.with_suffix(hot_path.suffix + ".staging")
    t0 = time.monotonic_ns()
    shutil.copyfile(source, staging)
    source_digest = sha256_file(source)
    staged_digest = sha256_file(staging)
    if staged_digest != source_digest:
        staging.unlink(missing_ok=True)
        raise IOError(
            f"staged copy of {filename!r} failed checksum "
            f"(source {source_digest[:12]}…, copy {staged_digest[:12]}…)"
        )
    os.replace(staging, hot_path)
    stage_copy_ms = (time.monotonic_ns() - t0) / 1e6
    logger.info(
        "staged %s: %s -> hot in %.0fms (sha256 %s…)",
        filename, tier, stage_copy_ms, staged_digest[:12],
    )
    return StageResult(
        path=hot_path,
        staged_from=tier,
        stage_copy_ms=stage_copy_ms,
        sha256=staged_digest,
    )


def select_gguf_files(filenames: List[str], quant: str) -> List[str]:
    """Pick the GGUF file(s) for a quant out of a repo listing.

    Quantizer repos hold many quants side by side; we want exactly the
    requested one. Handles split models (`...Q4_K_M-00001-of-00003.gguf`)
    by returning every part, sorted so part 1 comes first — llama.cpp
    loads a split from its first part. Matching is case-insensitive on
    the quant tag to survive repo naming whims.
    """
    quant_lower = quant.lower()
    hits = sorted(
        f for f in filenames
        if f.lower().endswith(".gguf") and quant_lower in f.lower()
    )
    return hits


def evict_from_hot(
    tiers: TierPaths,
    needed_bytes: int,
    pinned: Set[str],
) -> List[str]:
    """Free at least `needed_bytes` on the hot tier by removing LRU
    weights files — never a pinned file, never the only copy.

    Returns the evicted filenames. With a single member (V1) this is
    exercised only by tests, but the rules ship now so member #2 is a
    registry entry, not a code change.
    """
    tiers.ensure_dirs()
    candidates = []
    for path in tiers.hot.iterdir():
        if not path.is_file() or path.name in pinned or path.name.endswith(".staging"):
            continue
        lower_copy = None
        for tier in ("warm", "cold"):
            other = tiers.dir_for(tier) / path.name
            if other.is_file() and other.stat().st_size == path.stat().st_size:
                lower_copy = other
                break
        if lower_copy is None:
            continue  # rule 1: never delete the only copy
        candidates.append(path)

    # LRU by last access, oldest first.
    candidates.sort(key=lambda p: p.stat().st_atime)

    evicted: List[str] = []
    freed = 0
    for path in candidates:
        if freed >= needed_bytes:
            break
        size = path.stat().st_size
        path.unlink()
        freed += size
        evicted.append(path.name)
        logger.info("evicted %s from hot tier (freed %d bytes)", path.name, size)
    return evicted
