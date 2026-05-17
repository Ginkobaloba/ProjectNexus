# nodes/brainstem_4070/auth.py
"""
Sprint 3b auth middleware: long-lived bearer tokens, hashed on disk,
attributable per request.

Design lives in `docs/auth_middleware.md`. Short version:

- Tokens are minted by `scripts/create_token.py`, printed once, never
  stored in plaintext.
- The brainstem keeps a JSON file at `/data/auth/tokens.json` (mounted
  to the `auth_data` docker named volume) with entries of the shape
  `{name, hash, created_at, last_used_at, use_count}`.
- argon2id via `argon2-cffi` is the preferred KDF. If the library is
  not importable, we fall back to `hashlib.scrypt` with a strong work
  factor and a documented PHC-like serialization we own. Both branches
  produce hashes that are verifiable in constant-ish time.
- The middleware is a FastAPI dependency `require_token` that reads
  `Authorization: Bearer <token>`, walks the loaded entries, and 401s
  on the slightest issue. On success it attaches the token's name to
  `request.state` for downstream attribution.

The store-loading is intentionally simple: every request rereads only
if the file's mtime changed since the last load. That keeps token
revocation effective without a brainstem restart and avoids hammering
disk on every call.

Out of scope here: rotation policy, per-endpoint scopes, rate limits.
See the design doc for why.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Header, HTTPException, Request

logger = logging.getLogger("brainstem_4070.auth")


# ---------------------------------------------------------------------------
# KDF abstraction
# ---------------------------------------------------------------------------
# Two backends, same shape: hash(token) -> phc-like string, verify(hash,
# token) -> bool. argon2id is preferred; scrypt is the stdlib fallback.

_ARGON2_AVAILABLE = False
try:  # pragma: no cover - exercised by environment, not by tests directly
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError

    _argon2_hasher = PasswordHasher(
        # Defaults are already production-grade. We tune memory down
        # slightly so the brainstem container does not OOM on a verify
        # storm. 64 MiB is a comfortable compromise for a home lab.
        memory_cost=65536,  # 64 MiB
        time_cost=3,
        parallelism=4,
    )
    _ARGON2_AVAILABLE = True
except ImportError:
    _argon2_hasher = None  # type: ignore[assignment]
    VerifyMismatchError = Exception  # type: ignore[misc,assignment]
    InvalidHashError = Exception  # type: ignore[misc,assignment]


# Scrypt parameters when we have to use the fallback. These match
# RFC 7914's "interactive" baseline scaled up for 2026 hardware. The
# salt is 16 random bytes per token, embedded in the PHC-like string.
_SCRYPT_N = 2**15  # 32768
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_SALT_BYTES = 16


def _scrypt_hash(token: str) -> str:
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    dk = hashlib.scrypt(
        token.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=128 * _SCRYPT_N * _SCRYPT_R,  # enough headroom for the given N,r
    )
    return (
        f"$scrypt$N={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(dk).decode('ascii')}"
    )


def _scrypt_verify(stored: str, token: str) -> bool:
    try:
        prefix, params, salt_b64, hash_b64 = stored.split("$")[1:]
    except ValueError:
        return False
    if prefix != "scrypt":
        return False
    params_map: Dict[str, int] = {}
    for kv in params.split(","):
        k, _, v = kv.partition("=")
        try:
            params_map[k] = int(v)
        except ValueError:
            return False
    try:
        n = params_map["N"]
        r = params_map["r"]
        p = params_map["p"]
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (KeyError, ValueError):
        return False
    try:
        dk = hashlib.scrypt(
            token.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=128 * n * r,
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(dk, expected)


def hash_token(token: str) -> str:
    """Hash a token using argon2id if available, scrypt otherwise.

    Returns a self-describing string the verify path can parse. Callers
    should never need to know which backend produced a given hash;
    `verify_token` figures it out from the prefix.
    """
    if _ARGON2_AVAILABLE and _argon2_hasher is not None:
        return _argon2_hasher.hash(token)
    return _scrypt_hash(token)


def verify_token(stored_hash: str, token: str) -> bool:
    """Constant-time check of a candidate token against a stored hash.

    The branch on prefix lets us mix argon2 and scrypt entries in the
    same store without ceremony, which matters during a hypothetical
    migration from one backend to the other.
    """
    if not stored_hash or not token:
        return False
    if stored_hash.startswith("$argon2"):
        if not _ARGON2_AVAILABLE or _argon2_hasher is None:
            # We can read scrypt without argon2 but not the other way
            # around. Fail closed and surface the operational issue.
            logger.warning(
                "argon2 hash present in token store but argon2-cffi is not "
                "installed; cannot verify. Install argon2-cffi or re-mint "
                "the affected tokens to migrate to scrypt."
            )
            return False
        try:
            _argon2_hasher.verify(stored_hash, token)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False
        except Exception:
            # Any other error from argon2 is treated as a verification
            # failure rather than a 500. Belt and suspenders.
            logger.exception("unexpected argon2 verify error")
            return False
    if stored_hash.startswith("$scrypt$"):
        return _scrypt_verify(stored_hash, token)
    return False


# ---------------------------------------------------------------------------
# Token format
# ---------------------------------------------------------------------------

TOKEN_PREFIX = "nxs_"
TOKEN_RANDOM_BYTES = 32  # ~43 chars of url-safe base64 after the prefix


def mint_token() -> str:
    """Return a fresh bearer token. Caller is responsible for hashing and
    persisting via the token store; the plaintext token returned here is
    the only copy that will ever exist."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def looks_like_token(value: str) -> bool:
    """Cheap shape check before doing any KDF work. Not security; just a
    way to short-circuit obviously-wrong inputs and avoid CPU spend."""
    return bool(value) and value.startswith(TOKEN_PREFIX) and len(value) >= len(TOKEN_PREFIX) + 20


# ---------------------------------------------------------------------------
# Token store
# ---------------------------------------------------------------------------


@dataclass
class TokenEntry:
    name: str
    hash: str
    created_at: str
    last_used_at: Optional[str] = None
    use_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "hash": self.hash,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "use_count": self.use_count,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "TokenEntry":
        return cls(
            name=str(raw["name"]),
            hash=str(raw["hash"]),
            created_at=str(raw.get("created_at") or ""),
            last_used_at=raw.get("last_used_at"),
            use_count=int(raw.get("use_count") or 0),
        )


@dataclass
class TokenStore:
    """JSON-backed token registry. Thread-safe for the read-mostly
    workload the brainstem produces.

    The store reloads from disk only when the file mtime changes since
    the last successful load. That keeps revocation effective inside a
    running brainstem (mint a token elsewhere, the next request after
    the file's mtime ticks sees it) without paying for a disk read on
    every request.
    """

    path: Path
    _entries: List[TokenEntry] = field(default_factory=list)
    _mtime_ns: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def load(cls, path: os.PathLike | str) -> "TokenStore":
        store = cls(path=Path(path))
        store._reload_if_changed(force=True)
        return store

    # -- file I/O ----------------------------------------------------------

    def _reload_if_changed(self, *, force: bool = False) -> None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            with self._lock:
                self._entries = []
                self._mtime_ns = 0
            return
        if not force and stat.st_mtime_ns == self._mtime_ns:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("token store unreadable (%s): %s", self.path, exc)
            return
        entries_raw = raw.get("tokens", []) if isinstance(raw, dict) else []
        entries: List[TokenEntry] = []
        for item in entries_raw:
            try:
                entries.append(TokenEntry.from_dict(item))
            except (KeyError, ValueError, TypeError):
                logger.warning("skipping malformed token entry in %s", self.path)
        with self._lock:
            self._entries = entries
            self._mtime_ns = stat.st_mtime_ns

    def _flush(self) -> None:
        """Write the in-memory entries back to disk atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "version": 1,
            "kdf": "argon2id" if _ARGON2_AVAILABLE else "scrypt",
            "tokens": [e.to_dict() for e in self._entries],
        }
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            self._mtime_ns = self.path.stat().st_mtime_ns
        except FileNotFoundError:  # pragma: no cover - replace just succeeded
            self._mtime_ns = 0

    # -- public API --------------------------------------------------------

    def list_entries(self) -> List[TokenEntry]:
        """Return a snapshot of the current entries. Caller-safe (we
        return shallow copies of the dataclass instances)."""
        self._reload_if_changed()
        with self._lock:
            return [TokenEntry(**e.to_dict()) for e in self._entries]

    def create(self, name: str) -> Tuple[str, TokenEntry]:
        """Mint a token, hash it, persist the entry, return both. The
        plaintext token is the caller's only copy."""
        if not name or not name.strip():
            raise ValueError("token name is required")
        name = name.strip()
        self._reload_if_changed()
        with self._lock:
            if any(e.name == name for e in self._entries):
                raise ValueError(f"a token named '{name}' already exists; revoke it first")
            token = mint_token()
            entry = TokenEntry(
                name=name,
                hash=hash_token(token),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._entries.append(entry)
            self._flush()
            return token, entry

    def revoke(self, name: str) -> bool:
        """Remove the entry with the given name. Returns True if removed."""
        self._reload_if_changed()
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.name != name]
            removed = len(self._entries) < before
            if removed:
                self._flush()
            return removed

    def verify(self, token: str) -> Optional[TokenEntry]:
        """Walk the entries, return the matching one (or None). On
        match, update last_used_at and use_count and flush.

        We walk every entry on a miss to avoid timing leakage about
        which entry is closest to the candidate. n is small so the cost
        is bounded.
        """
        if not looks_like_token(token):
            return None
        self._reload_if_changed()
        matched: Optional[TokenEntry] = None
        with self._lock:
            for entry in self._entries:
                if verify_token(entry.hash, token):
                    matched = entry
                    # Do not break: keep verifying remaining entries so
                    # total CPU per call is independent of which entry
                    # matched. Cheap insurance against timing analysis.
                else:
                    pass
            if matched is not None:
                matched.last_used_at = datetime.now(timezone.utc).isoformat()
                matched.use_count += 1
                try:
                    self._flush()
                except OSError as exc:
                    # Flush failure should not deny a valid token. Log it
                    # and move on; we will retry on the next request.
                    logger.warning("token-store flush failed: %s", exc)
        return matched


# ---------------------------------------------------------------------------
# Process-wide store + FastAPI integration
# ---------------------------------------------------------------------------

_STORE: Optional[TokenStore] = None
_STORE_LOCK = threading.Lock()


def configure_store(path: os.PathLike | str) -> TokenStore:
    """Initialize (or replace) the process-wide token store. Called
    once at brainstem startup and again in tests against tmp paths."""
    global _STORE
    with _STORE_LOCK:
        _STORE = TokenStore.load(path)
        return _STORE


def get_store() -> TokenStore:
    if _STORE is None:
        raise RuntimeError(
            "auth token store is not configured; call configure_store() at startup"
        )
    return _STORE


def _parse_bearer(value: Optional[str]) -> Optional[str]:
    """Pull the token out of `Authorization: Bearer <token>`. Returns
    None if the header is missing or shaped wrong."""
    if not value:
        return None
    parts = value.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def require_token(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> TokenEntry:
    """FastAPI dependency. 401 on any failure mode; on success attaches
    token attribution to request.state and returns the entry so callers
    can also see it directly."""
    token = _parse_bearer(authorization)
    if not token:
        logger.warning("auth fail: missing or malformed Authorization header")
        raise HTTPException(status_code=401, detail="missing or invalid Authorization header")
    store = get_store()
    entry = store.verify(token)
    if entry is None:
        logger.warning("auth fail: invalid token")
        raise HTTPException(status_code=401, detail="invalid token")
    request.state.token_name = entry.name
    logger.info("auth ok: token=%s", entry.name)
    return entry
