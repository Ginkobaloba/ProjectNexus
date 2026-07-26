"""Family registry loader (Sprint 5, Card 1).

`family/registry.yaml` is the single source of truth for who exists.
The hub loads it at startup through `load_registry()`; any structural
problem — unknown keys, duplicate ids, a missing or empty spec file —
is a hard failure with a message naming the offending entry, because a
half-valid family roster must never boot (V2 doc, Section 4.1).

Adding a member is data-only: weights download + a registry entry + a
spec file. Nothing in here special-cases any particular member.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .logging_config import get_logger

logger = get_logger("nexus.core.family")

# Presence states a member can be in. Owned by the model manager
# (Card 4); defined here so the registry, hub, and manager agree on
# the vocabulary.
PRESENCE_STATES = ("awake", "busy", "waking", "asleep")

_OFFLOAD_POLICIES = ("vram_then_ram", "vram_ram_ssd")
_STORAGE_TIERS = ("hot", "warm", "cold")
_MODEL_FORMATS = ("gguf",)


class _StrictModel(BaseModel):
    """Unknown keys in the registry are typos until proven otherwise —
    fail loud instead of silently ignoring a misspelled knob."""

    model_config = ConfigDict(extra="forbid")


class MemberModel(_StrictModel):
    source: str          # "hf:<org>/<repo>" or a local path — the model's identity
    # Optional: the HF repo the GGUF quants are downloaded from, when
    # it differs from source (base repos usually ship safetensors only;
    # quants live in quantizer repos). Used by scripts/fetch_weights.py.
    gguf_repo: Optional[str] = None
    format: str
    quant: str
    context_length: int

    @field_validator("format")
    @classmethod
    def _known_format(cls, v: str) -> str:
        if v not in _MODEL_FORMATS:
            raise ValueError(f"unknown model format {v!r}; expected one of {_MODEL_FORMATS}")
        return v

    @field_validator("context_length")
    @classmethod
    def _positive_ctx(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("context_length must be positive")
        return v


class MemberRuntime(_StrictModel):
    offload_policy: str
    sampling_defaults: Dict[str, float] = {}

    @field_validator("offload_policy")
    @classmethod
    def _known_policy(cls, v: str) -> str:
        if v not in _OFFLOAD_POLICIES:
            raise ValueError(
                f"unknown offload_policy {v!r}; expected one of {_OFFLOAD_POLICIES}"
            )
        return v


class MemberMemory(_StrictModel):
    collection: str


class FamilyMember(_StrictModel):
    id: str
    display_name: str
    spec_file: str
    model: MemberModel
    runtime: MemberRuntime
    memory: MemberMemory
    storage_tier_hint: str = "hot"

    @field_validator("id")
    @classmethod
    def _sane_id(cls, v: str) -> str:
        # Ids end up in API paths, Chroma collection names, and
        # provenance metadata — keep them boring on purpose.
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"member id {v!r} must be alphanumeric (plus _ and -)")
        return v

    @field_validator("storage_tier_hint")
    @classmethod
    def _known_tier(cls, v: str) -> str:
        if v not in _STORAGE_TIERS:
            raise ValueError(
                f"unknown storage_tier_hint {v!r}; expected one of {_STORAGE_TIERS}"
            )
        return v


class Concierge(_StrictModel):
    """Staff, not family (Sprint 6 R1): no memory block — the concierge
    has no scope of its own and works only from what it is handed —
    and no storage_tier_hint, because its weights live pinned on the
    4070, never tiered."""

    id: str
    display_name: str
    spec_file: str
    model: MemberModel
    runtime: MemberRuntime

    @field_validator("id")
    @classmethod
    def _concierge_sane_id(cls, v: str) -> str:
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"concierge id {v!r} must be alphanumeric (plus _ and -)")
        return v


class FamilyRegistry(_StrictModel):
    members: List[FamilyMember]
    concierge: Optional[Concierge] = None

    def get(self, member_id: str) -> FamilyMember:
        for m in self.members:
            if m.id == member_id:
                return m
        raise KeyError(member_id)

    def __contains__(self, member_id: str) -> bool:
        return any(m.id == member_id for m in self.members)


class RegistryError(RuntimeError):
    """Raised for any problem that should stop the hub from booting."""


def load_registry(registry_path: Path | str, repo_root: Path | str | None = None) -> FamilyRegistry:
    """Load and validate the family registry, or die trying.

    `repo_root` anchors the relative `spec_file` paths; it defaults to
    the registry file's grandparent (registry lives at
    <root>/family/registry.yaml).
    """
    registry_path = Path(registry_path)
    if repo_root is None:
        repo_root = registry_path.parent.parent
    repo_root = Path(repo_root)

    if not registry_path.is_file():
        raise RegistryError(f"family registry not found: {registry_path}")

    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryError(f"family registry is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise RegistryError("family registry must be a mapping with a `members` list")

    try:
        registry = FamilyRegistry(**raw)
    except ValidationError as exc:
        raise RegistryError(f"family registry failed validation:\n{exc}") from exc

    if not registry.members:
        raise RegistryError("family registry has no members")

    seen: Dict[str, int] = {}
    for m in registry.members:
        if m.id in seen:
            raise RegistryError(f"duplicate member id {m.id!r} in family registry")
        seen[m.id] = 1

        spec_path = repo_root / m.spec_file
        if not spec_path.is_file():
            raise RegistryError(
                f"member {m.id!r}: spec file {m.spec_file!r} not found under {repo_root}"
            )
        if not spec_path.read_text(encoding="utf-8").strip():
            raise RegistryError(f"member {m.id!r}: spec file {m.spec_file!r} is empty")

    if registry.concierge is not None:
        c = registry.concierge
        if c.id in seen:
            raise RegistryError(
                f"concierge id {c.id!r} collides with a family member id — "
                "staff and family are different things"
            )
        c_spec = repo_root / c.spec_file
        if not c_spec.is_file():
            raise RegistryError(
                f"concierge {c.id!r}: spec file {c.spec_file!r} not found under {repo_root}"
            )
        if not c_spec.read_text(encoding="utf-8").strip():
            raise RegistryError(f"concierge {c.id!r}: spec file {c.spec_file!r} is empty")

    logger.info(
        "family registry loaded: %d member(s): %s",
        len(registry.members),
        ", ".join(m.id for m in registry.members),
    )
    return registry


def load_member_spec(member: FamilyMember, repo_root: Path | str) -> str:
    """Read the member's spec file (its base system prompt)."""
    return (Path(repo_root) / member.spec_file).read_text(encoding="utf-8").strip()
