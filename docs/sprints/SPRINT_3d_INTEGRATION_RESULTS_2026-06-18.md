# Sprint 3d: Card 3 integration results (hermetic pass, Tailscale deferred)

Date: 2026-06-18
Author: BROOKFIELD Recovery Agent (Sonnet), under Drew's direction
Scope: Sprint 3d Card 3 acceptance, LAN-only path. Tailscale-gated sections are flagged DEFERRED, not run.
Companion to: `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md` (the original Card 3 source) and `docs/sprints/SPRINT_3d_PLAN_2026-06-18.md` (the plan of record).

## 1. Headline

The hermetic integration suite `tests/integration/` runs **20 passed, 4 skipped, 20 warnings in 7.11s** from the 4070 host. This matches the 2026-05-17 sandbox baseline (also 20 passed, 4 skipped) exactly. The suite that has been code-complete since 2026-05-17 has now been validated on the real target host, closing the long-open Sprint 3d validation loop on the part of the loop that does not depend on a live fabric.

The non-hermetic sections of the manual test plan (laptop, phone, CLI, Cortex-down behavior, token revocation, cross-device session continuity, live-smoke against the real wire) are not run in this PR. They are blocked on Card 2 fabric bring-up and on Tailscale recovery, both of which are tracked separately. See Section 4.

## 2. What this PR does

1. Documents the pytest run captured on the 4070 host.
2. Updates `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md` Section "Manual test plan completion checklist": ticks the pytest box, marks the other rows with a `[-]` deferred-or-blocked marker, each with the reason in line.
3. Records the dependency footnote that the audit had open: argon2-cffi must be installed at the brainstem environment level for the auth path to work on Windows + Python 3.13 + bundled OpenSSL 3.x. Without it the scrypt fallback hits the OpenSSL 32 MiB ceiling exactly (the auth.py call uses `maxmem=128 * N * r = 33,554,432` bytes which is equal to the ceiling, not strictly greater). This is an environment finding; no source change is shipped here. Captured for a future hygiene card.

This PR does not modify any source code under `nodes/`, `clients/`, `core/`, or `tests/`. It only adds this results doc and ticks one checkbox in the handoff.

## 3. Pytest transcript (4070 host)

### 3.1 Host + environment

| Field | Value |
|---|---|
| Host | BROOKFIELD_PC (4070, LAN 192.168.1.251) |
| Branch | sprint/3d-stabilize-2026-06-18 |
| HEAD | 3b194355d6abf6a479b5b2792cbd19577fb03ac2 |
| Python | 3.13.14 (Windows Store install, MS_qbz5n2kfra8p0) |
| pytest | 9.1.0 |
| fastapi | 0.136.1 |
| pydantic | 2.12.5 |
| pydantic-settings | installed |
| httpx | 0.28.1 |
| requests | installed |
| loguru | installed |
| uvicorn[standard] | installed |
| argon2-cffi | installed (required, see Section 5) |

### 3.2 Invocation

```
$env:PYTHONPATH = "nodes;."
$env:BRAINSTEM_METRICS_PATH = "$env:TEMP\test_metrics.jsonl"
$env:BRAINSTEM_TOKEN_STORE_PATH = "$env:TEMP\test_tokens.json"
python -m pytest tests/integration/ -v --tb=short
```

The PowerShell `nodes;.` is the Windows equivalent of the handoff's `PYTHONPATH=nodes:.`. Both env vars matter because the brainstem reads them at import time and otherwise falls back to `/data/metrics/` and `/data/auth/`, which a non-container host does not have.

### 3.3 Result

```
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.1.0, pluggy-1.6.0
rootdir: C:\dev\project-nexus
plugins: anyio-4.12.0
collecting ... collected 24 items

tests/integration/test_auth_paths.py::test_generate_without_bearer_returns_401 PASSED [  4%]
tests/integration/test_auth_paths.py::test_generate_with_invalid_token_returns_401 PASSED [  8%]
tests/integration/test_auth_paths.py::test_generate_with_revoked_token_returns_401 PASSED [ 12%]
tests/integration/test_auth_paths.py::test_generate_with_valid_token_returns_200 PASSED [ 16%]
tests/integration/test_auth_paths.py::test_malformed_authorization_header_returns_401 PASSED [ 20%]
tests/integration/test_auth_paths.py::test_health_anonymous_even_with_no_tokens_minted PASSED [ 25%]
tests/integration/test_cortex_down_contract.py::test_generate_returns_503_when_cortex_down PASSED [ 29%]
tests/integration/test_cortex_down_contract.py::test_cortex_down_response_has_retry_after_header PASSED [ 33%]
tests/integration/test_cortex_down_contract.py::test_cortex_timeout_is_classified_separately PASSED [ 37%]
tests/integration/test_cortex_down_contract.py::test_health_stays_200_while_cortex_down PASSED [ 41%]
tests/integration/test_cortex_down_contract.py::test_root_contract_documents_cortex_down_shape PASSED [ 45%]
tests/integration/test_cortex_down_contract.py::test_cortex_down_followed_by_recovery_succeeds PASSED [ 50%]
tests/integration/test_live_smoke.py::test_live_health_returns_200 SKIPPED [ 54%]
tests/integration/test_live_smoke.py::test_live_root_advertises_cortex_down_contract SKIPPED [ 58%]
tests/integration/test_live_smoke.py::test_live_generate_unauthenticated_returns_401 SKIPPED [ 62%]
tests/integration/test_live_smoke.py::test_live_generate_authenticated_returns_text SKIPPED [ 66%]
tests/integration/test_metrics_attribution.py::test_metric_record_attributes_token_on_happy_path PASSED [ 70%]
tests/integration/test_metrics_attribution.py::test_metric_record_attributes_token_on_cortex_down PASSED [ 75%]
tests/integration/test_session_memory.py::test_x_session_id_is_required PASSED [ 79%]
tests/integration/test_session_memory.py::test_session_id_propagates_to_memory_write PASSED [ 83%]
tests/integration/test_session_memory.py::test_session_id_propagates_to_memory_query PASSED [ 87%]
tests/integration/test_session_memory.py::test_cross_session_recall_same_token PASSED [ 91%]
tests/integration/test_session_memory.py::test_cross_session_recall_different_token PASSED [ 95%]
tests/integration/test_session_memory.py::test_turn_idx_increments_per_session PASSED [100%]

================= 20 passed, 4 skipped, 20 warnings in 7.11s ==================
```

The 4 skips are `test_live_smoke.py`, which auto-skips unless `NEXUS_LIVE_URL` and `NEXUS_LIVE_TOKEN` are set. Both are intentionally unset in this run because the live wire (Tailscale to brainstem) is not available; see Section 4.

The 20 warnings are the single existing class: pydantic v2 "class-based Config is deprecated" in `nodes/brainstem_4070/config.py:6`. Same warning as the 2026-05-17 baseline. Not a regression.

## 4. Manual checklist sections: status and reason for each

The acceptance criterion in `SPRINT_3d_PLAN_2026-06-18.md` Card 3 is that every box in the HANDOFF checklist is either ticked or marked intentionally-skipped with reason. The HANDOFF checklist now reads:

| Box | Status in this PR | Reason |
|---|---|---|
| Section A laptop browser | `[-]` BLOCKED-ON-CARD-2 | Requires brainstem reachable at `${BRAINSTEM_URL}`. The 4070 fabric is dark: docker compose is not running, `docker/.env` is missing on the 4070 working tree. Unblocks the moment Card 2 LAN-half lands. |
| Section B phone browser | `[-]` DEFERRED-ON-TAILSCALE | Phone path requires Tailscale on the phone and on the 4070. 4070 Tailscale is in NoState (offline 6 days, tx 15506868 rx 0). Per Sprint 3d plan Open Question 3, this is the carve-out path. |
| Section C CLI | `[-]` BLOCKED-ON-CARD-2 | Same reason as Section A. |
| Section D Cortex-down behavior | `[-]` BLOCKED-ON-CARD-2 | Same reason as Section A. The Cortex-down contract is exercised by the hermetic suite (6 of the 20 passing tests are this contract). The manual section validates the same contract end-to-end over the wire; that part needs the fabric live. |
| Section E token revocation | `[-]` BLOCKED-ON-CARD-2 | Same reason as Section A. The hermetic suite exercises the token-revoked-without-restart path; manual section confirms the same against the live brainstem. |
| Section F cross-device session continuity | `[-]` DEFERRED-ON-TAILSCALE | Two-device path requires Tailscale on both. |
| Section G optional items | `[-]` BLOCKED-ON-CARD-2 | Optional pass over failure modes the suite cannot reach. Requires fabric live. |
| pytest tests/integration/ | `[x]` DONE | 20 passed, 4 skipped, see Section 3. |
| Live-smoke subset | `[-]` DEFERRED-ON-TAILSCALE-AND-FABRIC | Needs both Tailscale up and fabric live to drive the real wire. Both gated. |

The honest read: every box that does not require a live fabric or a live Tailscale is ticked. Every box that requires either is marked with a reason naming exactly which precondition is missing.

## 5. Environment finding: argon2-cffi is required (not a source change)

First pytest attempt on the 4070 produced 15 failures of the same shape:

```
nodes\brainstem_4070\auth.py:88: in _scrypt_hash
    dk = hashlib.scrypt(
E   ValueError: [digital envelope routines] memory limit exceeded
```

This is the audit-noted bug: `_SCRYPT_N = 2**15`, `_SCRYPT_R = 8`, `_SCRYPT_P = 1`, and `maxmem = 128 * _SCRYPT_N * _SCRYPT_R = 33,554,432` bytes. OpenSSL's default memlimit is 32 MiB = 33,554,432 bytes, and the check is strict-greater, not greater-or-equal. The two numbers are equal, so OpenSSL refuses. Python 3.13.14 on Windows Store does not change this because the bundled OpenSSL still implements the same strict check.

Workaround used: `pip install argon2-cffi` on the 4070. `nodes/brainstem_4070/auth.py` prefers argon2id when `from argon2 import PasswordHasher` succeeds at import time, falling back to `_scrypt_hash` only on ImportError. With argon2-cffi present, the scrypt code path is never taken and the 15 failing tests pass.

Recommendation, not in this PR: add `argon2-cffi` to whatever dependency manifest ends up shipping for the brainstem (currently `reqirements.txt`, which has the typo), and either bump `maxmem` strictly above 32 MiB (e.g., `256 * _SCRYPT_N * _SCRYPT_R`) or drop the scrypt fallback. That is a one-line source edit and a one-line dep manifest edit; both are out of scope here under Drew's "recovery + test execution, no source mods" rule for Card 3.

## 6. Card 3 acceptance check

From `SPRINT_3d_PLAN_2026-06-18.md` Card 3:

> Acceptance: every checkbox in `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md` Section "Manual test plan completion checklist" either ticked or marked intentionally-skipped with reason. `pytest tests/integration/` run from the 4070 host with the result transcribed into the handoff. Live-smoke subset run with `NEXUS_LIVE_URL` and `NEXUS_LIVE_TOKEN` set.

Status:

- Every checkbox in the handoff is now either `[x]` or `[-]` with a reason. PASS.
- pytest tests/integration/ run from the 4070 host with the result transcribed. PASS, full transcript in Section 3, summary line back-ported to the handoff checkbox.
- Live-smoke subset with NEXUS_LIVE_URL and NEXUS_LIVE_TOKEN set. NOT RUN. Deferred on Tailscale + fabric.

Net: Card 3 lands as a partial. The hermetic half is closed. The wire-dependent half is blocked on Card 2 (fabric) and on Tailscale recovery, both of which are independent cards.

## 7. What needs to happen for full Card 3 closure

To tick the remaining boxes, in dependency order:

1. **Card 1 merge** (`sprint/3d-stabilize-2026-06-18` to `main`). The 4070 still has only `foundation/consolidation` as its non-detached local branch as of this run; it picked up `sprint/3d-stabilize-2026-06-18` only because this agent fetched and checked it out over SSH. Once Card 1 merges, the 4070 should be `git fetch && git checkout main` and live there.
2. **Card 2 fabric bring-up on 4070**: install Docker if not present, run `scripts/setup/refresh-tailscale-bind.ps1` to mint a fresh `docker/.env`, `docker compose up -d`, confirm `/health` returns 200 on LAN at `http://192.168.1.251:5001/health`.
3. **Tailscale recovery on 4070**: `tailscale up` on the 4070 host, either interactive browser-auth or with a fresh `--authkey` from the Tailscale admin console. The Windows Tailscale service is Running but stuck in NoState as of this run.
4. **Card 3 manual run**: with the fabric live and Tailscale up, Drew walks Sections A through G of `docs/manual_integration_test_plan.md`, ticks the boxes in the handoff.
5. **Card 3 live-smoke**: `NEXUS_LIVE_URL=http://100.89.210.52:5001 NEXUS_LIVE_TOKEN=<minted> python -m pytest tests/integration/test_live_smoke.py -v` from any Tailscale-connected host.

Once 2 through 5 are done, the remaining `[-]` rows in the handoff turn into `[x]` rows and Card 3 is fully closed.

## 8. Files touched by this PR

- `docs/sprints/SPRINT_3d_INTEGRATION_RESULTS_2026-06-18.md` (new, this file)
- `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md` (checklist updated, one box ticked, others marked with reasons; legend appended)

No source files touched. No test files touched. No dependency manifests touched.

---

Sources: this doc is grounded on the live pytest run captured on BROOKFIELD_PC on 2026-06-18 (transcript in Section 3), the existing `docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md`, `docs/manual_integration_test_plan.md`, `docs/sprints/SPRINT_3d_PLAN_2026-06-18.md`, and `C:\dev\NEXUS_STATE_AUDIT_2026-06-16.md` Section 4 finding 6 (the scrypt/OpenSSL note).
