# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Nexus Automation Node is the workflow orchestration layer of **Project Nexus** — a modular, biologically-inspired distributed cognition system. This repo deploys an **n8n** automation engine via Docker, fronted by Traefik reverse proxy and Cloudflare Tunnel for secure external access.

This is an infrastructure-as-code project with no application source code, build steps, or test suites. The primary development artifacts are Docker configuration and n8n workflow JSON files.

## Common Commands

```bash
# Start the full stack (Traefik + Cloudflared + n8n)
docker compose up -d

# Stop all services
docker compose down

# View logs
docker compose logs -f           # all services
docker compose logs -f n8n       # n8n only

# Restart a single service
docker compose restart n8n

# Backup n8n data (workflows + credentials)
docker exec n8n sh -c "tar czf /home/node/.n8n_backup.tar.gz /home/node/.n8n"
docker cp n8n:/home/node/.n8n_backup.tar.gz .

# Restore n8n data
docker cp .n8n_backup.tar.gz n8n:/home/node
docker exec n8n tar xzf /home/node/.n8n_backup.tar.gz -C /
```

## Architecture

Three Docker services on a shared `nexus` bridge network:

- **Traefik v2.11** — Reverse proxy. Routes `n8n.projectnexuscode.org` to the n8n container (port 5678). Config split between static (`traefik/traefik.yml`) and dynamic (`traefik/dynamic/config.yml`) with hot-reload. Docker provider discovers services via labels; `exposedByDefault: false` requires explicit opt-in.
- **Cloudflared** — Cloudflare Tunnel for secure ingress without exposing ports publicly. Token provided via `CLOUDFLARED_TUNNEL_TOKEN` env var.
- **n8n** — The automation engine. Persists data in a named Docker volume (`n8n_data` mounted at `/home/node/.n8n`). Runners enabled for workflow execution.

## Environment & Secrets

All secrets live in `.env` (gitignored). Required variables:
- `CLOUDFLARED_TUNNEL_TOKEN` — Cloudflare tunnel authentication
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` — Google OAuth2 for Gmail/Drive/Sheets/Docs
- `OPENAI_API_KEY` — OpenAI API access (Email workflows + LLM.Council)
- `ANTHROPIC_API_KEY` — Anthropic API access (LLM.Council)
- `GEMINI_API_KEY` — Google Gemini API access (LLM.Council)

n8n credentials are overwritten via `N8N_CREDENTIALS_OVERWRITE_DATA` in docker-compose.yml, defining two Gmail OAuth profiles: `gmail_main` (full Google suite scope) and `gmail_alerts` (Gmail-only scope).

`NEXUS_LABELS` env var defines email categorization labels (urgent, financial, legal, personal, kids, project, junk) used by n8n workflows.

## Key Configuration Details

- Production domain: `n8n.projectnexuscode.org`
- Traefik dashboard: `traefik.projectnexuscode.org`
- Timezone: `US/Central`
- TLS minimum version: 1.2 (enforced in `traefik/dynamic/config.yml`)
- `N8n_BLOCK_ENV_ACCESS_IN_NODE=false` — allows n8n Code nodes to read environment variables
- n8n workflow templates go in the repo root as `.json` files

## n8n MCP Integration

Claude Code connects to the live n8n instance via the **n8n-mcp** server (czlonkowski/n8n-mcp). Config lives in `.mcp.json` (gitignored — contains API key).

**Available MCP tools:**
- `list_workflows` / `get_workflow` / `create_workflow` / `update_workflow` / `delete_workflow` — CRUD operations on live n8n workflows
- `activate_workflow` / `deactivate_workflow` — toggle workflow active state
- `search_nodes` / `get_node_details` — query the built-in database of 544 n8n nodes
- `search_templates` — search 2,700+ workflow templates for patterns and examples

**MCP server location:** `C:\Users\Drama\Desktop\n8n-mcp\`

**API key rotation:** The n8n API key in `.mcp.json` is a JWT with an expiration date. When it expires, generate a new one from n8n Settings > API and update `.mcp.json`.

## Workflow Standard Library

Reusable atomic workflows deployed to n8n as sub-workflows. Each follows the `Domain.Operation` naming convention and a consistent 4-node pattern:

```
Execute Workflow Trigger → Validate Input (Code) → Operation → Format Output (Set/Code)
```

**Registry:** `workflow-registry.json` is the source of truth — maps workflow names to n8n IDs, and defines input/output schemas for each workflow. Both Claude Code (via MCP) and n8n AI Agent nodes read this registry to know what's available.

**Calling a sub-workflow:** Use n8n's "Execute Workflow" node, pass input fields matching the registry's `input` schema, and receive standardized output matching the `output` schema.

### Phase 1 — Email Domain

| Workflow | n8n ID | Description |
|----------|--------|-------------|
| `Email.Send` | `0G0Ka32a3mYhQhOa` | Send email via Gmail |
| `Email.Get` | `GxrpXyYs4TmWtCXQ` | Get single email by message ID |
| `Email.List` | `90vLGzH19vJNqVc1` | List recent emails with optional filters |
| `Email.Search` | `1RQlpK2HU3Cu4qKC` | Search emails with Gmail query syntax |
| `Email.Label` | `oBbkedhulUupMiNU` | Add/remove labels on a message |
| `Email.Reply` | `OMahM1prJ6QecQ2Y` | Reply to an existing email thread |

All Email workflows use the `Gmail account` OAuth2 credential (id: `6IGQz4SKT7kp908J`).

### Phase 2 — LLM Domain

| Workflow | n8n ID | Description |
|----------|--------|-------------|
| `LLM.Council` | `13Bg7qtxJYvsFscJ` | Multi-model deliberation: Claude + Gemini + GPT vote and synthesize |

**LLM.Council pattern:** 26-node, 2-round deliberation. Round 1 fans out to all 3 models in parallel. Round 2 (peer review) fires if any of: non-unanimous vote, confidence variance > 0.3, or peer questions raised. Final output includes `final_answer`, `consensus` (unanimous/majority/split), `vote_tally`, `dissent`, and full `deliberation` log.

**API keys required in `.env`:** `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` — all three must also be in `docker-compose.yml` n8n env block.

**Models used:** `claude-3-5-sonnet-20241022` · `gemini-2.0-flash` · `gpt-4o`

**Cross-node references in R2:** Parse R2 nodes use `$('Agg R1 + R2 Check').first().json` to recover R1 context after HTTP nodes replace item data.

### Adding New Workflows

1. Define the workflow in `workflow-registry.json` with input/output schemas and `n8nId: null`
2. Build the workflow JSON following the 4-node pattern
3. Validate via `validate_workflow` MCP tool
4. Deploy via `n8n_create_workflow` MCP tool
5. Update `n8nId` in the registry with the returned ID

### Future Domains

Calendar, Drive, Sheets, Docs, LLM (Chat/Classify/Summarize/Extract), HTTP (Get/Post).

## Project Nexus Integration Points

This node connects to other Nexus components:
- **Cortex (4090 GPU)** — LLM reasoning engine
- **Brainstem (4070 GPU)** — validation and routing layer
- **NAS Memory Node** — semantic/episodic knowledge store
- **Ollama / TRT-LLM** — local LLM runtimes (HTTP on port 11434)
- **OpenAI API** — external LLM access
