# Nexus — Handoff for Claude Code

## Purpose of this doc
You are picking up work on Nexus, a distributed cognitive architecture project. This doc is your onboarding. Read it once, keep it open. Do not skip to code.

## Who you are working with
Drew Mattick. Software developer, CS bachelor's finishing up, heading to a PhD focused on AI. Primary languages Python and C#. Treat him as a peer engineer, not a customer. He iterates fast: draft, react, tighten. Do not over-polish first passes. No em-dashes in prose. Direct, casual-intelligent tone. Dark humor welcome, rare dad joke acceptable.

## Where you are
Repo is at `C:\Users\<username>\Desktop\nexus` on the 4090 box (Windows 11 Pro). Confirm the exact path on your first run. Do not assume contents. Walk the tree before you do anything else.

## Project in one paragraph
Nexus distributes cognitive roles across heterogeneous consumer-grade hardware instead of running a monolithic model. Jetson Nanos act as peripheral sensors. A mid-tier GPU box (RTX 4070 Super) filters and gates incoming signals. A NAS holds long-term memory. A high-end GPU box (RTX 4090) hosts the reasoning model. A future consolidation node handles offline memory maintenance. The architecture is grounded in three working-draft papers the project maintains as a coherent trio: the Nexus architecture paper, a continuity paper on preserving identity across model upgrades, and a paper on containerized intelligence as a deployment philosophy. Read those papers if they appear in the repo. Do not relitigate their framing.

## Hardware reality as of now
- **4090 node:** Windows 11 Pro. Drew's daily driver. Currently runs vLLM serving Qwen3 30B-A3B inside a Docker container. This is the cortex. Do not disrupt the running model without asking.
- **4070 node:** Windows 11 Pro. Currently offline. Was displaced after a basement flood and has not been returned to the network yet. Was previously running the same vLLM-in-Docker pattern (TensorRT-LLM was tried first and scrapped, overhead too high on the 4070 Super).
- **Jetson Nanos:** 2 of them flashed with the Jetson Nano Ubuntu variant. Cases are 3D-printed. Not racked. Not yet on Ethernet. Additional Jetsons exist but are not flashed.
- **NAS:** Does not exist yet. Planned.
- **Cameras and sensors:** Several cameras already installed around the house. Additional camera modules and sensor kits exist for the Jetsons and for future mobile platforms (Project Vector, RC vehicles that will go out and gather data).

## Current goal
Get the Jetson Nanos returning data to the 4070 over Ethernet.

Everything else (NAS, consolidation node, memory schema, full topology, Project Vector) is downstream of this. Do not scope-creep.

## First moves when you start
Context for this flow: Drew recently consolidated multiple scattered sources into this single repo. There is no hidden sacred structure to preserve. Expect duplicates, half-finished attempts at the same thing, and dead code sitting next to live code. Part of your job is to make sense of the mess, not to tiptoe around it. The staging below exists so Drew can see what you are about to do before you do it, not so you do nothing.

1. **Confirm the repo path with Drew.** Do not guess.
2. **Inventory pass — read only, no file moves.** Walk every directory. Produce `inventory.md` at the repo root. For each meaningful item list: what it is, what it appears to do, how confident you are in that assessment, whether it looks live, dead, duplicate, or partial. Flag obvious breakage. Flag probable duplicates grouped together. Flag anything where you genuinely cannot tell what it is.
3. **Propose an organization plan.** Write `reorg_plan.md` at the repo root. Include a short paragraph describing the proposed structure and why, then a table with three columns: current path, proposed path, and action (keep, move, merge, archive, delete). For every `delete` entry, give a one-line reason. Do not execute yet.
4. **Stop and show Drew both files.** He will approve, edit, or redirect.
5. **Execute the approved plan using `git mv` for moves and a dedicated `archive/` directory for anything you would otherwise delete.** Do not hard-delete files on the first pass. Archive preserves recovery; git history preserves lineage. Commit the reorg as its own commit with a clear message so it can be reverted cleanly if needed.
6. **Only after the reorg is committed, start engineering work.** The first real task is the Jetson → 4070 data path.

## Known unknowns you will probably hit
- There may be multiple partial attempts at the same thing in the repo. First run was not optimized and may be scrap-worthy, but do not delete until triage.
- There is no finalized message contract between Jetsons and the 4070. Transport options on the table: MQTT, ZeroMQ, REST, gRPC. No decision yet. Do not pick one unilaterally.
- No canonical Dockerfile exists as a project artifact. If you find Dockerfiles in the repo, treat them as drafts.
- There is no canonical repo layout yet. If you see `edge/`, `brainstem/`, `memory/`, `cortex/`, `consolidation/`, `contracts/`, `infra/`, that structure has been discussed but may not be implemented.
- Network setup is incomplete. Static IPs, VLANs, and managed switching have been discussed but not executed.

## Non-negotiables
- **Biological role mapping is structural, not decorative.** Cortex, thalamus, hippocampus, brainstem, and sleep engine are functional roles mapped to specific hardware tiers. Do not rename them to generic service labels.
- **Identity lives in memory structures, not in model weights.** Never write code that assumes a model swap is an identity reset. The continuity paper governs this.
- **Forgetting is a feature.** Memory is intentionally filtered. Do not write indiscriminate logging-everything layers.
- **The 4070 is the gatekeeper, not secondary compute.** It defines what the system notices. Treat it as load-bearing.
- **Do not collapse Nexus into a monolithic single-host design** under time pressure. If you find yourself about to, stop and ask.

## Working conventions
- Python preferred for LLM, embedding, and vector DB work. C# acceptable for service layers and orchestration where type safety helps.
- Docker is the packaging default. vLLM-in-Docker is the established pattern for model serving.
- When a decision is technically disputed, Drew prefers multi-agent triangulation over a single confident answer. Flag contested calls explicitly and suggest cross-checking with another model rather than forcing a call.
- Do not invent citations, benchmarks, or implementation artifacts. If something does not exist, say it does not exist.

## Files to look for in the repo
If any of these exist, read them before asking Drew for context:
- `README.md` at the repo root
- Any file with "architecture" or "design" in the name
- Existing Dockerfiles or compose files
- Any `.md` file named after a component (`jetson`, `4070`, `cortex`, `memory`, etc.)
- The three Nexus papers if they were committed

## What to hand back on your first session
The inventory file, the reorg plan, and a short list of the two or three most important open questions you encountered. That is the whole session one deliverable. Reorganization and engineering happen on session two, after Drew has reviewed the plan.

## Tone reminder
Drew's style guide in one sentence: write like a smart engineer talking to another smart engineer over coffee, not like a consulting deck. If a sentence sounds like it belongs in a press release, delete it.
