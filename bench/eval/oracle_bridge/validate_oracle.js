#!/usr/bin/env node
/*
 * validate_oracle.js -- faithful, long-lived bridge to n8n-mcp's `validate_workflow`.
 *
 * This is the verifier oracle for the Track C Builder eval. It instantiates the
 * exact same WorkflowValidator the n8n-mcp `validate_workflow` MCP tool uses
 * (see Nexus_N8N-MCP/dist/mcp/server.js -> validateWorkflow), backed by the real
 * 534-node SQLite database (data/nodes.db). It does NOT require a live n8n
 * instance -- this is the "free programmatic verifier" the program design calls
 * for (parse -> whitelist happen on the Python side; this stage is n8n validate).
 *
 * Protocol: newline-delimited JSON on stdin, one verdict line per request on
 * stdout. The DB is loaded once, so per-candidate cost is just validation, not
 * Node startup. Designed to be driven by bench/eval/verifier.py.
 *
 *   stdin  : {"id": "<spec_id>#<k>", "workflow": {<n8n workflow json>}, "profile": "runtime"}
 *   stdout : {"id": ..., "valid": bool, "errorCount": int, "warningCount": int,
 *             "errors": [{node, message}], "summary": {...}}
 *   ready  : on startup, emits {"ready": true, "dbNodes": <count>} once the DB
 *            is open, so the caller can block until the oracle is warm.
 *
 * Env:
 *   N8N_MCP_DIR  absolute path to the Nexus_N8N-MCP checkout (has dist/ + data/)
 *   NODE_DB_PATH override path to nodes.db (defaults to <N8N_MCP_DIR>/data/nodes.db)
 */
'use strict';

const path = require('path');
const readline = require('readline');

const MCP_DIR = process.env.N8N_MCP_DIR;
if (!MCP_DIR) {
  process.stderr.write('FATAL: N8N_MCP_DIR env var is required\n');
  process.exit(2);
}
const DB_PATH = process.env.NODE_DB_PATH || path.join(MCP_DIR, 'data', 'nodes.db');
const DIST = path.join(MCP_DIR, 'dist');

// Require the built modules by absolute path. Their own `require('better-sqlite3')`
// etc. resolve against Nexus_N8N-MCP/node_modules because the files live there.
const { createDatabaseAdapter } = require(path.join(DIST, 'database', 'database-adapter'));
const { NodeRepository } = require(path.join(DIST, 'database', 'node-repository'));
const { EnhancedConfigValidator } = require(path.join(DIST, 'services', 'enhanced-config-validator'));
const { WorkflowValidator } = require(path.join(DIST, 'services', 'workflow-validator'));

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

async function main() {
  let repository;
  try {
    const db = await createDatabaseAdapter(DB_PATH);
    repository = new NodeRepository(db);
    // Same similarity init the MCP server does on its in-memory path.
    try { EnhancedConfigValidator.initializeSimilarityServices(repository); } catch (_) { /* non-fatal */ }
  } catch (err) {
    emit({ ready: false, error: `DB init failed: ${err && err.message ? err.message : String(err)}` });
    process.exit(3);
  }

  let dbNodes = -1;
  try { dbNodes = repository.getNodeCount ? repository.getNodeCount() : -1; } catch (_) { /* optional */ }
  emit({ ready: true, dbNodes, dbPath: DB_PATH });

  const rl = readline.createInterface({ input: process.stdin, terminal: false });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let req;
    try {
      req = JSON.parse(trimmed);
    } catch (e) {
      emit({ id: null, valid: false, fatal: 'bad_request_json', errors: [{ node: 'bridge', message: e.message }] });
      continue;
    }
    const id = req.id !== undefined ? req.id : null;
    const profile = req.profile || 'runtime';
    try {
      const validator = new WorkflowValidator(repository, EnhancedConfigValidator);
      const result = await validator.validateWorkflow(req.workflow, {
        validateNodes: true,
        validateConnections: true,
        validateExpressions: true,
        profile,
      });
      emit({
        id,
        valid: result.valid,
        errorCount: result.errors.length,
        warningCount: result.warnings.length,
        errors: result.errors.slice(0, 8).map((e) => ({ node: e.nodeName || 'workflow', message: e.message })),
        summary: {
          totalNodes: result.statistics.totalNodes,
          triggerNodes: result.statistics.triggerNodes,
          validConnections: result.statistics.validConnections,
          invalidConnections: result.statistics.invalidConnections,
        },
      });
    } catch (err) {
      emit({ id, valid: false, error: err && err.message ? err.message : String(err) });
    }
  }
}

main().catch((err) => {
  process.stderr.write(`FATAL: ${err && err.stack ? err.stack : String(err)}\n`);
  process.exit(1);
});
