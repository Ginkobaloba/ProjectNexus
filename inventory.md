# Nexus Repo Inventory

Read-only triage pass. No files moved. Confidence calls are my best read, not ground truth.

Repo root confirmed: `C:\Users\Drama\Desktop\Nexus`. Matches the handoff modulo case (doc says lowercase `nexus`, filesystem says `Nexus`, Windows does not care).

Git state at walk time:
- Outer repo remote: `github.com/ginkobaloba/ProjectNexus`
- Four commits on `main`, most recent `feat(nas): scaffold NAS node structure...`
- Untracked at root: `Google Keys.txt`, `Nexus-Automation-Node/`, `Nexus-LLM-Runtime-4090/`, `n8n_workflow.json`, `nexus_handoff.md`, `papers/nexus_architecture/~$xus_Synthetic_Cognition_Framework.docx`

---

## Top-level layout

| Path | What it is | Status | Confidence | Notes |
|---|---|---|---|---|
| `readme.md` | Project overview, node roles, roadmap | live | high | Current and coherent with the three-paper framing. Keep. |
| `nexus_handoff.md` | Your handoff doc (untracked) | live | high | Not yet committed. |
| `reqirements.txt` | Python deps list (typo) | live-ish, broken | high | Misspelled filename. Duplicates `fastapi` and both plain + `uvicorn[standard]`. Needs dedup and rename to `requirements.txt`. |
| `.gitignore` | Standard ignores + secrets | live | high | Covers `Access_Token.txt` but not `Google Keys.txt`, not `Nexus-LLM-Runtime-4090/models/`, not the Word lockfile. |
| `Access_Token.txt` | Credential | live, **SECRET** | high | Already gitignored. Rotate and move to a secret store outside the repo. |
| `Google Keys.txt` | Credential (untracked) | live, **SECRET** | high | Not yet gitignored. Rotate before anything else touches git. |
| `n8n_workflow.json` | Old n8n workflow export at root | duplicate | high | A newer / fuller copy lives in `Nexus-Automation-Node/exported-*.json`. This one looks scrappy. Archive or delete. |
| `.vscode/`, `.mypy_cache/` | Editor and tool caches | tooling | high | Already gitignored. Fine. |

---

## `core/` — older heartbeat scaffold

MQTT-based agent registry, pre-dates the `nodes/` layout. Not wired into anything current. Live code, but architecturally orphaned.

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `core/main.py` | MQTT subscriber, prints active agents every 15s | orphan | high | Works in isolation, not called by anything else in the repo. |
| `core/registry.py` | In-memory `AgentRegistry` with TTL | orphan | high | Fine code, just unused. |
| `core/config.py` | `BaseSettings` for MQTT broker + topics | broken on pydantic v2 | high | Imports `BaseSettings` from `pydantic`, which moved to `pydantic-settings` in v2. |
| `core/models.py` | `Heartbeat`, `AgentCommand` | orphan | high | |
| `core/logging_config.py` | stdlib logger helper | orphan | high | |
| `core/_init_.py` | **Typo** | broken | high | Single underscores. Python does not treat this as a package marker, so `from core import ...` would fail. Should be `__init__.py`. Same bug exists in `agent/`. |

**Call:** `core/` looks like a first-pass service mesh attempt before the FastAPI-per-node design took over. Decide whether to port it forward as the cluster's control plane or archive it.

---

## `agent/` — paired heartbeat client

Companion to `core/`. Publishes MQTT heartbeats on an interval. Same orphan status.

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `agent/agent.py` | `NexusAgent` MQTT heartbeat loop | orphan | high | |
| `agent/config.py` | `AgentSettings` via `BaseSettings` | broken on pydantic v2 | high | Same v1 import. |
| `agent/_init_.py` | **Typo** | broken | high | Single underscores again. |

---

## `nodes/` — current architectural surface

Canonical per-node layout. Two nodes have real code, two are placeholder shells.

### `nodes/brainstem_4070/` — live

FastAPI service on port 5001. Embeds with `sentence-transformers` (default `BAAI/bge-large-en-v1.5`), holds STM in a ring buffer, basic validation filter.

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `server.py` | FastAPI app: `/health`, `/embed`, `/stm/write` | live | high | Clean. No endpoint yet to push to the NAS. |
| `embed.py` | SentenceTransformer wrapper | live | high | |
| `stm_buffer.py` | `STMBuffer` deque | live | high | |
| `filter.py` | `basic_validation` placeholder | live-stub | high | Explicitly labeled as a stub. |
| `config.py` | `BaseSettings`, env prefix `BRAINSTEM_` | broken on pydantic v2 | high | `from pydantic import BaseSettings` again. |
| `__init__.py` | Correct double-underscore here | live | high | |

### `nodes/nas_memory/` — live

FastAPI service on port 5002. ChromaDB-backed semantic store + JSONL episodic log.

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `server.py` | `/health`, `/semantic/write`, `/semantic/search`, `/episodic/write`, `/episodic/list` | live | high | |
| `semantic_store.py` | ChromaDB wrapper | **likely broken** | medium | Uses `chroma_db_impl="duckdb+parquet"` and `client.persist()`, both removed in current `chromadb`. Needs port to `PersistentClient`. |
| `episodic_store.py` | JSONL append log | live | high | |
| `schemas.py` | Pydantic models for NAS API | live | high | |
| `config.py` | `BaseSettings`, hardcoded `/data/nas` paths | broken on pydantic v2, Linux-pathed | high | `/data/nas` only makes sense inside the Docker container. Fine when containerized, surprising if anyone runs it host-side on Windows. |

### `nodes/cortex_4090/` — empty

Only `__init__.py`. Placeholder. The 4090 is actually running vLLM-in-Docker today, separately (see `Nexus-LLM-Runtime-4090/`). This directory does not yet contain that runtime.

### `nodes/jetson_peripherals/` — empty

Only `__init__.py`. Placeholder. This is where the Jetson-to-4070 path work needs to land per the handoff's current goal.

---

## `docker/` — pairs with `nodes/`

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `docker/docker-compose.yml` | Builds brainstem + nas services, bridge network | live | high | Canonical compose for the brainstem-plus-NAS pair. |
| `docker/brainstem.Dockerfile` | Python 3.11 slim + sentence-transformers | live | high | |
| `docker/nas.Dockerfile` | Not read in this pass, but referenced by compose | live (assumed) | medium | |

---

## `Nexus-LLM-Runtime-4090/` — the live cortex runtime, untracked, nested git inside

This is the 4090's model-serving setup. Lives in the repo tree but is untracked at the outer level.

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `compose.yaml` | TensorRT-LLM Docker compose, port 8000 | **stale vs reality** | high | Handoff says TRT-LLM was tried and scrapped, current stack is vLLM serving Qwen3 30B-A3B. This file does not reflect that. |
| `compose.txt` | Same thing as `compose.yaml` with a different volume path | duplicate | high | Two near-identical TRT-LLM composes. Pick one. |
| `models/llama70b/` | **~140 GB** of Llama-70B safetensors with its own `.git` (HF LFS) | heavy, untracked | high | Not currently in the Nexus commit graph, but there is nothing stopping a `git add .` from committing it. Needs a gitignore rule immediately. Also: handoff says the current cortex is Qwen3 30B-A3B, not Llama-70B, so this model may be dead weight. |
| `models/llama70b-Instruct-FP8/` | Empty | placeholder | high | |

---

## `Nexus-Automation-Node/` — separate GitHub repo nested inside, untracked

This is its own repo (`github.com/Ginkobaloba/Nexus-Automation-Node`, 18+ commits, its own `main`). The outer Nexus repo sees it as one untracked directory. This is the live n8n automation node: Traefik plus Cloudflared plus n8n, with a workflow registry, `LLM.Council` multi-model deliberation, and a stack of exported workflows. It is production-shaped. It is also where the real secrets live.

| Path | What | Status | Conf. | Notes |
|---|---|---|---|---|
| `.git/` | Separate repository | live | high | See the structural question below. |
| `.env` | **SECRETS** | live, leaking-risk | high | Contains live Google OAuth client secret, Gemini key, OpenAI key, Anthropic key, Cloudflare tunnel token, n8n API JWT. Already gitignored inside its own repo. Outside the repo it is still a file sitting on disk. |
| `.mcp.json` | Claude Code MCP config, API key | live | high | Gitignored. |
| `CLAUDE.md` | Well-written guide for this node | live | high | Matches current stack, current workflows, current domains. Keep. |
| `README.md` | Broader prose; partially stale | mostly live | medium | README still references generic TRT-LLM/Ollama endpoints; CLAUDE.md is tighter. |
| `docker-compose.yml` | Traefik + Cloudflared + n8n | live | high | Production. |
| `config.yaml` | LiteLLM model routing | live | high | |
| `workflow-registry.json` | 100K of workflow metadata | live | high | Source of truth for n8n workflows. |
| `exported-*.json` | Six exported n8n workflows (Builder, Orchestrator, Council, Tests) | live | high | |
| `n8n_backup*.tar.gz` x3 | 8.3 MB each, three copies of the same backup | duplicate | high | All timestamped Feb 18. Keep one, drop two. |
| `n8n_workflow.json` | Small orphan workflow | unclear | low | Different from the exported workflows. Unsure why it is loose. |
| `scripts/` | PowerShell activation / test scripts, one `setup-cortex-llm.sh`, one `cortex-llm.service` | live | high | Supporting tooling for the n8n stack. |
| `docs/` | Four meaty design docs (builder, calendar, cortex, prompts) | live | high | Real reference material. Keep. |
| `traefik/` | Traefik static + dynamic config | live | high | |
| `test-council.ps1` | Test script at root | live | high | |
| `.claude/settings.local.json` | Claude Code permissions | machine-specific | high | Gitignored inside the nested repo. |

**This is the one that really matters for the reorg.** Either we leave it as a sibling repo outside the Nexus tree, pull it in as a submodule/subtree, or flatten it into the monorepo. Not my call to pick.

---

## `consolidation/` — empty stub

`__init__.py` only. Per the handoff, the consolidation / sleep engine is downstream of the Jetson work. Placeholder.

---

## `docs/` — empty stubs

All four files (`api_spec.md`, `architecture.md`, `memory_system.md`, `node_details.md`) are zero bytes. Scaffolding from the v0.1 bootstrap commit. The real docs are in `Nexus-Automation-Node/docs/` and in `papers/`.

---

## `scripts/` — empty stubs

All three files (`benchmark_inference.py`, `start_all.py`, `test_memory.py`) are zero bytes. Same v0.1 scaffolding. No actual logic.

---

## `papers/` — real content, leave alone

| Path | Size | Status |
|---|---|---|
| `papers/nexus_architecture/Nexus_Synthetic_Cognition_Framework.docx` | 29 KB | live |
| `papers/persistence_of_self/Nexus_Self_Continuity_in_Recursive_EI_Systems.docx` | 30 KB | live |
| `papers/containerized_intelligence/mattick-containerized-intelligence-propagation-2025.docx` | 26 KB | live |
| `papers/nexus_architecture/~$xus_Synthetic_Cognition_Framework.docx` | 162 B | junk | Word lockfile, you have the doc open or crashed with it open. Gitignore `~$*.docx` and delete. |

Do not touch the papers per the handoff.

---

## Duplicates grouped

1. **Three n8n backups, one day, identical size:** `Nexus-Automation-Node/.n8n_backup.tar.gz`, `n8n_backup_pre_2x.tar.gz`, `n8n_backup_pre_2x_20260218.tar.gz`.
2. **Two TRT-LLM composes:** `Nexus-LLM-Runtime-4090/compose.yaml` and `compose.txt`.
3. **Two heartbeat-era configs with same broken pydantic v1 import:** `core/config.py`, `agent/config.py`, plus the same pattern in `nodes/brainstem_4070/config.py` and `nodes/nas_memory/config.py`.
4. **Two "here is a loose n8n workflow json" files:** root `n8n_workflow.json`, `Nexus-Automation-Node/n8n_workflow.json`.
5. **Orphan MQTT pattern vs live FastAPI pattern:** `core/` + `agent/` never connect to `nodes/brainstem_4070` or `nodes/nas_memory`. Two different approaches to "how nodes talk", neither wired to the other.

## Breakage flags

- Pydantic v1 `BaseSettings` import in four files. Will fail against the pinned `pydantic-settings` in `reqirements.txt` unless `pydantic<2` is installed, which contradicts `pydantic-settings` existing.
- ChromaDB `duckdb+parquet` impl and `client.persist()` calls. Current `chromadb` uses `PersistentClient` and auto-persists.
- `core/_init_.py` and `agent/_init_.py` are not valid Python package markers. Imports from those packages will not work.
- `reqirements.txt` spelling.
- No gitignore rule for `Nexus-LLM-Runtime-4090/models/**`, and no rule for `~$*.docx`, and no rule for `Google Keys.txt` (only `Access_Token.txt` is explicit).

## Things I genuinely cannot tell

- Whether `core/` + `agent/` MQTT scaffolding is meant to come back as the cluster control plane once the Jetsons are talking, or whether it got abandoned in favor of per-node FastAPI and should be archived.
- Whether `Nexus-LLM-Runtime-4090/models/llama70b/` is dead weight (Llama-70B downloaded, never served, replaced by Qwen3) or a kept-as-backup alternative weight set.
- Whether `Nexus-Automation-Node` is intended to be part of this repo long-term, or whether it is a sibling service that just happens to have been dropped into the Desktop\Nexus tree during consolidation.
