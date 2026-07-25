"""Sprint 5 Card 1: family registry loader + validation.

Done-criterion under test: the hub can boot its roster from
`family/registry.yaml` alone, and every malformed registry fails loud
at load time rather than half-booting.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.family import RegistryError, load_member_spec, load_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_registry(tmp_path: Path, body: str) -> Path:
    family_dir = tmp_path / "family"
    family_dir.mkdir()
    reg = family_dir / "registry.yaml"
    reg.write_text(body, encoding="utf-8")
    return reg


def _spec(tmp_path: Path, rel: str = "family/vera/spec.md") -> None:
    spec = tmp_path / rel
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# Vera\nBe kind.\n", encoding="utf-8")


VALID = """
members:
  - id: "vera"
    display_name: "Vera"
    spec_file: "family/vera/spec.md"
    model:
      source: "hf:Qwen/Qwen3-30B-A3B-Instruct-2507"
      format: "gguf"
      quant: "Q4_K_M"
      context_length: 32768
    runtime:
      offload_policy: "vram_then_ram"
      sampling_defaults: {temperature: 0.7, top_p: 0.9}
    memory:
      collection: "member_vera"
    storage_tier_hint: "hot"
"""


def test_checked_in_registry_is_valid():
    """The real registry in the repo must always load."""
    registry = load_registry(REPO_ROOT / "family" / "registry.yaml")
    assert "vera" in registry
    member = registry.get("vera")
    assert member.model.format == "gguf"
    spec = load_member_spec(member, REPO_ROOT)
    assert "Vera" in spec


def test_valid_registry_loads(tmp_path):
    reg = _write_registry(tmp_path, VALID)
    _spec(tmp_path)
    registry = load_registry(reg)
    assert registry.get("vera").display_name == "Vera"
    assert registry.get("vera").runtime.sampling_defaults["temperature"] == 0.7


def test_second_member_is_data_only(tmp_path):
    """Adding member #2 = one more yaml entry + spec file. No code."""
    second = VALID + """
  - id: "juno"
    display_name: "Juno"
    spec_file: "family/juno/spec.md"
    model:
      source: "hf:example/model"
      format: "gguf"
      quant: "Q5_K_M"
      context_length: 8192
    runtime:
      offload_policy: "vram_ram_ssd"
    memory:
      collection: "member_juno"
    storage_tier_hint: "warm"
"""
    reg = _write_registry(tmp_path, second)
    _spec(tmp_path)
    _spec(tmp_path, "family/juno/spec.md")
    registry = load_registry(reg)
    assert [m.id for m in registry.members] == ["vera", "juno"]


def test_duplicate_id_fails(tmp_path):
    reg = _write_registry(tmp_path, VALID + VALID.replace("members:", ""))
    _spec(tmp_path)
    with pytest.raises(RegistryError, match="duplicate member id"):
        load_registry(reg)


def test_missing_spec_file_fails(tmp_path):
    reg = _write_registry(tmp_path, VALID)  # no spec written
    with pytest.raises(RegistryError, match="spec file"):
        load_registry(reg)


def test_unknown_key_fails(tmp_path):
    reg = _write_registry(tmp_path, VALID.replace(
        "storage_tier_hint", "storage_teir_hint"))
    _spec(tmp_path)
    with pytest.raises(RegistryError, match="validation"):
        load_registry(reg)


def test_bad_offload_policy_fails(tmp_path):
    reg = _write_registry(tmp_path, VALID.replace(
        "vram_then_ram", "sharded_across_gpus"))
    _spec(tmp_path)
    with pytest.raises(RegistryError, match="offload_policy"):
        load_registry(reg)


def test_empty_registry_fails(tmp_path):
    reg = _write_registry(tmp_path, "members: []\n")
    with pytest.raises(RegistryError, match="no members"):
        load_registry(reg)


def test_missing_file_fails(tmp_path):
    with pytest.raises(RegistryError, match="not found"):
        load_registry(tmp_path / "family" / "registry.yaml")
