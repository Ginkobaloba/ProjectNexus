# Archived: n8n-mcp integration

When this repo was first scaffolded, an upstream tool called
`n8n-mcp` (github.com/czlonkowski/n8n-mcp) was vendored under
`Nexus_N8N-MCP/` to let an LLM author and run n8n workflows. That
was the right call at the time: tool-use and connector ecosystems
inside frontier LLMs were thin, and n8n filled a real gap for
"LLM defines its own workflow" experiments.

That gap has since closed. Anthropic and OpenAI shipped first-class
tool calling, connectors, and routine systems that make most of what
`n8n-mcp` enabled redundant for this project. Keeping the vendored
clone in the working tree adds noise without adding capability.

State as of this commit:

- The `Nexus_N8N-MCP/` directory is preserved on disk but ignored
  by git (see `.gitignore`). Nothing is deleted; the upstream
  repo's history lives in its own `.git` directory inside it.
- The `Nexus-Automation-Node/` directory holds runtime state for
  the n8n container itself and is also ignored.
- One workflow export, `n8n_workflow.json` (Hybrid Email Triage
  Pipeline), is tracked because it's a project artifact, not an
  upstream copy.

If we ever need to reach for the n8n-mcp stack again, the directory
is still there. If we want to clean it up entirely later, `rm -rf`
on the ignored directories is safe; nothing in this repo depends on
their contents.

Direction going forward: build agentic capability via the LLM's
native tool calling against our own services (brainstem, NAS,
cortex), not via an external workflow engine.
