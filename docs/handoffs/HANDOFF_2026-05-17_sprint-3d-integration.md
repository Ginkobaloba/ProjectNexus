# Handoff: 2026-05-17 Sprint 3d (end-to-end integration test of the brainstem fabric)

Status: code complete on `foundation/consolidation`. The automated
integration suite is in place at `tests/integration/` and runs green
in the agent sandbox (20 passed, 4 live-smoke skipped because the env
vars NEXUS_LIVE_URL / NEXUS_LIVE_TOKEN were not set). The full repo
suite, including the prior 22 unit tests from Sprint 3b and 3c, runs
green (42 passed, 4 skipped).

The Sprint 3c commit-and-push that this handoff inherited as a pending
manual step is still pending. Sprint 3d did not touch that state per
the brief. The PowerShell commands at the bottom of
`docs/handoffs/HANDOFF_2026-05-17_sprint-3c-exposure.md` are still
correct; the Sprint 3d files just get added to the same sequence.
A combined PowerShell block is at the bottom of this handoff for
convenience.

## What shipped

Sprint 3d validates that Sprint 3a (thin clients), 3b (auth), and 3c
(Tailscale-only exposure + Cortex-down 503 contract) work together as
a single coherent fabric, from a generic-client perspective.

### tests/integration/ - hermetic integration suite

A pytest suite that exercises every critical path against a real
FastAPI TestClient. Outbound dependencies (Cortex on 4090, the
embedder + Chroma) are stubbed in-process so the suite is hermetic
and runs offline. The stubs preserve the wire contracts the real
services expose, so a passing suite is genuine evidence the brainstem
plumbing works end-to-end.

Files:

- `tests/integration/__init__.py` - package marker.
- `tests/integration/conftest.py` (304 lines) - the `brainstem`
  fixture plus the `FakeCortex` and `FakeMemory` in-process stand-ins.
  FakeMemory ranks retrieval by token-overlap, which is enough to
  prove that retrieve-before-generate actually plumbs the prior turn
  into the system prompt without needing a real embedding model.
- `tests/integration/test_auth_paths.py` (94 lines) - no-token 401,
  invalid-token 401, revoked-token 401 without restart, malformed
  Authorization header 401, happy-path 200, /health anonymous even
  with no tokens minted.
- `tests/integration/test_cortex_down_contract.py` (118 lines) -
  Sprint 3c 503 contract observed from outside: cortex_unavailable
  code, cortex_timeout code with the longer retry window, Retry-After
  header matching the body, /health stays 200 during the outage, /
  index advertises the contract, recovery from down -> up does not
  stick.
- `tests/integration/test_session_memory.py` (174 lines) -
  X-Session-Id required, X-Session-Id propagates to memory_write,
  X-Session-Id propagates to memory_query (without scoping retrieval
  to that session), cross-session recall with the SAME token,
  cross-session recall with DIFFERENT tokens, turn_idx increments
  per-session.
- `tests/integration/test_metrics_attribution.py` (58 lines) -
  per-token attribution holds on the happy path AND on the 503 path,
  so dashboard breakdowns by client survive an outage.
- `tests/integration/test_live_smoke.py` (80 lines) - tiny live-stack
  subset that auto-skips unless NEXUS_LIVE_URL and NEXUS_LIVE_TOKEN
  are set. Confirms the real wire works. Tolerates a real Cortex
  outage by pytest.skip rather than a hard fail.

### docs/manual_integration_test_plan.md

Drew-runnable checklist covering laptop browser, phone browser, CLI,
Cortex-down handling, token revocation, cross-device session
continuity, and a "things to test if you have time but aren't
automatable" section covering real Tailscale dropouts, real token-
window exhaustion, real network partitions to the embedder, and
multi-client race conditions on the same session id.

326 lines. Every step is one curl, one click, or one CLI invocation.
Every step has an EXPECTED RESULT. Format is a flat checklist.

## Automated test results

Run from the agent sandbox with the brainstem package importable and
the in-process stubs in place:

```
tests/integration/test_auth_paths.py::test_generate_without_bearer_returns_401 PASSED
tests/integration/test_auth_paths.py::test_generate_with_invalid_token_returns_401 PASSED
tests/integration/test_auth_paths.py::test_generate_with_revoked_token_returns_401 PASSED
tests/integration/test_auth_paths.py::test_generate_with_valid_token_returns_200 PASSED
tests/integration/test_auth_paths.py::test_malformed_authorization_header_returns_401 PASSED
tests/integration/test_auth_paths.py::test_health_anonymous_even_with_no_tokens_minted PASSED
tests/integration/test_cortex_down_contract.py::test_generate_returns_503_when_cortex_down PASSED
tests/integration/test_cortex_down_contract.py::test_cortex_down_response_has_retry_after_header PASSED
tests/integration/test_cortex_down_contract.py::test_cortex_timeout_is_classified_separately PASSED
tests/integration/test_cortex_down_contract.py::test_health_stays_200_while_cortex_down PASSED
tests/integration/test_cortex_down_contract.py::test_root_contract_documents_cortex_down_shape PASSED
tests/integration/test_cortex_down_contract.py::test_cortex_down_followed_by_recovery_succeeds PASSED
tests/integration/test_live_smoke.py (4 tests) SKIPPED [env vars unset]
tests/integration/test_metrics_attribution.py::test_metric_record_attributes_token_on_happy_path PASSED
tests/integration/test_metrics_attribution.py::test_metric_record_attributes_token_on_cortex_down PASSED
tests/integration/test_session_memory.py::test_x_session_id_is_required PASSED
tests/integration/test_session_memory.py::test_session_id_propagates_to_memory_write PASSED
tests/integration/test_session_memory.py::test_session_id_propagates_to_memory_query PASSED
tests/integration/test_session_memory.py::test_cross_session_recall_same_token PASSED
tests/integration/test_session_memory.py::test_cross_session_recall_different_token PASSED
tests/integration/test_session_memory.py::test_turn_idx_increments_per_session PASSED

================== 20 passed, 4 skipped, 20 warnings in 2.74s ==================
```

And the full repo suite, to confirm no regression in the unit layer:

```
================== 42 passed, 4 skipped, 35 warnings in 4.58s ==================
```

22 of those passing tests are the Sprint 3b auth suite and the
Sprint 3c Cortex-down suite. 20 are the new integration tests. 4 are
the live-smoke tests, which skip cleanly when the env vars are unset.

The single warning class is the `pydantic` "class-based Config is
deprecated" message in `nodes/brainstem_4070/config.py`. Existing
finding, not introduced by Sprint 3d. Captured for cleanup in a
future hygiene pass.

### How to run the suite

From a developer machine with the brainstem importable (the same way
the prior unit tests run):

```
PYTHONPATH=nodes:. \
  BRAINSTEM_METRICS_PATH=/tmp/test_metrics.jsonl \
  BRAINSTEM_TOKEN_STORE_PATH=/tmp/test_tokens.json \
  python -m pytest tests/integration/ -v
```

The two env vars matter because the brainstem reads them at import
time and falls back to `/data/metrics/` and `/data/auth/` (the docker
mount points), which a dev box does not have. The same shape works on
the 4070 host as long as you have permission to write to those paths
or you override them as shown.

To run the live-smoke subset against the running 4070 stack:

```
NEXUS_LIVE_URL=http://100.89.210.52:5001 \
  NEXUS_LIVE_TOKEN=nxs_xxx \
  python -m pytest tests/integration/test_live_smoke.py -v
```

Substitute your real Tailscale URL and a valid token.

### How to run the manual plan

`docs/manual_integration_test_plan.md`. Run it linearly. Sections A
through F validate the public contracts; section G is the optional
"if you have time" pass that covers failure modes the automated suite
cannot reach (real Tailscale dropouts, real token-window exhaustion,
real partitions to the embedder, multi-client races on the same
session).

## Findings

No new bugs surfaced. Every test the brief asked for is green. A few
contract observations worth keeping in mind for Sprint 4:

1. **Cross-session recall does not respect token identity.** A turn
   written under one token IS retrievable from a session opened with
   a different token, because the brainstem does not scope retrieval
   by client identity. That is consistent with the current Sprint 2
   contract (cross-session means "across ANY session"), but it is a
   security choice Sprint 4 might want to revisit if Drew ever wants
   per-client memory walls. The dedicated test
   `test_cross_session_recall_different_token` will turn red the moment
   that contract changes intentionally; treat it as a tripwire, not a
   failure mode.

2. **turn_idx is per-session monotonic and in-process.** A brainstem
   restart resets the counter to 0 for a session whose memory rows
   exist in Chroma. That is fine for Phase 0 but it means a
   "what turn number is this" question across a restart will lie. Doc
   in `docs/manual_integration_test_plan.md` section G5. Sprint 4
   could lift the counter into Chroma metadata if it becomes a real
   problem.

3. **The brainstem trusts X-Session-Id from the client.** A
   misbehaving client could overwrite another client's session by
   sending its id. Auth limits this to known clients, but does not
   prevent it among trusted clients. Doc, not a bug. Sprint 4 could
   make session ids server-issued and HMAC-signed if the threat model
   warrants it.

## Manual test plan completion checklist (for Drew)

Drew runs this from the 4070 host after the Sprint 3c commit lands.

- [-] Section A laptop browser passed (A1, A2, A3, A4) -- BLOCKED-ON-CARD-2: requires brainstem reachable at `${BRAINSTEM_URL}`; fabric is still dark on the 4070 as of 2026-06-18 (docker compose not running, `docker/.env` missing). Unblocks when Card 2 lands.
- [-] Section B phone browser passed (B1, B2, B3) -- DEFERRED-ON-TAILSCALE: 4070 Tailscale is in NoState (offline 6 days). Phone path requires Tailscale on both sides. Recovery card carved out per Sprint 3d plan Open Question 3.
- [-] Section C CLI passed (C1, C2, C3) -- BLOCKED-ON-CARD-2 (same reason as Section A).
- [-] Section D Cortex-down behavior passed (D1, D2, D3, D4, D5) -- BLOCKED-ON-CARD-2 (same reason as Section A).
- [-] Section E token revocation passed (E1, E2, E3) -- BLOCKED-ON-CARD-2 (same reason as Section A).
- [-] Section F cross-device session continuity passed (F1, F2, F3) -- DEFERRED-ON-TAILSCALE (same reason as Section B).
- [-] Section G items tried (or intentionally skipped, noted here) -- BLOCKED-ON-CARD-2 (same reason as Section A).
- [x] `pytest tests/integration/` run from the 4070 host with the
  result transcribed back here. **2026-06-18: 20 passed, 4 skipped (live-smoke), 20 warnings in 7.11s on host BROOKFIELD_PC, branch sprint/3d-stabilize-2026-06-18 @ 3b194355d6abf6a479b5b2792cbd19577fb03ac2, Python 3.13.14. Matches the 2026-05-17 sandbox baseline exactly. Full transcript: `docs/sprints/SPRINT_3d_INTEGRATION_RESULTS_2026-06-18.md`.**
- [-] Live-smoke subset run with NEXUS_LIVE_URL and NEXUS_LIVE_TOKEN
  set, result transcribed back here. -- DEFERRED-ON-TAILSCALE-AND-FABRIC: needs both Tailscale up and fabric live to exercise the real wire. Both gated on Card 2 + Tailscale recovery.

Mark each checkbox in this file when done and commit the update. The
checklist is the audit trail.

Legend: `[x]` complete, `[ ]` open, `[-]` intentionally deferred or
blocked with reason in line.

## Sprint 4: bidirectional callback (the fabric differentiator)

The architecture's defining feature has been on the roadmap since
Stage 0: the 4070 brainstem and the 4090 cortex talk both ways.
Today the 4070 calls /generate on the 4090. Sprint 4 lets the 4090
call back: emit tool requests, request more context, or hand off
sub-problems to a peer. That bidirectionality is what makes the
fabric a fabric rather than a fancy reverse proxy.

Entry-point notes for Sprint 4 to start fast:

- **Read the design doc that does not exist yet.** Spend the first
  hour writing `docs/bidirectional_callback.md`. The shape probably
  involves a server-sent-events or websocket channel from the 4070
  back to the 4090, OR the 4090 polls a queue endpoint on the 4070.
  Both are tractable; the trade-offs are documented in the Phase 0
  experiment program already.
- **Pick the wire format before the wire.** Even if the first call
  is one tool request, design the envelope to carry many kinds. The
  current `/generate` request/response is shaped for one job; the
  callback channel should be event-shaped from day one.
- **Tests should follow the same pattern Sprint 3d used.** Stub the
  4090 in-process for the unit-level callbacks; layer integration
  tests that drive the brainstem from outside. The live-smoke
  pattern in `tests/integration/test_live_smoke.py` is the template
  for the real two-box validation.
- **The fake Cortex in `tests/integration/conftest.py` is a natural
  fit for the new callback shape.** Extend it to expose a hook the
  brainstem can register against, and you have an in-process
  callback target for tests on day one.
- **Auth across the callback channel matters.** The 4070 and the
  4090 are both trusted nodes, but the channel still needs a stable
  identity proof. Reuse the Sprint 3b token store on the 4090 side
  with a node-scoped token; do not introduce a second auth system.

The "smallest demo you can ship" for Sprint 4: the 4090, mid-
generation, asks the 4070 "do you have any context tagged
`#sprint4_test` for me?" - the 4070 responds with a small JSON blob
from the embedder - the 4090 keeps generating with that context. That
loop is the fabric differentiator in its rawest form; if it works,
everything else is bigger versions of the same shape.

## PowerShell commit sequence

Drew runs the following from `C:\dev\project-nexus` after pulling the
agent's work back. The defensive lock cleanup is the same pattern
Sprint 3c documented; we include it here so this handoff stands on
its own.

```powershell
# 1. defensive lock cleanup (idempotent; does nothing if there is no lock)
if (Test-Path .git\index.lock) { Remove-Item .git\index.lock -Force }

# 2. reset any stale staged state from prior session activity
git reset HEAD

# 3. (only if Sprint 3c has not been committed yet)
#    Sprint 3c chunk A: brainstem 503 contract + bind + tests + design doc
git add nodes/brainstem_4070/server.py `
        nodes/brainstem_4070/config.py `
        docker/docker-compose.yml `
        docker/.env.example `
        scripts/setup/refresh-tailscale-bind.ps1 `
        tests/test_cortex_down.py `
        docs/exposure_and_cortex_down.md
git commit -m "sprint-3c chunk A: tailscale-only bind + cortex-down 503 contract + tests"

#    Sprint 3c chunk B: client wiring (CLI + web) for the 503 retry
git add clients/cli/nexus_cli.py clients/web/index.html
git commit -m "sprint-3c chunk B: CLI + web 503 retry handling"

#    Sprint 3c chunk C: that handoff
git add docs/handoffs/HANDOFF_2026-05-17_sprint-3c-exposure.md
git commit -m "sprint-3c chunk C: handoff"

# 4. Sprint 3d: integration suite + manual plan + this handoff
git add tests/integration/
git commit -m "sprint-3d chunk A: integration pytest suite (auth, cortex-down, cross-session memory, metrics)"

git add docs/manual_integration_test_plan.md
git commit -m "sprint-3d chunk B: manual integration test plan"

git add docs/handoffs/HANDOFF_2026-05-17_sprint-3d-integration.md
git commit -m "sprint-3d chunk C: handoff"

# 5. push
git push origin foundation/consolidation
```

If the index lock keeps coming back, the workaround that worked in
Sprint 3c was to close any open VS Code window on the repo first,
since the language server can hold the index. Same applies here.

Sources: this handoff is based on the working state of
`foundation/consolidation` plus the integration suite run captured
above. Source files:
`tests/integration/__init__.py`,
`tests/integration/conftest.py`,
`tests/integration/test_auth_paths.py`,
`tests/integration/test_cortex_down_contract.py`,
`tests/integration/test_session_memory.py`,
`tests/integration/test_metrics_attribution.py`,
`tests/integration/test_live_smoke.py`,
`docs/manual_integration_test_plan.md`.
