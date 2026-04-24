# Nexus.Builder — 18-Node Architecture Spec

*Canonical implementation reference for the Nexus.Builder workflow.*

---

## Node Summary Table

| # | Name | Type | typeVersion | Position |
|---|------|------|-------------|----------|
| 1 | Execute Workflow Trigger | n8n-nodes-base.executeWorkflowTrigger | 1.1 | [0, 0] |
| 2 | Validate Input | n8n-nodes-base.code | 2 | [240, 0] |
| 3 | Call Cortex LLM | n8n-nodes-base.httpRequest | 4.2 | [480, 0] |
| 4 | Parse and Validate | n8n-nodes-base.code | 2 | [720, 0] |
| 5 | IF Validation Passed | n8n-nodes-base.if | 2 | [960, 0] |
| 6 | Validate with n8n API | n8n-nodes-base.httpRequest | 4.2 | [1200, -150] |
| 7a | Parse n8n Validation | n8n-nodes-base.code | 2 | [1440, -150] |
| 8 | IF API Validation Passed | n8n-nodes-base.if | 2 | [1680, -150] |
| 7b | Inject Error Feedback | n8n-nodes-base.code | 2 | [1200, 150] |
| 9 | Check Attempt Limit | n8n-nodes-base.if | 2 | [1440, 150] |
| 10 | Format Escalation Error | n8n-nodes-base.set | 3.4 | [1680, 300] |
| 11 | Deploy — Create Workflow | n8n-nodes-base.httpRequest | 4.2 | [1920, -150] |
| 12 | Deploy Handler | n8n-nodes-base.code | 2 | [2160, -150] |
| 13 | IF Deploy Succeeded | n8n-nodes-base.if | 2 | [2400, -150] |
| 14 | Activate Workflow | n8n-nodes-base.httpRequest | 4.2 | [2640, -150] |
| 15 | Update Registry | n8n-nodes-base.code | 2 | [2880, -150] |
| 16 | Verify Activation | n8n-nodes-base.httpRequest | 4.2 | [3120, -150] |
| 17 | Format Final Output | n8n-nodes-base.code | 2 | [3360, 0] |

Total: 18 nodes. Node 7a and 7b are two distinct nodes at the same conceptual level.
Terminal outputs: NODE 10 (escalation error) and NODE 17 (success/deploy-failure).

---

## Complete Connection Map

```
Execute Workflow Trigger  → [0] → Validate Input                [0]
Validate Input            → [0] → Call Cortex LLM               [0]
Call Cortex LLM           → [0] → Parse and Validate            [0]
Parse and Validate        → [0] → IF Validation Passed          [0]

IF Validation Passed      → [0] → Validate with n8n API         [0]   (TRUE: no error)
IF Validation Passed      → [1] → Inject Error Feedback         [0]   (FALSE: has error)

Validate with n8n API     → [0] → Parse n8n Validation          [0]
Parse n8n Validation      → [0] → IF API Validation Passed      [0]

IF API Validation Passed  → [0] → Deploy — Create Workflow      [0]   (TRUE: passed)
IF API Validation Passed  → [1] → Inject Error Feedback         [0]   (FALSE: failed)

Inject Error Feedback     → [0] → Check Attempt Limit           [0]
Check Attempt Limit       → [0] → Call Cortex LLM               [0]   (TRUE: retry — LOOP BACK)
Check Attempt Limit       → [1] → Format Escalation Error       [0]   (FALSE: escalate)

Deploy — Create Workflow  → [0] → Deploy Handler                [0]
Deploy Handler            → [0] → IF Deploy Succeeded           [0]

IF Deploy Succeeded       → [0] → Activate Workflow             [0]   (TRUE: has ID)
IF Deploy Succeeded       → [1] → Format Final Output           [0]   (FALSE: deploy failed)

Activate Workflow         → [0] → Update Registry               [0]
Update Registry           → [0] → Verify Activation             [0]
Verify Activation         → [0] → Format Final Output           [0]
```

**CRITICAL LOOP-BACK:** Check Attempt Limit output [0] → Call Cortex LLM [0] is a backward edge in the canvas. n8n allows this — drag the output connector left past NODE 3.

**NODE 17 receives from two paths:**
- NODE 16 (Verify Activation) — happy path
- NODE 13 output [1] (IF Deploy Succeeded FALSE) — deploy failure path
Both connect to NODE 17 input [0]. Named node fallback handles which path ran.

---

## NODE DEFINITIONS

### NODE 1: Execute Workflow Trigger

```
name:        "Execute Workflow Trigger"
id:          "nb01"
type:        "n8n-nodes-base.executeWorkflowTrigger"
typeVersion: 1.1
position:    [0, 0]
```

```json
{
  "inputSource": "workflowInputs",
  "workflowInputs": {
    "values": [
      { "name": "description",      "type": "string"  },
      { "name": "domain",           "type": "string"  },
      { "name": "required_inputs",  "type": "object"  },
      { "name": "expected_outputs", "type": "object"  },
      { "name": "similarity_match", "type": "object"  }
    ]
  }
}
```

`similarity_match` is optional — when present, strategy=MODIFY; when absent, strategy=GENERATE.

---

### NODE 2: Validate Input

```
name:        "Validate Input"
id:          "nb02"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [240, 0]
```

**Code Block A:**
```javascript
const item = $input.first().json;

// Required field validation
const required = ['description', 'domain', 'required_inputs', 'expected_outputs'];
for (const field of required) {
  if (!item[field]) {
    throw new Error(`Missing required field: ${field}`);
  }
}

// Determine strategy
const strategy = item.similarity_match ? 'MODIFY' : 'GENERATE';

// Node whitelist (read from registry if available, else hardcoded)
let nodeWhitelist;
try {
  const fs = require('fs');
  const registry = JSON.parse(fs.readFileSync('/data/workflow-registry.json', 'utf8'));
  nodeWhitelist = registry.nodeWhitelist || null;
} catch(e) {
  nodeWhitelist = null;
}

const DEFAULT_WHITELIST = [
  "n8n-nodes-base.executeWorkflowTrigger",
  "n8n-nodes-base.code",
  "n8n-nodes-base.set",
  "n8n-nodes-base.httpRequest",
  "n8n-nodes-base.if",
  "n8n-nodes-base.switch",
  "n8n-nodes-base.merge",
  "n8n-nodes-base.gmail",
  "n8n-nodes-base.googleCalendar",
  "n8n-nodes-base.googleSheets",
  "n8n-nodes-base.webhook",
  "n8n-nodes-base.wait",
  "n8n-nodes-base.noOp"
];

// Build workflow_name: Domain.Operation format
const domainCap = item.domain.charAt(0).toUpperCase() + item.domain.slice(1);
// Extract operation from description (naive: first verb-noun pair)
const opWords = item.description.match(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b/);
const operation = opWords ? opWords[0].replace(/\s+/g, '') : 'Custom';
const workflowName = `${domainCap}.${operation}`;

// Build the initial Cortex prompt
const CREDENTIAL_MAP = {
  email:    "Gmail account",
  calendar: "Google Calendar account",
  sheets:   "Google Sheets account",
  drive:    "Google Drive account"
};
const credentialHint = CREDENTIAL_MAP[item.domain.toLowerCase()] || null;

let promptMessages;
if (strategy === 'GENERATE') {
  promptMessages = [{
    role: 'user',
    content: `You are an expert n8n workflow architect. Generate a complete, valid n8n workflow JSON for the following spec.

WORKFLOW NAME: ${workflowName}
DOMAIN: ${item.domain}
DESCRIPTION: ${item.description}
REQUIRED INPUTS: ${JSON.stringify(item.required_inputs, null, 2)}
EXPECTED OUTPUTS: ${JSON.stringify(item.expected_outputs, null, 2)}
${credentialHint ? `CREDENTIAL: Use credential named "${credentialHint}" for any OAuth nodes.` : ''}

RULES:
1. Start with an Execute Workflow Trigger node (type: n8n-nodes-base.executeWorkflowTrigger, typeVersion: 1.1, inputSource: "workflowInputs")
2. Only use node types from this whitelist: ${JSON.stringify(nodeWhitelist || DEFAULT_WHITELIST)}
3. End with a Set node (type: n8n-nodes-base.set, typeVersion: 3.4) named "Format Output" that outputs exactly the fields in EXPECTED OUTPUTS
4. Include proper connections array
5. Use typeVersion values: code=2, set=3.4, httpRequest=4.2, if=2, gmail=2, googleCalendar=2

Output ONLY the raw JSON object — no markdown fences, no explanation. The entire response must be parseable by JSON.parse().

Required top-level fields: name, nodes, connections, settings`
  }];
} else {
  // MODIFY strategy
  const src = item.similarity_match;
  promptMessages = [{
    role: 'user',
    content: `You are an expert n8n workflow architect. Modify the provided workflow to match the new spec.

NEW WORKFLOW NAME: ${workflowName}
DOMAIN: ${item.domain}
DESCRIPTION: ${item.description}
REQUIRED INPUTS: ${JSON.stringify(item.required_inputs, null, 2)}
EXPECTED OUTPUTS: ${JSON.stringify(item.expected_outputs, null, 2)}
${credentialHint ? `CREDENTIAL: Use credential named "${credentialHint}" for any OAuth nodes.` : ''}

SOURCE WORKFLOW (modify this): ${JSON.stringify(src.json, null, 2)}

RULES:
1. Keep the same general structure but adapt it to the new spec
2. Only use node types from this whitelist: ${JSON.stringify(nodeWhitelist || DEFAULT_WHITELIST)}
3. Update the workflow name to: ${workflowName}
4. Ensure the output matches EXPECTED OUTPUTS exactly
5. Preserve valid patterns from the source; replace domain-specific logic as needed

Output ONLY the raw JSON object — no markdown fences, no explanation. Must be parseable by JSON.parse().`
  }];
}

return [{
  json: {
    ...item,
    workflow_name: workflowName,
    strategy: strategy,
    attempt_count: 1,
    messages: promptMessages,
    node_whitelist: nodeWhitelist || DEFAULT_WHITELIST,
    validation_error: null,
    workflow_json: null
  }
}];
```

---

### NODE 3: Call Cortex LLM

```
name:          "Call Cortex LLM"
id:            "nb03"
type:          "n8n-nodes-base.httpRequest"
typeVersion:   4.2
position:      [480, 0]
continueOnFail: true
```

```json
{
  "method": "POST",
  "url": "http://host.docker.internal:8001/v1/chat/completions",
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [
      { "name": "Content-Type", "value": "application/json" }
    ]
  },
  "sendBody": true,
  "specifyBody": "string",
  "body": "={{ JSON.stringify({ model: 'cortex', messages: $json.messages, temperature: 0.1, max_tokens: 4096, chat_template_kwargs: { thinking: false } }) }}",
  "options": {
    "response": {
      "response": {
        "fullResponse": false,
        "responseFormat": "json"
      }
    },
    "timeout": 120000
  }
}
```

**TRICKY PART 1:** `body` must be a **string expression** using `JSON.stringify()` — NOT the structured body UI. The messages array in `$json.messages` grows across retries as error turns are appended.
**TRICKY PART 2:** Use `host.docker.internal:8001` (not `localhost`) — n8n runs in Docker, Cortex runs in WSL2 on the host.
**TRICKY PART 3:** `chat_template_kwargs: { thinking: false }` suppresses Qwen3's chain-of-thought reasoning, getting structured JSON output directly.
**TRICKY PART 4:** `continueOnFail: true` — network errors (Cortex down, timeout) must not crash the workflow.

---

### NODE 4: Parse and Validate

```
name:        "Parse and Validate"
id:          "nb04"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [720, 0]
```

**Code Block B:**
```javascript
// Recover prior state (HTTP node replaces $json with response)
const priorState = $('Validate Input').first().json;

// Get error feedback from retry loop (null on first attempt)
let errorContext = null;
try {
  errorContext = $('Inject Error Feedback').first().json;
} catch(e) {
  // Not in a retry — normal first attempt
}

// Use most recent state (error context has updated attempt_count etc.)
const state = errorContext || priorState;

// Get LLM response
const llmResponse = $input.first().json;

// Step A: Check for HTTP/network error
if ($input.first().error || !llmResponse.choices) {
  const errMsg = $input.first().error?.message || 'No choices in LLM response';
  return [{
    json: {
      ...state,
      validation_error: `LLM call failed: ${errMsg}`,
      workflow_json: null,
      parsed_ok: false
    }
  }];
}

// Step B: Extract content and parse JSON
let rawContent = llmResponse.choices[0]?.message?.content;
if (rawContent == null) {
  return [{
    json: {
      ...state,
      validation_error: 'LLM returned null content (likely hit max_tokens during thinking)',
      workflow_json: null,
      parsed_ok: false
    }
  }];
}

// Strip markdown fences if present
rawContent = rawContent.trim();
if (rawContent.startsWith('```')) {
  rawContent = rawContent.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
}

// Repair control characters inside string values (Qwen3 JSON quirk)
function repairJson(raw) {
  let result = '';
  let inString = false;
  let escaped = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (escaped) { result += ch; escaped = false; continue; }
    if (ch === '\\' && inString) { result += ch; escaped = true; continue; }
    if (ch === '"') { inString = !inString; result += ch; continue; }
    if (inString && ch.charCodeAt(0) < 32) {
      // Escape control character
      if (ch === '\n') result += '\\n';
      else if (ch === '\r') result += '\\r';
      else if (ch === '\t') result += '\\t';
      else result += '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0');
      continue;
    }
    result += ch;
  }
  return result;
}

let parsed;
try {
  parsed = JSON.parse(rawContent);
} catch(e) {
  try {
    parsed = JSON.parse(repairJson(rawContent));
  } catch(e2) {
    return [{
      json: {
        ...state,
        validation_error: `JSON parse failed: ${e.message}. Raw (first 500 chars): ${rawContent.slice(0, 500)}`,
        workflow_json: rawContent,
        parsed_ok: false
      }
    }];
  }
}

// Step C: Node whitelist check
const whitelist = new Set(state.node_whitelist || []);
const nodes = parsed.nodes || [];
const badNodes = nodes.filter(n => !whitelist.has(n.type));
if (badNodes.length > 0) {
  return [{
    json: {
      ...state,
      validation_error: `Workflow uses non-whitelisted node types: ${badNodes.map(n => n.type).join(', ')}`,
      workflow_json: JSON.stringify(parsed),
      parsed_ok: false
    }
  }];
}

// Step D: Basic structure check
if (!parsed.nodes || !Array.isArray(parsed.nodes) || parsed.nodes.length === 0) {
  return [{
    json: {
      ...state,
      validation_error: 'Workflow JSON missing required "nodes" array',
      workflow_json: JSON.stringify(parsed),
      parsed_ok: false
    }
  }];
}
if (!parsed.connections || typeof parsed.connections !== 'object') {
  return [{
    json: {
      ...state,
      validation_error: 'Workflow JSON missing required "connections" object',
      workflow_json: JSON.stringify(parsed),
      parsed_ok: false
    }
  }];
}
if (!parsed.name) {
  parsed.name = state.workflow_name;
}

// Step E: Set workflow settings
parsed.settings = {
  executionOrder: 'v1',
  saveDataSuccessExecution: 'all',
  saveDataErrorExecution: 'all',
  saveManualExecutions: true,
  timezone: 'US/Central',
  callerPolicy: 'workflowsFromSameOwner'
};

return [{
  json: {
    ...state,
    validation_error: null,
    workflow_json: JSON.stringify(parsed),
    parsed_workflow: parsed,
    parsed_ok: true
  }
}];
```

---

### NODE 5: IF Validation Passed

```
name:        "IF Validation Passed"
id:          "nb05"
type:        "n8n-nodes-base.if"
typeVersion: 2
position:    [960, 0]
```

```json
{
  "conditions": {
    "conditions": [
      {
        "id": "val1",
        "leftValue": "={{ $json.parsed_ok }}",
        "rightValue": true,
        "operator": { "type": "boolean", "operation": "true" }
      }
    ],
    "combinator": "and"
  }
}
```

Output [0] (TRUE) → NODE 6: Validate with n8n API
Output [1] (FALSE) → NODE 7b: Inject Error Feedback

---

### NODE 6: Validate with n8n API

```
name:          "Validate with n8n API"
id:            "nb06"
type:          "n8n-nodes-base.httpRequest"
typeVersion:   4.2
position:      [1200, -150]
continueOnFail: true
```

```json
{
  "method": "POST",
  "url": "http://localhost:5678/api/v1/workflows/validate",
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [
      { "name": "Content-Type", "value": "application/json" },
      { "name": "X-N8N-API-KEY", "value": "={{ $env.N8N_API_KEY }}" }
    ]
  },
  "sendBody": true,
  "specifyBody": "string",
  "body": "={{ $json.workflow_json }}",
  "options": {
    "response": {
      "response": {
        "fullResponse": true,
        "responseFormat": "json"
      }
    },
    "timeout": 30000
  }
}
```

**TRICKY PART 6:** Use `fullResponse: true` — HTTP 400 (validation error) would crash without it. We need to inspect `statusCode` in the next code node.
**TRICKY PART 7:** If n8n version doesn't support this endpoint (404), Parse n8n Validation treats 404 as a pass.

---

### NODE 7a: Parse n8n Validation

```
name:        "Parse n8n Validation"
id:          "nb07a"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [1440, -150]
```

**Code Block C:**
```javascript
const apiResponse = $input.first().json;
const priorState = $('Parse and Validate').first().json;

const statusCode = apiResponse.statusCode;

// 404 = endpoint not supported by this n8n version — treat as pass
// 200 = passed validation
// 400 = failed validation
if (!statusCode || statusCode === 404 || (statusCode >= 200 && statusCode < 300)) {
  return [{
    json: {
      ...priorState,
      n8n_api_validation: 'passed',
      n8n_validation_error: null
    }
  }];
}

// Extract error from response body
const body = apiResponse.body || {};
const errMsg = body.message || body.error || `n8n API validation rejected workflow (HTTP ${statusCode})`;

return [{
  json: {
    ...priorState,
    n8n_api_validation: 'failed',
    n8n_validation_error: errMsg,
    parsed_ok: false,
    validation_error: `n8n structural validation failed: ${errMsg}`
  }
}];
```

---

### NODE 8: IF API Validation Passed

```
name:        "IF API Validation Passed"
id:          "nb08"
type:        "n8n-nodes-base.if"
typeVersion: 2
position:    [1680, -150]
```

```json
{
  "conditions": {
    "conditions": [
      {
        "id": "api1",
        "leftValue": "={{ $json.n8n_api_validation }}",
        "rightValue": "failed",
        "operator": { "type": "string", "operation": "notEquals" }
      }
    ],
    "combinator": "and"
  }
}
```

Output [0] (TRUE = not failed) → NODE 11: Deploy — Create Workflow
Output [1] (FALSE = failed) → NODE 7b: Inject Error Feedback

---

### NODE 7b: Inject Error Feedback

```
name:        "Inject Error Feedback"
id:          "nb07b"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [1200, 150]
```

Receives from: NODE 5 output [1] AND NODE 8 output [1]

**Code Block D:**
```javascript
const item = $input.first().json;

// Build error feedback turn for the LLM
const updatedMessages = [...(item.messages || [])];

// Add the assistant's bad response (if we have it)
if (item.workflow_json) {
  updatedMessages.push({
    role: 'assistant',
    content: item.workflow_json
  });
}

updatedMessages.push({
  role: 'user',
  content: `That response had an error. Fix it and try again.\n\nError: ${item.validation_error}\n\nRemember: output ONLY valid JSON, no markdown fences, no explanation. The entire response must be parseable by JSON.parse(). Only use node types from the whitelist.`
});

return [{
  json: {
    ...item,
    attempt_count: (item.attempt_count || 1) + 1,
    messages: updatedMessages
  }
}];
```

---

### NODE 9: Check Attempt Limit

```
name:        "Check Attempt Limit"
id:          "nb09"
type:        "n8n-nodes-base.if"
typeVersion: 2
position:    [1440, 150]
```

```json
{
  "conditions": {
    "conditions": [
      {
        "id": "cond1",
        "leftValue": "={{ $json.attempt_count }}",
        "rightValue": 3,
        "operator": { "type": "number", "operation": "lte" }
      }
    ],
    "combinator": "and"
  }
}
```

Output [0] (TRUE = attempt_count <= 3) → NODE 3: Call Cortex LLM **LOOP BACK**
Output [1] (FALSE = attempt_count > 3) → NODE 10: Format Escalation Error

**TRICKY PART 10:** Backward connection from output [0] to NODE 3. In n8n UI, drag the connector back left. n8n allows backward edges.
**TRICKY PART 11:** `attempt_count` starts at 1. After failure, Inject Error Feedback increments to 2. Check is `<= 3` → attempts 1, 2, 3 retry; attempt 4 escalates.

---

### NODE 10: Format Escalation Error

```
name:        "Format Escalation Error"
id:          "nb10"
type:        "n8n-nodes-base.set"
typeVersion: 3.4
position:    [1680, 300]
```

```json
{
  "mode": "manual",
  "assignments": {
    "assignments": [
      { "id": "esc1", "name": "status", "value": "error", "type": "string" },
      { "id": "esc2", "name": "error_code", "value": "BUILDER_ESCALATION", "type": "string" },
      { "id": "esc3", "name": "workflow_name", "value": "={{ $json.workflow_name }}", "type": "string" },
      { "id": "esc4", "name": "strategy_used", "value": "={{ $json.strategy }}", "type": "string" },
      { "id": "esc5", "name": "attempts", "value": "={{ $json.attempt_count - 1 }}", "type": "number" },
      { "id": "esc6", "name": "last_error", "value": "={{ $json.validation_error }}", "type": "string" },
      { "id": "esc7", "name": "last_workflow_json", "value": "={{ $json.workflow_json }}", "type": "string" },
      { "id": "esc8", "name": "message", "value": "={{ 'Nexus.Builder failed after ' + ($json.attempt_count - 1) + ' attempts. Last error: ' + $json.validation_error }}", "type": "string" },
      { "id": "esc9", "name": "n8nId", "value": null, "type": "string" }
    ]
  },
  "includeOtherFields": false
}
```

**Terminal node** — NOT connected to Format Final Output. Caller must handle both output shapes.

---

### NODE 11: Deploy — Create Workflow

```
name:          "Deploy — Create Workflow"
id:            "nb11"
type:          "n8n-nodes-base.httpRequest"
typeVersion:   4.2
position:      [1920, -150]
continueOnFail: true
```

```json
{
  "method": "POST",
  "url": "http://localhost:5678/api/v1/workflows",
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [
      { "name": "Content-Type", "value": "application/json" },
      { "name": "X-N8N-API-KEY", "value": "={{ $env.N8N_API_KEY }}" }
    ]
  },
  "sendBody": true,
  "specifyBody": "string",
  "body": "={{ $json.workflow_json }}",
  "options": {
    "response": {
      "response": {
        "fullResponse": false,
        "responseFormat": "json"
      }
    },
    "timeout": 30000
  }
}
```

**TRICKY PART 12:** Response contains `id` field = the new workflow's n8n ID. Deploy Handler must recover prior state from `$('Parse n8n Validation')` since HTTP replaced `$json`.
**TRICKY PART 13:** `continueOnFail: true` — deployment failure (duplicate name, API unreachable) must produce a structured error.

---

### NODE 12: Deploy Handler

```
name:        "Deploy Handler"
id:          "nb12"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [2160, -150]
```

**Code Block E:**
```javascript
const createResponse = $input.first().json;
let priorState;
try {
  priorState = $('Parse n8n Validation').first().json;
} catch(e) {
  priorState = $('Parse and Validate').first().json;
}

if ($input.first().error || createResponse.message) {
  const errMsg = $input.first().error?.message || createResponse.message || 'Unknown deployment error';
  return [{
    json: {
      ...priorState,
      status: 'error',
      error_code: 'DEPLOYMENT_FAILED',
      message: 'Failed to create workflow via n8n API: ' + errMsg,
      n8nId: null
    }
  }];
}

const newId = createResponse.id;
if (!newId) {
  return [{
    json: {
      ...priorState,
      status: 'error',
      error_code: 'DEPLOYMENT_FAILED',
      message: 'n8n API returned no workflow ID in create response',
      n8nId: null
    }
  }];
}

return [{
  json: {
    ...priorState,
    n8nId: newId,
    deploy_error: null
  }
}];
```

---

### NODE 13: IF Deploy Succeeded

```
name:        "IF Deploy Succeeded"
id:          "nb13"
type:        "n8n-nodes-base.if"
typeVersion: 2
position:    [2400, -150]
```

```json
{
  "conditions": {
    "conditions": [
      {
        "id": "dep1",
        "leftValue": "={{ $json.n8nId }}",
        "rightValue": "",
        "operator": { "type": "string", "operation": "notEmpty" }
      }
    ],
    "combinator": "and"
  }
}
```

Output [0] (TRUE) → NODE 14: Activate Workflow
Output [1] (FALSE) → NODE 17: Format Final Output *(passes through error state)*

---

### NODE 14: Activate Workflow

```
name:          "Activate Workflow"
id:            "nb14"
type:          "n8n-nodes-base.httpRequest"
typeVersion:   4.2
position:      [2640, -150]
continueOnFail: true
```

```json
{
  "method": "POST",
  "url": "={{ 'http://localhost:5678/api/v1/workflows/' + $json.n8nId + '/activate' }}",
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [
      { "name": "X-N8N-API-KEY", "value": "={{ $env.N8N_API_KEY }}" }
    ]
  },
  "sendBody": false,
  "options": {
    "response": {
      "response": {
        "fullResponse": true,
        "responseFormat": "json"
      }
    },
    "timeout": 30000
  }
}
```

**TRICKY PART 14:** `fullResponse: true` — n8n 2.x may return 200 or 204 for activation. Check `statusCode` not body.
**TRICKY PART (from MEMORY.md):** Sub-workflows MUST be active to be callable. This step is non-negotiable.

---

### NODE 15: Update Registry

```
name:        "Update Registry"
id:          "nb15"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [2880, -150]
```

**Code Block F:**
```javascript
const activateResponse = $input.first().json;
const priorState = $('Deploy Handler').first().json;

const statusCode = activateResponse.statusCode || 200;
const activationSucceeded = (statusCode >= 200 && statusCode < 300);

const fs = require('fs');
const crypto = require('crypto');
const registryPath = '/data/workflow-registry.json';

// Compute nodeHash for duplicate detection
const nodes = priorState.parsed_workflow?.nodes || [];
const hashInput = nodes.map(n => n.type + ':' + n.name).sort().join('|');
const nodeHash = crypto.createHash('sha256').update(hashInput).digest('hex').slice(0, 16);

// Build new registry entry (v2.0 schema)
const newEntry = {
  n8nId: priorState.n8nId,
  description: priorState.description,
  semanticDescription: priorState.description + ' — generated by Nexus.Builder on ' + new Date().toISOString(),
  input: priorState.required_inputs,
  output: priorState.expected_outputs,
  tags: [priorState.domain, 'builder-generated'],
  status: activationSucceeded ? 'unverified' : 'inactive',
  version: 1,
  createdBy: 'builder',
  nodeHash: nodeHash,
  usageCount: 0,
  lastVerified: null,
  dependsOn: [],
  allowedCallers: 'any'
};

// Read, update, write registry
let registry = {};
try {
  const raw = fs.readFileSync(registryPath, 'utf8');
  registry = JSON.parse(raw);
} catch(e) {
  // Start fresh if registry missing/corrupt
}

registry.workflows = registry.workflows || {};
registry.workflows[priorState.workflow_name] = newEntry;
registry.lastUpdated = new Date().toISOString();

try {
  fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2), 'utf8');
} catch(e) {
  return [{
    json: {
      ...priorState,
      activation_succeeded: activationSucceeded,
      registry_write_error: e.message,
      registry_updated: false
    }
  }];
}

return [{
  json: {
    ...priorState,
    activation_succeeded: activationSucceeded,
    registry_write_error: null,
    registry_updated: true,
    new_entry: newEntry
  }
}];
```

**TRICKY PART 15:** `require('fs')` and `require('crypto')` available when `N8n_BLOCK_ENV_ACCESS_IN_NODE=false`.
**TRICKY PART 16:** No locking — concurrent Builder calls can clobber each other. Acceptable for Phase 3B.

---

### NODE 16: Verify Activation

```
name:          "Verify Activation"
id:            "nb16"
type:          "n8n-nodes-base.httpRequest"
typeVersion:   4.2
position:      [3120, -150]
continueOnFail: true
```

```json
{
  "method": "GET",
  "url": "={{ 'http://localhost:5678/api/v1/workflows/' + $json.n8nId }}",
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [
      { "name": "X-N8N-API-KEY", "value": "={{ $env.N8N_API_KEY }}" }
    ]
  },
  "options": {
    "response": {
      "response": {
        "fullResponse": false,
        "responseFormat": "json"
      }
    },
    "timeout": 15000
  }
}
```

---

### NODE 17: Format Final Output

```
name:        "Format Final Output"
id:          "nb17"
type:        "n8n-nodes-base.code"
typeVersion: 2
position:    [3360, 0]
```

Receives from: NODE 16 (happy path) AND NODE 13 output [1] (deploy failure path).

**Code Block G:**
```javascript
const current = $input.first().json;

// Recover full state — fallback chain depending on which path ran
let priorState;
try {
  priorState = $('Update Registry').first().json;
} catch(e) {
  try {
    priorState = $('Deploy Handler').first().json;
  } catch(e2) {
    priorState = current;
  }
}

const verifiedActive = current.active === true;
const deployFailed = priorState.status === 'error' || !priorState.n8nId;

if (deployFailed) {
  return [{
    json: {
      workflow_name: priorState.workflow_name || null,
      n8nId: null,
      status: 'error',
      strategy_used: priorState.strategy || null,
      attempts: priorState.attempt_count ? priorState.attempt_count - 1 : 0,
      error_code: priorState.error_code || 'DEPLOYMENT_FAILED',
      message: priorState.message || 'Deployment failed'
    }
  }];
}

return [{
  json: {
    workflow_name: priorState.workflow_name,
    n8nId: priorState.n8nId,
    status: verifiedActive ? 'deployed' : 'deployed_inactive',
    strategy_used: priorState.strategy,
    attempts: priorState.attempt_count,
    registry_updated: priorState.registry_updated || false,
    registry_write_error: priorState.registry_write_error || null,
    activation_succeeded: priorState.activation_succeeded || false,
    message: verifiedActive
      ? `Workflow "${priorState.workflow_name}" deployed and activated successfully (ID: ${priorState.n8nId})`
      : `Workflow "${priorState.workflow_name}" deployed but activation unconfirmed (ID: ${priorState.n8nId})`
  }
}];
```

**TRICKY PART 17:** Named-node fallback chain handles which upstream path ran.

---

## Workflow Settings

```json
{
  "executionOrder": "v1",
  "callerPolicy": "workflowsFromSameOwner",
  "saveDataSuccessExecution": "all",
  "saveDataErrorExecution": "all",
  "saveManualExecutions": true,
  "timezone": "US/Central"
}
```

`saveDataErrorExecution: "all"` is critical — preserves bad LLM JSON for debugging.

---

## Registry Entry for Nexus.Builder

Add to `workflow-registry.json` under `workflows` after deployment (Builder doesn't register itself):

```json
"Nexus.Builder": {
  "n8nId": null,
  "description": "Creates and deploys new n8n workflows on demand from a spec",
  "semanticDescription": "Generates or modifies n8n workflow JSON using the Cortex LLM, validates it (JSON parse, node whitelist, credential substitution, n8n API structural check), deploys via n8n REST API, activates the workflow, and updates the registry. Use this when no existing workflow covers the requested task.",
  "input": {
    "description":      { "type": "string",  "required": true,  "description": "What the workflow should do" },
    "domain":           { "type": "string",  "required": true,  "description": "Domain: email, llm, http, calendar, file, memory" },
    "required_inputs":  { "type": "object",  "required": true,  "description": "Input schema the new workflow must accept" },
    "expected_outputs": { "type": "object",  "required": true,  "description": "Output schema the new workflow must produce" },
    "similarity_match": { "type": "object",  "required": false, "description": "Existing workflow to modify (from Tier 3 routing)" }
  },
  "output": {
    "workflow_name":    { "type": "string",  "description": "Name of the created workflow" },
    "n8nId":            { "type": "string",  "description": "n8n workflow ID of deployed workflow (null on error)" },
    "status":           { "type": "string",  "enum": ["deployed", "deployed_inactive", "error"], "description": "Result status" },
    "strategy_used":    { "type": "string",  "enum": ["MODIFY", "GENERATE"], "description": "Which build strategy was used" },
    "attempts":         { "type": "number",  "description": "Number of LLM attempts made (1-3)" },
    "registry_updated": { "type": "boolean", "description": "Whether workflow-registry.json was updated" }
  },
  "tags": ["nexus", "builder", "meta", "orchestration"],
  "status": "unverified",
  "version": 1,
  "createdBy": "human",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "internal"
}
```

---

## Tricky Parts Consolidated Reference

| # | Node(s) | Issue | Solution |
|---|---------|-------|----------|
| 1 | Call Cortex LLM | `body` must be a string expression | Use `JSON.stringify({...})` in expression, NOT structured body UI |
| 2 | Call Cortex LLM | `localhost` vs `host.docker.internal` | Use `host.docker.internal:8001` to reach Cortex from inside container |
| 3 | Call Cortex LLM | Retry loop needs updated `messages` array | Messages accumulate error turns in item JSON |
| 4 | Call Cortex LLM | Network errors must not crash workflow | `continueOnFail: true` on all HTTP Request nodes |
| 5 | Parse and Validate | HTTP node replaces `$json` with response | Use `$('Validate Input').first().json` to recover state; guard `$('Inject Error Feedback')` with try/catch |
| 6 | Validate with n8n API | HTTP 400 crashes without fullResponse | `fullResponse: true` + `continueOnFail: true` |
| 7 | Validate with n8n API | Endpoint may not exist (404) | Parse n8n Validation treats 404 as pass |
| 8 | IF API Validation Passed | Two failure sources feed Inject Error Feedback | Both IF nodes connect FALSE output to nb07b input [0]; valid in n8n |
| 9 | Check Attempt Limit | Loop-back is backward edge in canvas | n8n allows backward connections; drag output connector back left |
| 10 | Check Attempt Limit | `attempt_count` accounting | Starts at 1, incremented before retry; `<= 3` = 3 LLM calls max |
| 11 | Format Final Output | Two upstream paths (happy + deploy failure) | Named node fallback chain: `$('Update Registry')` → `$('Deploy Handler')` |
| 12 | Deploy Handler | Need ID from response + prior state | Recover via `$('Parse n8n Validation').first().json` |
| 13 | Activate Workflow | 200 vs 204 response code variation | `fullResponse: true`, check `statusCode >= 200 && < 300` |
| 14 | Activate Workflow | Must be done for sub-workflow calls (n8n 2.x) | Non-negotiable — sub-workflows must be active |
| 15 | Update Registry | Race condition on concurrent Builder calls | Accepted limitation for Phase 3B |
| 16 | Update Registry | `require('fs')` and `require('crypto')` | Available when `N8n_BLOCK_ENV_ACCESS_IN_NODE=false` |
| 17 | Format Escalation Error | Terminal node — not connected to Format Final Output | Caller must handle both output shapes; check `status: 'error'` |
