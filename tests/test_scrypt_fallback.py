"""Regression: the scrypt fallback must actually work.

The Sprint 3b auth module prefers argon2id and falls back to
hashlib.scrypt when argon2-cffi is absent. The fallback shipped with
`maxmem` set to exactly 128*N*r — OpenSSL 3.x needs headroom above the
core requirement, so every token operation on an argon2-less install
raised "[digital envelope routines] memory limit exceeded" (observed on
Python 3.13.3 / OpenSSL 3.0.16; flagged in the PR #13 triage sweep).

These tests force the scrypt path regardless of whether argon2-cffi is
installed, so the fallback stays exercised on every machine instead of
only the ones where it is the last resort.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def scrypt_only(monkeypatch: pytest.MonkeyPatch):
    import brainstem_4070.auth as auth

    monkeypatch.setattr(auth, "_ARGON2_AVAILABLE", False)
    monkeypatch.setattr(auth, "_argon2_hasher", None)
    return auth


def test_scrypt_hash_verify_roundtrip(scrypt_only):
    auth = scrypt_only
    token = auth.mint_token()
    stored = auth.hash_token(token)
    assert stored.startswith("$scrypt$")
    assert auth.verify_token(stored, token) is True
    assert auth.verify_token(stored, auth.mint_token()) is False


def test_scrypt_token_store_roundtrip(scrypt_only, tmp_path):
    auth = scrypt_only
    store = auth.TokenStore.load(tmp_path / "tokens.json")
    token, entry = store.create("fallback_client")
    assert entry.hash.startswith("$scrypt$")

    matched = store.verify(token)
    assert matched is not None and matched.name == "fallback_client"
    assert store.verify(auth.mint_token()) is None


def test_scrypt_maxmem_has_headroom(scrypt_only):
    """The exact-fit value was the bug; whatever the helper returns must
    exceed the scrypt core requirement, not equal it."""
    auth = scrypt_only
    core = 128 * auth._SCRYPT_N * auth._SCRYPT_R
    assert auth._scrypt_maxmem(auth._SCRYPT_N, auth._SCRYPT_R) > core
