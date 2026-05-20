# Project Nexus — Cortex Design Document

**Status:** Draft v1.0
**Date:** 2026-02-18
**Scope:** Nexus.Orchestrator, Nexus.Builder, Cortex LLM setup, registry extensions, IoT ingestion, memory architecture

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Hardware Architecture](#2-hardware-architecture)
3. [Cortex LLM Setup](#3-cortex-llm-setup)
4. [Registry Schema Extensions](#4-registry-schema-extensions)
5. [Nexus.Orchestrator](#5-nexusorchestrator)
6. [Nexus.Builder](#6-nexusbuilder)
7. [IoT Ingestion Layer](#7-iot-ingestion-layer)
8. [Memory Architecture (NAS)](#8-memory-architecture-nas)
9. [Error Handling Philosophy](#9-error-handling-philosophy)
10. [Security & Guardrails](#10-security--guardrails)
11. [Self-Improvement Loop](#11-self-improvement-loop)
12. [Build Order](#12-build-order)

---

## 1. System Overview

Project Nexus is a modular, biologically-inspired distributed cognition system. This node
(Nexus-Automation-Node) is the workflow orchestration layer — the hands of the system.
The Cortex is its reasoning core.

The central thesis of this design: **the system should be able to extend itself.** When asked
to perform a task for which no workflow exists, the Cortex designs and deploys one, validates
it, and adds it to the permanent library. Over time the library grows and the system becomes
faster and more capable without human intervention.

### Core Loop

```
Request (human / agent / IoT device)
    │
    ▼
Nexus.Orchestrator
    │
    ├── Registry match found ──────────────────► Execute workflow ──► Return result
    │
    └── No match ──► Nexus.Builder
                          │
                          ├── Modify existing workflow
                          ├── Compose from templates
                          └── Generate from scratch
                                    │
                                    ▼
                              Validate → Deploy → Register → Execute ──► Return result
```

---

## 2. Hardware Architecture

### Node Map

| Node | Role | IP | GPU | VRAM | OS |
|------|------|----|-----|------|----|
| **Cortex** | Reasoning engine, n8n host | 192.168.1.140 | RTX 4090 | 24 GB | Windows 11 Pro |
| **Brainstem** | Validation, classification, routing LLM | 192.168.1.251 | RTX 4070 Super | 12 GB | TBD |
| **NAS Memory Node** | Episodic + semantic storage | TBD | — | — | TBD |
| **Jetson Nano(s)** | IoT preprocessing, sensor ingestion | TBD | Nano GPU | 4 GB | Linux |

### Services Per Node

**Cortex (192.168.1.140)**
- n8n 2.8.3 (Docker, port 5678, public via Cloudflare Tunnel)
- Traefik v2.11 (reverse proxy)
- Cloudflared (secure ingress)
- vLLM — Qwen2.5-Coder-32B-Instruct-AWQ (port 8001) ← *to be deployed*

**Brainstem (192.168.1.251)**
- vLLM — Qwen3-4B-noFP (port 8000) — classification and lightweight reasoning

**NAS Memory Node** ← *future*
- Vector store (Qdrant or Weaviate)
- Episodic log store (structured JSON or SQLite)
- Semantic index for workflow registry embeddings

**Jetson Nano(s)** ← *future*
- Edge preprocessing (sensor fusion, image classification, audio)
- Compressed event emission to Nexus ingestion webhook

### Network Topology

All nodes share the `192.168.1.x` LAN. n8n reaches Brainstem via HTTP on the LAN —
no auth required (trusted network). Cortex vLLM similarly accessible on LAN.
External access routes exclusively through Cloudflare Tunnel.

---

## 3. Cortex LLM Setup

### Model Selection

**Model:** `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`

Rationale:
- 32B parameters, AWQ 4-bit quantization → ~18–20 GB VRAM, fits the 4090's 24 GB
- Coder variant is purpose-built for structured JSON output and code generation — exactly
  what Nexus.Builder needs when generating n8n workflow JSON
- Strong general reasoning for the Orchestrator's routing and intent parsing steps
- AWQ quantization preserves more accuracy than GPTQ at the same bit width

**Why not TensorRT-LLM:**
TRT-LLM's fixed VRAM overhead (3–5 GB for compilation buffers and CUDA workspace) is
acceptable on 24 GB but the setup complexity is high — model weight conversion, Triton
Inference Server config, engine versioning. vLLM is already proven on the Brainstem,
exposes an identical OpenAI-compatible API, and delivers sufficient throughput for
orchestration workloads (which are not high-concurrency). Migration to TRT-LLM later
is a pure performance upgrade with zero downstream API changes.

**Why not NeMo:**
NeMo Framework is a training and fine-tuning toolkit — wrong layer entirely. NeMo
Guardrails (a separate product) is potentially useful later for constraining Orchestrator
behavior, but is not an inference server.

### Deployment

```yaml
# docker-compose addition on Cortex — to be appended to existing docker-compose.yml
cortex-llm:
  image: vllm/vllm-openai:latest
  runtime: nvidia
  environment:
    - NVIDIA_VISIBLE_DEVICES=all
  volumes:
    - huggingface_cache:/root/.cache/huggingface
  command: >
    --model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ
    --quantization awq
    --port 8001
    --max-model-len 8192
    --gpu-memory-utilization 0.90
    --served-model-name cortex
  ports:
    - "8001:8001"
  networks:
    - nexus
```

`--max-model-len 8192`: Conservative starting point. The Orchestrator's prompts include
the registry (currently ~4 KB) plus the request — 8192 tokens is ample. Increase if
Builder prompts with large workflow examples need more headroom.

`--gpu-memory-utilization 0.90`: Leaves ~2.4 GB for CUDA overhead and OS.

**Environment variable across n8n:**
`CORTEX_LLM_URL=http://192.168.1.140:8001`
`BRAINSTEM_LLM_URL=http://192.168.1.251:8000`

Both added to the n8n env block in `docker-compose.yml` so Code nodes can reference them
via `$env.CORTEX_LLM_URL`.

---

## 4. Registry Schema Extensions

The current `workflow-registry.json` needs additional fields to support Orchestrator
routing, Builder duplicate detection, and self-improvement tracking.

### Fields to Add Per Workflow

```jsonc
{
  "Email.Send": {
    // — existing fields unchanged —
    "n8nId": "0G0Ka32a3mYhQhOa",
    "description": "Send an email via Gmail",       // keep: brief, human-readable
    "input": { ... },
    "output": { ... },
    "tags": ["email", "gmail", "send"],

    // — new fields —
    "semanticDescription": "Composes and sends an outbound email message to one or more
      recipients using the Gmail API. Accepts plain text or HTML body. Use this when the
      goal is to deliver a new message. Do NOT use for replies (use Email.Reply instead).",

    "status": "active",
    // "active"     — deployed, activated, verified working
    // "inactive"   — deployed but not activated (cannot be called as sub-workflow)
    // "unverified" — deployed by Builder, not yet confirmed by a successful execution
    // "deprecated" — superseded by a newer workflow, preserved for reference

    "version": 1,
    // Incremented each time the workflow is modified and redeployed

    "createdBy": "human",
    // "human"      — built by a developer directly
    // "builder"    — generated by Nexus.Builder
    // "claude-code" — built via Claude Code MCP session

    "nodeHash": "a3f8c2...",
    // SHA-256 of the canonical node list (sorted by type+name). Used by Builder to
    // detect structural duplicates before registering a new workflow.

    "usageCount": 0,
    // Incremented on each successful execution call. Used for prioritization in
    // semantic search and to identify unused workflows for cleanup.

    "lastVerified": "2026-02-18T00:00:00Z",
    // ISO timestamp of last confirmed successful execution.

    "dependsOn": [],
    // Names of other standard library workflows this workflow calls as sub-workflows.
    // Builder uses this to detect missing dependencies before deployment.

    "allowedCallers": "any"
    // "any"         — callable by anyone (Orchestrator, agents, test harnesses)
    // "internal"    — callable only from within n8n (not via MCP/webhook)
    // "human-only"  — requires human-initiated trigger, not Orchestrator-callable
  }
}
```

### Registry-Level Metadata

```jsonc
{
  "version": "2.0",           // bump from 1.0 to mark schema change
  "schemaVersion": 2,
  "lastUpdated": "2026-02-18T00:00:00Z",
  "nodeWhitelist": [          // Builder may only use nodes on this list
    "n8n-nodes-base.executeWorkflowTrigger",
    "n8n-nodes-base.set",
    "n8n-nodes-base.code",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.gmail",
    "n8n-nodes-base.merge",
    "n8n-nodes-base.if",
    "n8n-nodes-base.switch",
    "n8n-nodes-base.noOp"
  ],
  "workflows": { ... }
}
```

---

## 5. Nexus.Orchestrator

### Purpose

Receives a natural language request, determines which workflow handles it, extracts the
required parameters, and executes. If no workflow exists, delegates to Nexus.Builder.

### Input / Output Schema

**Input:**
```jsonc
{
  "request":  "string (required) — natural language description of what to do",
  "context":  "object (optional) — prior conversation turns, session state",
  "source":   "string (optional) — 'human' | 'agent' | 'iot' | 'scheduled'",
  "confirm_dangerous": "boolean (optional, default false) — pre-approved confirmation for destructive actions"
}
```

**Output:**
```jsonc
{
  "status":        "success | clarification_needed | error | awaiting_confirmation",
  "result":        "object — the output from the executed workflow (null if not executed)",
  "workflow_used": "string — name of the workflow that was called",
  "was_built":     "boolean — true if Nexus.Builder was invoked",
  "message":       "string — human-readable summary or clarifying question",
  "needs_input":   "array — list of missing parameters if status is clarification_needed",
  "error":         "object — structured error if status is error"
}
```

### Routing Algorithm

The Orchestrator runs a tiered matching process. Each tier is attempted in order and
short-circuits as soon as a confident match is found.

---

**Tier 0 — Intent Parse (always runs)**

Prompt the Cortex LLM with:
- The incoming request
- A brief description of what the Orchestrator is and what kinds of things it can do

Extract a structured intent object:
```jsonc
{
  "action_verb":   "send | get | list | search | label | reply | classify | ask | create | ...",
  "domain":        "email | calendar | llm | file | http | memory | ...",
  "parameters":    { "extracted_key": "extracted_value" },
  "ambiguities":   ["what is missing or unclear"],
  "is_dangerous":  false,      // e.g., delete, bulk send, data export
  "is_compound":   false,      // e.g., "search email AND reply to all from John"
  "confidence":    0.92
}
```

If `is_compound: true` → decompose into sequential sub-requests, run each through the
Orchestrator recursively (max depth: 3 levels to prevent runaway chaining).

If `confidence < 0.5` → return `status: clarification_needed` immediately. Do not proceed
with low-confidence routing.

---

**Tier 1 — Exact Name Match**

If the parsed `domain` + `action_verb` directly map to a registry workflow name
(e.g., domain=email, action_verb=send → Email.Send), and the workflow is `status: active`,
this is a confident match. Skip Tiers 2–3.

---

**Tier 2 — Tag / Domain Filter + LLM Semantic Ranking**

Filter the registry to workflows whose tags include the parsed domain.
Prompt the Cortex LLM with:
- The intent object from Tier 0
- The `semanticDescription` of each filtered workflow (not the full JSON — just descriptions)

Ask: *"Which of these workflows best handles this request? If none are a strong match,
say NONE. If multiple are plausible, rank them."*

Output: ranked list with confidence scores.

Accept the top match if confidence ≥ 0.75. If top confidence < 0.75, fall through to Tier 3.

---

**Tier 3 — Close Match Detection (for Builder pre-population)**

If Tier 2 found a workflow with confidence 0.40–0.74 — "close but not quite" — pass it to
Nexus.Builder as a `similarity_match`. The Builder will modify it rather than build from
scratch.

If Tier 2 found nothing above 0.40 — pass to Nexus.Builder with no similarity hint.

---

**Parameter Extraction & Validation**

Once a target workflow is identified:
1. Cross-reference the intent's `parameters` against the workflow's `input` schema
2. For each required field: if missing, add to `needs_input` list
3. For each optional field: include if present, omit if absent
4. If `needs_input` is non-empty → return `status: clarification_needed` with the list

Do not execute with missing required parameters. Do not guess at required params.

---

**Dangerous Action Gate**

If `is_dangerous: true` in the intent object AND `confirm_dangerous: false` in the input:
- Return `status: awaiting_confirmation` with a plain-English description of the action
- Do not execute
- Do not build
- The caller must re-submit with `confirm_dangerous: true`

Dangerous actions include: any bulk operation, any delete, any operation sending external
communications without a template, any HTTP Request to an external URL created by the Builder.

---

**Execution**

Call the matched workflow via n8n Execute Workflow (sub-workflow call pattern).
Capture the output. Format it according to the Orchestrator's output schema.
On success: increment the workflow's `usageCount` and update `lastVerified` in the registry.
On failure: do not increment counts. See [Section 9](#9-error-handling-philosophy).

---

### Edge Cases

| Scenario | Handling |
|----------|----------|
| Two workflows match with equal confidence | Present both options to caller as `clarification_needed` |
| Request is purely conversational ("how many emails did I get?") | Route to Email.List/Search and format result as prose |
| Request references a person or entity not in parameters | Extract from context if available; else ask |
| Orchestrator called recursively for a compound action | Max depth 3; if exceeded, return error with decomposed sub-results so far |
| Workflow in registry but deleted from n8n | First call attempt fails → mark as `status: inactive` in registry, route to Builder to recreate |
| Registry file missing or corrupt | Fall back to empty registry (no workflows known), alert via Email.Send to admin, continue |
| Cortex LLM unreachable | Fall back to Brainstem LLM for Tier 1 routing only; escalate to human for anything requiring Builder |
| Request is in a language other than English | Translate to English in Tier 0 intent parse, proceed normally |

---

## 6. Nexus.Builder

### Purpose

Creates new n8n workflows on demand. Called by the Orchestrator when no matching workflow
exists. Outputs the created workflow's registry entry.

### Input Schema

```jsonc
{
  "description":      "string — what the workflow should do (from intent parse)",
  "domain":           "string — email | calendar | llm | http | memory | ...",
  "required_inputs":  "object — input schema the workflow must accept",
  "expected_outputs": "object — output schema the workflow should produce",
  "similarity_match": {        // optional — included when Tier 3 found a close match
    "name":    "Email.Search",
    "n8nId":   "1RQlpK2HU3Cu4qKC",
    "json":    { ... }         // full workflow JSON fetched from n8n API
  }
}
```

### Build Strategy Selection

```
similarity_match provided?
    YES → Strategy: MODIFY
    NO  → Domain has templates in nodeWhitelist?
              YES → Strategy: COMPOSE
              NO  → Strategy: GENERATE
```

---

**Strategy: MODIFY**

Fetch the existing workflow JSON (already included in `similarity_match.json`).
Prompt Cortex with:
- The existing JSON
- A precise diff description: *"Change X to Y, add node Z between A and B, remove node C"*
- The required_inputs and expected_outputs the new version must satisfy
- The verified node spec list from MEMORY.md (to prevent hallucinated node configs)

The LLM produces a modified JSON. It must:
- Preserve the 4-node standard library pattern (Trigger → Validate → Operation → Format)
- Change the workflow name to reflect its new function
- Not reference any nodes not on the `nodeWhitelist`

The resulting workflow is treated as a new workflow (new n8n ID, new registry entry).
The source workflow it was derived from is noted in the new entry's `semanticDescription`.

---

**Strategy: COMPOSE**

The domain has verified node templates. Prompt Cortex with:
- A set of "atomic node blocks" (pre-written, validated JSON snippets for each whitelisted node)
- The 4-node scaffold pattern
- The required_inputs and expected_outputs

The LLM assembles the blocks into a valid workflow JSON. Because it's composing from
pre-validated templates, the failure rate is lower than full generation.

---

**Strategy: GENERATE**

No template or similar workflow available. Prompt Cortex with:
- A detailed system prompt including:
  - The complete n8n workflow JSON schema
  - 2–3 real working examples from the standard library (as JSON)
  - The verified node specs for every whitelisted node type
  - The 4-node standard library pattern
  - The required_inputs and expected_outputs
- The task description

For GENERATE, if the Cortex fails validation 3 times, escalate to **LLM.Council** for the
design step. Council's multi-model consensus is more reliable for complex novel structures.
Reset the validation counter and attempt 3 more times with the Council-generated JSON.

---

### Validation Loop

```
Attempt 1..3 (Cortex LLM):
    Generate / Modify / Compose workflow JSON
        ↓
    Step A: JSON parse check
        - If not valid JSON: attempt repairJson() (escape unescaped control chars, fix trailing commas)
        - If still invalid: increment attempt, feedback "output was not valid JSON: <error>"
        ↓
    Step B: Node whitelist check
        - Scan all nodes for `type` field
        - Any type not in nodeWhitelist → reject, feedback "node type X is not allowed"
        ↓
    Step C: Credential check
        - Any credentialId in nodes must exist in the known credentials map
        - Substitute with correct credential if wrong ID used for a known credential name
        ↓
    Step D: Dependency check
        - Any Execute Workflow nodes: confirm referenced workflow exists in registry
        - If missing: recursively invoke Builder for the dependency (depth limit: 2)
        ↓
    Step E: n8n API validation
        - POST to /api/v1/workflows/validate (or use validate_workflow MCP tool)
        - Parse structured errors from response
        - Feed specific errors back into next attempt prompt
        ↓
    All checks pass → proceed to deployment

Attempt 4+ (LLM.Council, GENERATE strategy only):
    Reset counter, submit to LLM.Council with full context
    3 more attempts with Council-generated JSON
    If still failing → ESCALATE (see below)
```

**Escalation:** After all retries exhausted, return a structured error to the Orchestrator
containing: what was attempted, which validation step failed, the last invalid JSON (for human
debugging), and a suggested manual approach. Do not deploy a broken workflow.

---

### Deployment

1. `POST /api/v1/workflows` — creates workflow in n8n (inactive by default)
2. `POST /api/v1/workflows/{id}/activate` — activates it (required for sub-workflow calls)
3. Verify activation: `GET /api/v1/workflows/{id}` → confirm `active: true`

---

### Registry Update

**Immediately after deployment (before execution):**
```jsonc
// Write to workflow-registry.json on disk
{
  "NewWorkflow.Name": {
    "n8nId": "<returned ID>",
    "description": "<brief description>",
    "semanticDescription": "<rich description for routing>",
    "input": { ... },
    "output": { ... },
    "tags": [ ... ],
    "status": "unverified",    // not "active" yet — execution hasn't been confirmed
    "version": 1,
    "createdBy": "builder",
    "nodeHash": "<computed>",
    "usageCount": 0,
    "lastVerified": null,
    "dependsOn": [ ... ],
    "allowedCallers": "any"
  }
}
```

**Also write to n8n workflow static data** (key: `registry_cache`) as a secondary backup
in case the file on disk is unavailable.

**After first successful execution:**
- Update `status` from `"unverified"` to `"active"`
- Set `lastVerified` to current timestamp
- Queue git commit: staged changes to `workflow-registry.json`

The git commit is not automatic — it is queued as a notification to the human operator
(or triggered by a `Nexus.GitSync` workflow, to be built later). A workflow that has never
successfully executed does not get committed to the repository.

---

### Duplicate Detection

Before registering a new workflow, compute its `nodeHash`:
- Extract all nodes from the JSON
- Sort by `type` + `name`, stringify, SHA-256
- Compare against every existing `nodeHash` in the registry

If a match is found: the new workflow is structurally identical to an existing one.
Options (decided by confidence):
- If names differ but purpose is the same → reject new, return the existing workflow to caller
- If purposes differ but structure matches → log warning, allow registration with a note in `semanticDescription`

---

### Edge Cases

| Scenario | Handling |
|----------|----------|
| LLM hallucinates a non-whitelisted node type | Whitelist check catches it; prompt with "only use nodes from this list" in retry |
| LLM uses wrong credential ID | Substitute with correct credential from credentials map; do not count as a failure |
| LLM generates workflow calling a sub-workflow that doesn't exist | Recursively invoke Builder for that dependency (max depth 2); build dependencies first |
| Builder creates workflow but activation fails | Mark `status: inactive`; surface error to Orchestrator; do not execute |
| Workflow deploys and activates but execution fails | Mark `status: unverified`; return execution error to caller; leave in registry for debugging |
| Request is too complex for atomic workflow (>25 nodes estimated) | Return `escalation_needed` with a human-readable description; suggest breaking into sub-workflows |
| Builder called for the same workflow twice simultaneously | Deduplication lock: store in-flight workflow names in n8n static data; second call waits or returns the in-flight result |
| Generated workflow would duplicate an existing one (nodeHash match) | Return existing workflow instead of deploying duplicate |
| LLM.Council also fails to generate valid JSON after 6 total attempts | Full escalation: return structured error, save last attempt to disk for human review |

---

## 7. IoT Ingestion Layer

### Overview

Jetson Nano (and other IoT edge devices) perform local preprocessing before emitting
events to the Nexus orchestration layer. This keeps event payloads small and semantically
meaningful — raw sensor data is NOT passed to n8n.

### Preprocessing Contract (Jetson Nano)

The Jetson Nano is responsible for:
- **Vision:** Object detection, scene classification, face/person detection (not identification)
- **Audio:** Wake word detection, ambient noise classification, speech-to-text
- **Sensor fusion:** Combining multiple sensor streams into a single event
- **Compression:** All events must be compact JSON (< 4 KB)

The Jetson emits preprocessed events via HTTP POST to a Nexus ingestion webhook.

### Ingestion Webhook: `Nexus.IoT.Ingest`

**Endpoint:** `POST /webhook/iot-ingest`
**Auth:** Bearer token (device-specific, one per Jetson unit)

**Event Payload Schema:**
```jsonc
{
  "device_id":   "jetson-nano-01",
  "device_type": "jetson-nano",
  "timestamp":   "2026-02-18T12:00:00Z",
  "event_type":  "motion_detected | person_detected | speech | sensor | custom",
  "confidence":  0.87,           // preprocessing confidence (0–1)
  "payload": {
    // Event-specific structured data. Examples:
    // motion_detected: { zone: "front_door", duration_ms: 450 }
    // person_detected: { count: 1, location: "living_room" }
    // speech: { transcript: "turn off the lights", intent: "home_control" }
    // sensor: { type: "temperature", value: 72.4, unit: "F" }
  },
  "raw_ref":     null            // optional: reference ID to raw data stored on device
                                 // Nexus does NOT store raw data (stays on edge)
}
```

### Ingest Workflow Logic

```
Receive event
    ↓
Validate: device_id in trusted device list? confidence above threshold (> 0.5)?
    ↓ fail → 401 / discard
    ↓ pass
Route by event_type:
    motion_detected  → Email.Send alert (if armed) / log to episodic memory
    person_detected  → log to episodic memory / trigger downstream workflow
    speech           → extract intent → pass to Nexus.Orchestrator as a request
    sensor           → log to episodic memory / check thresholds / alert if exceeded
    custom           → pass payload directly to Nexus.Orchestrator with device context
```

The key path for voice/speech events: the Jetson's speech-to-text output flows directly
into `Nexus.Orchestrator` as a natural language request. The IoT layer and the Orchestrator
are connected by design — a spoken request from a Jetson behaves identically to a typed
request from a human.

### Future IoT Devices

The ingest schema is designed to be device-agnostic. Any device that can:
- Authenticate with a Bearer token
- Emit JSON events < 4 KB
- Perform its own preprocessing before emitting

...can be onboarded to the Nexus IoT layer without changes to the ingestion workflow.
New device types are registered in a `device-registry.json` (modeled after workflow-registry).

---

## 8. Memory Architecture (NAS)

### Overview

The NAS Memory Node provides two types of storage that are intentionally separate:

**Episodic Memory:** Event log. What happened, when, and in what context.
Every significant Nexus action is logged: workflow executions, IoT events, Orchestrator
routing decisions, Builder creations.

**Semantic Memory:** Knowledge base. What things mean and how they relate.
Workflow registry embeddings (for fast semantic search), entity relationships, learned
facts from the system's operation.

### Why Separate Storage from the Orchestrator Node

- The Cortex (4090) is compute. The NAS is storage. Mixing them creates a single point
  of failure and couples two concerns that scale differently.
- Episodic logs grow unboundedly. They belong on large spinning storage.
- Semantic indexes benefit from fast I/O — NAS with SSD cache tier is appropriate.

### Episodic Memory Schema

```jsonc
{
  "id":          "uuid",
  "timestamp":   "2026-02-18T12:00:00Z",
  "event_type":  "workflow_execution | iot_event | orchestrator_decision | builder_creation | error",
  "source":      "human | agent | iot | scheduled",
  "device_id":   "jetson-nano-01",     // null if not IoT
  "workflow":    "Email.Sort",          // null if not a workflow event
  "input":       { ... },              // sanitized (no credentials, no PII beyond what's needed)
  "output":      { ... },
  "duration_ms": 842,
  "status":      "success | error | partial",
  "tags":        ["email", "sort", "qwen"],
  "session_id":  "uuid"               // groups related events (e.g., one Orchestrator call → multiple sub-workflows)
}
```

### Semantic Memory / Vector Store

Primary use: fast semantic matching for Orchestrator routing.

Rather than prompting the Cortex LLM to compare a request to 50+ registry entries (slow,
token-expensive), the Orchestrator first does a vector similarity search against the embedded
`semanticDescription` fields. The top-k results (k=5) are then passed to the LLM for final
ranking. This makes routing fast even as the library grows to hundreds of workflows.

**Implementation:**
- Qdrant (self-hosted) on NAS
- Embeddings generated by the Cortex LLM (or a dedicated small embedding model)
- Registry embeddings recomputed whenever a workflow is added or its `semanticDescription` changes
- Query at routing time: embed the incoming request, top-5 nearest neighbors from registry

This is Phase 4 infrastructure — build after the Orchestrator is working with simple LLM-based matching.

### Privacy Boundary

Episodic logs must NOT store:
- Raw credentials or tokens
- Full email body content (store subject + metadata only)
- Biometric data from IoT devices
- Any PII that isn't necessary for operational replay

---

## 9. Error Handling Philosophy

**Principle: Degrade gracefully. Never fail silently. Always return something actionable.**

### Failure Hierarchy

```
Level 1 — Transient failure
    Workflow execution returns an error once.
    Action: Retry once after 2s. If still failing → Level 2.

Level 2 — Persistent execution failure
    Workflow fails on retry.
    Action: Return structured error to caller. Log to episodic memory. Do not retry.
    Surface: "Workflow X failed: <specific error>. Last successful run: <timestamp>."

Level 3 — Builder validation failure
    Cortex LLM can't produce valid workflow JSON within 3 attempts.
    Action: Escalate to LLM.Council. 3 more attempts.
    If still failing → Level 4.

Level 4 — Builder total failure
    All 6 attempts failed (3 Cortex + 3 Council).
    Action: Return structured escalation error. Save last attempt to disk at
    docs/builder-failures/<timestamp>-<workflow-name>.json for human debugging.
    Do not deploy. Notify operator.

Level 5 — Infrastructure failure
    n8n API unreachable / Cortex LLM unreachable.
    Action: Cortex LLM fallback → Brainstem LLM for basic routing only.
    If n8n unreachable → return "infrastructure unavailable", do not attempt workflows.
    Log and alert.

Level 6 — Registry failure
    workflow-registry.json missing or corrupt.
    Action: Fall back to empty registry (no workflows known).
    All requests treated as "no match" → Builder attempts to recreate everything → high risk.
    Therefore: immediately alert operator and suspend Builder until registry is restored.
    Orchestrator can still route if n8n has the workflows (by direct ID) but will be blind.
```

### Structured Error Format

All errors returned by Orchestrator/Builder follow this schema:

```jsonc
{
  "status":      "error",
  "error": {
    "code":      "WORKFLOW_EXECUTION_FAILED | BUILDER_ESCALATION | INFRASTRUCTURE_UNAVAILABLE | ...",
    "message":   "Human-readable description of what went wrong",
    "workflow":  "Email.Sort",         // which workflow was involved (null if none)
    "attempt":   2,                    // which attempt number failed
    "detail":    { ... },              // raw error from n8n or LLM, for debugging
    "suggestion":"Check Gmail credential expiry. Last auth: 2026-01-15."
  }
}
```

---

## 10. Security & Guardrails

### Node Whitelist

The Builder may only generate workflows using node types listed in the registry's
`nodeWhitelist`. Any generated workflow containing an unlisted node type is:
1. Rejected during validation (Step B of the validation loop)
2. The LLM is instructed to retry using only whitelisted nodes

Adding a new node type to the whitelist is a deliberate human action (edit registry,
commit to git) not something the Builder or Orchestrator can do autonomously.

### Credential Isolation

The Builder may only reference credentials that already exist in the n8n credential store
AND are listed in the registry's credential map. It cannot:
- Create new credentials
- Reference credentials by anything other than their known IDs
- Generate workflows that prompt the user to enter new credentials

### Dangerous Action Gate

Defined dangerous operations (applied at Orchestrator level, before Builder):
- Any bulk operation affecting > 10 items without explicit limit
- Any delete operation (email, file, calendar event)
- Any external HTTP POST/PUT/DELETE to URLs outside the known Nexus node IPs
- Any email send that is not using a template already defined in the registry
- Any operation to an unknown external service

These require `confirm_dangerous: true` in the Orchestrator input. The Orchestrator
surfaces a plain-English description of the action before executing.

### Rate Limiting

Builder rate limit: **5 new workflow deployments per hour per source.**
Purpose: prevent runaway generation loops (e.g., Orchestrator retry bug calling Builder
repeatedly for the same failing request).

Enforced via n8n workflow static data (increment counter, reset hourly).

### HTTP Request Audit

Any workflow created by the Builder that contains an HTTP Request node pointing to
a URL outside the internal LAN (`192.168.1.x`) is flagged `allowedCallers: "human-only"`
and requires human review before the flag is changed to `"any"`.

### Recursive / Self-Reference Guard

The Orchestrator tracks the current execution chain in the session context.
Rules:
- Max compound action decomposition depth: 3
- Max Builder dependency recursion depth: 2
- If Orchestrator receives a request that would call itself → error, not recursion

---

## 11. Self-Improvement Loop

### Per-Execution

On every successful workflow execution:
- `usageCount` incremented in registry (in-memory; persisted to disk on batch interval)
- `lastVerified` updated

On every Builder creation + first successful execution:
- `status` updated from `"unverified"` to `"active"`
- Git commit queued for registry file

### Weekly Audit (future scheduled workflow)

A `Nexus.RegistryAudit` workflow runs weekly:
1. Finds workflows with `usageCount = 0` for 30+ days → flags for human review (possible deletion)
2. Finds workflows where `lastVerified` is > 7 days ago → runs a health check execution
3. Finds structural duplicates (nodeHash collisions) → surfaces to operator for merge decision
4. Finds workflows with `status: unverified` older than 24 hours → escalates (something is wrong)

### Semantic Search Improvement

As the library grows, the vector embeddings in the NAS become a richer search space.
More workflows = better routing = fewer Builder invocations = faster responses.
The system naturally becomes more efficient as it operates.

### Self-Documentation

Every time the Builder creates a workflow, it writes a `semanticDescription` that becomes
part of the routing corpus. The system teaches itself what it can do by doing it.

---

## 12. Build Order

The following sequence respects dependencies — each item can only be built after the
items it depends on are complete.

### Phase 3A — Cortex LLM Foundation
1. **Cortex vLLM service** — Add to `docker-compose.yml`, pull Qwen2.5-Coder-32B-Instruct-AWQ, verify `/v1/models` responds on port 8001
2. **Environment variables** — Add `CORTEX_LLM_URL` and `BRAINSTEM_LLM_URL` to docker-compose n8n env block, recreate container
3. **Registry schema migration** — Extend `workflow-registry.json` to v2.0 schema with new fields on all existing entries

### Phase 3B — Builder (build before Orchestrator — Orchestrator depends on it)
4. **`Nexus.Builder`** — The creation engine. Can be tested in isolation by giving it a workflow spec and verifying it deploys a valid workflow.
5. **Builder test harness** — `Test.Nexus.Builder` webhook workflow

### Phase 3C — Orchestrator
6. **`Nexus.Orchestrator`** — The routing brain. Depends on Builder existing.
7. **Orchestrator test harness** — `Test.Nexus.Orchestrator` webhook workflow
8. **End-to-end test** — Send a request for a workflow that doesn't exist; verify the full loop: Orchestrator → Builder → deploy → execute → return result

### Phase 3D — IoT Ingestion
9. **Device registry** — `device-registry.json` with Jetson Nano entry
10. **`Nexus.IoT.Ingest`** — Ingestion webhook workflow
11. **Jetson integration** — Configure Jetson Nano to emit preprocessed events to the webhook

### Phase 4 — Memory (NAS)
12. **NAS setup** — Hardware + OS + network share
13. **Qdrant** — Docker on NAS, vector store for semantic memory
14. **Episodic logger** — `Nexus.Memory.Log` workflow that writes events to NAS
15. **Registry embedder** — Compute and store embeddings for all `semanticDescription` fields
16. **Orchestrator v2** — Replace LLM-only Tier 2 matching with vector search + LLM reranking

### Phase 5 — Optimization
17. **`Nexus.RegistryAudit`** — Weekly health check and cleanup
18. **`Nexus.GitSync`** — Auto-commit verified new workflows to git
19. **TensorRT-LLM migration** (optional) — If throughput becomes a bottleneck, convert Cortex model to TRT engine. API interface unchanged.

---

*This document is the canonical design reference for the Cortex layer. Update it before changing the architecture — the document should always reflect deployed reality.*
