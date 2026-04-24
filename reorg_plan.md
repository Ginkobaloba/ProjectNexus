# Nexus Reorg Plan

Paired with `inventory.md`. Nothing has been moved yet. The goal of this pass is to establish a layout you can build on for the Jetson to 4070 data path without the current mess slowing you down.

## Proposed structure and why

Keep the per-node split that `nodes/` already implies, because it mirrors the biological role mapping and matches how compose builds. Pull `docker/` into an `infra/` tree so it sits next to the other cross-cutting pieces (gitignore rules, future Terraform or Ansible, future network topology docs). Add `contracts/` as the canonical home for the Jetson to 4070 message schema once you pick a transport, because that decision is the first thing the next engineering pass will make and it needs a home before it is made, not after. Keep `papers/` untouched. Move the v0.1 scaffolding that is still zero bytes (`scripts/`, `docs/`) into `archive/` rather than deleting, so git blame still resolves if anything references them.

Proposed top-level after reorg:

```
nexus/
  README.md
  requirements.txt
  .gitignore
  nexus_handoff.md
  inventory.md
  reorg_plan.md
  papers/                      # untouched
  nodes/
    brainstem_4070/            # live
    nas_memory/                # live
    cortex_4090/               # placeholder, will absorb or reference runtime
    jetson_peripherals/        # next target per handoff
    consolidation/             # placeholder (was top-level ./consolidation)
  infra/
    docker/                    # was top-level ./docker
      docker-compose.yml
      brainstem.Dockerfile
      nas.Dockerfile
    cortex-runtime/            # was Nexus-LLM-Runtime-4090 (compose only, no weights)
  contracts/                   # NEW, empty except a stub README
  archive/
    core_mqtt_scaffold/        # ex core/
    agent_mqtt_scaffold/       # ex agent/
    scripts_v01_stubs/         # ex scripts/
    docs_v01_stubs/            # ex docs/
    n8n_backups_duplicates/    # redundant tarballs
    trtllm_compose_legacy/     # old TRT-LLM compose files
automation/                    # OPEN QUESTION, see below. Either submodule, subtree, sibling repo, or folded in.
```

`Nexus-Automation-Node` and `Nexus-LLM-Runtime-4090/models/` need decisions before they get moved or ignored.

## Decisions needed before executing

1. **`Nexus-Automation-Node`.** It is its own GitHub repo with 18+ commits of independent history. Pick one:
   - **a. Sibling repo.** Move the whole folder up one level to `C:\Users\Drama\Desktop\Nexus-Automation-Node`. Leaves both repos clean. Simplest mental model. Loses the implicit "all Nexus stuff lives here" framing.
   - **b. Git subtree.** `git subtree add --prefix=automation ... ` into this repo. Brings the 18 commits in, keeps upstream pullable. Medium complexity.
   - **c. Submodule.** Fastest. Worst ergonomics. Worth avoiding unless you have a strong reason.
   - **d. Flatten / absorb.** Delete inner `.git`, treat the contents as native. Loses the independent history unless you subtree-merge first. Cleanest monorepo outcome.
   My lean is (a) or (b). Not executing until you call it.

2. **`Nexus-LLM-Runtime-4090/models/llama70b/`.** ~140 GB, currently unreferenced by the running cortex (Qwen3 30B-A3B per the handoff). Pick one:
   - Keep on disk but move **outside** the repo to a model cache dir, add a gitignore rule, reference from compose by absolute path.
   - Delete if truly dead.
   Either way it must not end up in git history.

3. **`core/` + `agent/` MQTT scaffolding.** These were a separate architectural approach to node coordination (heartbeat bus) and have no current callers. Pick one:
   - Archive under `archive/core_mqtt_scaffold/` and `archive/agent_mqtt_scaffold/` (my default).
   - Promote to a real `control_plane/` package and rewire as the cluster control bus once the Jetsons come online. This overlaps with the still-unpicked Jetson to 4070 transport decision (MQTT is one of the options on the table). If you want MQTT as the cluster bus, revive; if not, archive.

## Pre-flight (do these before any `git mv`)

These are safety steps, not organizational changes. Do them first.

| # | Action | Reason |
|---|---|---|
| P1 | **Rotate** every secret in `Nexus-Automation-Node/.env`, `Access_Token.txt`, `Google Keys.txt`. | Google OAuth client secret, Gemini, OpenAI, Anthropic, Cloudflare tunnel, n8n API JWT are all sitting on disk in plaintext files. Even with gitignore, rotation is cheaper than assuming they have not leaked. |
| P2 | Extend root `.gitignore` with: `Nexus-LLM-Runtime-4090/models/`, `~$*.docx`, `Google Keys.txt`, `*.tar.gz` (or at least the known n8n backups), `.mcp.json`. | Prevents accidental `git add .` of model weights and secrets. |
| P3 | Delete `papers/nexus_architecture/~$xus_Synthetic_Cognition_Framework.docx`. | Word lockfile from an open or crashed Word session. |
| P4 | Close anything holding `Nexus_Synthetic_Cognition_Framework.docx` open so the lockfile does not come back. | Housekeeping. |

## Reorg table

`current path` is relative to repo root. `action` is `keep`, `move`, `merge`, `archive`, or `delete`. For every `delete` there is a one-line reason.

| Current path | Proposed path | Action | Notes |
|---|---|---|---|
| `readme.md` | `README.md` | move | Rename for consistency (case and convention). |
| `reqirements.txt` | `requirements.txt` | move | Fix spelling and dedupe `fastapi` + `uvicorn`. |
| `.gitignore` | `.gitignore` | keep | Extend per P2. |
| `nexus_handoff.md` | `nexus_handoff.md` | keep | Commit it so future sessions have it. |
| `inventory.md`, `reorg_plan.md` | same | keep | Commit alongside the handoff. |
| `Access_Token.txt` | *(removed from repo after rotation)* | delete | Rotate first. No token ever goes back in this location. |
| `Google Keys.txt` | *(removed from repo after rotation)* | delete | Same. |
| `n8n_workflow.json` (root) | `archive/n8n_workflows_legacy/n8n_workflow_root.json` | archive | Superseded by `Nexus-Automation-Node/exported-*.json`. |
| `papers/` | `papers/` | keep | Untouched per handoff. |
| `papers/nexus_architecture/~$xus_Synthetic_Cognition_Framework.docx` | *(gone)* | delete | Word lockfile, not content. |
| `docker/` | `infra/docker/` | move | Group infra together. |
| `docker/docker-compose.yml` | `infra/docker/docker-compose.yml` | move | Fix `context: ..` to `context: ../..` after move. |
| `docker/brainstem.Dockerfile` | `infra/docker/brainstem.Dockerfile` | move | Same path adjustment. |
| `docker/nas.Dockerfile` | `infra/docker/nas.Dockerfile` | move | Same. |
| `core/` | `archive/core_mqtt_scaffold/` | archive | Orphan heartbeat scaffold, broken pydantic v1 import, fix underscore typo. See decision (3). |
| `agent/` | `archive/agent_mqtt_scaffold/` | archive | Same. |
| `consolidation/` | `nodes/consolidation/` | move | Group all nodes under `nodes/`. Placeholder, still useful as a named slot. |
| `nodes/brainstem_4070/` | `nodes/brainstem_4070/` | keep | Live. Separately fix pydantic v1 `BaseSettings` import in config.py. |
| `nodes/nas_memory/` | `nodes/nas_memory/` | keep | Live. Separately port ChromaDB calls to `PersistentClient`. |
| `nodes/cortex_4090/` | `nodes/cortex_4090/` | keep | Placeholder. Will eventually reference the 4090 runtime compose. |
| `nodes/jetson_peripherals/` | `nodes/jetson_peripherals/` | keep | Next engineering target per handoff. |
| `scripts/` (all zero bytes) | `archive/scripts_v01_stubs/` | archive | Empty stubs from v0.1 bootstrap. |
| `docs/` (all zero bytes) | `archive/docs_v01_stubs/` | archive | Empty stubs from v0.1 bootstrap. |
| `Nexus-LLM-Runtime-4090/compose.yaml` | `infra/cortex-runtime/compose.trtllm.yaml` | move + rename | TRT-LLM compose, stale vs current vLLM setup. Rename so future-you knows this is the legacy path. |
| `Nexus-LLM-Runtime-4090/compose.txt` | `archive/trtllm_compose_legacy/compose.txt` | archive | Dupe of compose.yaml. |
| `Nexus-LLM-Runtime-4090/models/` | *(moved outside the repo)* | delete | See decision (2). Must not enter git history. Gitignore covers the path. |
| `Nexus-LLM-Runtime-4090/` (parent shell) | *(disappears once emptied)* | delete | Empty shell after moves. |
| `Nexus-Automation-Node/` | **depends on decision (1)** | — | Sibling repo, subtree, submodule, or flatten. |
| `Nexus-Automation-Node/.n8n_backup.tar.gz` | *(one copy kept in the chosen location)* | merge | Keep one of the three; move the other two to `archive/n8n_backups_duplicates/`. |
| `Nexus-Automation-Node/n8n_backup_pre_2x.tar.gz` | `archive/n8n_backups_duplicates/` | archive | Dupe. |
| `Nexus-Automation-Node/n8n_backup_pre_2x_20260218.tar.gz` | `archive/n8n_backups_duplicates/` | archive | Dupe. |
| `Nexus-Automation-Node/n8n_workflow.json` | resolve during decision (1) | — | Loose workflow, purpose unclear. Needs a quick eyeball. |
| `Nexus-Automation-Node/...` (rest) | resolve during decision (1) | — | The whole tree ships together. |
| *(new)* `contracts/README.md` | `contracts/README.md` | create | Stub that documents: this is where the Jetson to 4070 message schema lands once transport is picked. |

## Execution order once approved

1. Pre-flight (P1–P4).
2. Commit `nexus_handoff.md`, `inventory.md`, `reorg_plan.md` as-is. One commit, so the plan itself is on the record before anything moves.
3. Resolve decision (1) about `Nexus-Automation-Node`. Execute.
4. Resolve decision (2) about the Llama-70B weights. Execute (move outside repo + gitignore).
5. Fix typos and renames that are pure no-ops: `readme.md` → `README.md`, `reqirements.txt` → `requirements.txt`, `_init_.py` → `__init__.py` wherever applicable (note: only in the files that are being archived, so may not matter).
6. `git mv` the directory moves per the table.
7. Adjust `infra/docker/docker-compose.yml` context paths.
8. Create `archive/` entries.
9. Create empty `contracts/README.md` stub.
10. Commit the reorg as one commit with a clear message: `reorg: consolidate node layout, archive v0.1 stubs and MQTT scaffold, centralize infra/`.
11. Stop. Drew reviews. **Then** engineering work begins on the Jetson to 4070 path.

Nothing here touches live model serving. The running vLLM-in-Docker on the 4090 is not affected by any of these moves. The n8n stack in `Nexus-Automation-Node` stays running regardless of which of the four options you pick for it, because it has its own compose and its own docker volume.
