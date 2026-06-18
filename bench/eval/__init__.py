# bench/eval/ - Model-quality eval harness for Project Nexus.
#
# Where the zero-byte scripts/benchmark_inference.py was always meant to live.
# Implements the task-family-1 (Nexus.Builder workflow synthesis) eval from
# NEXUS_PATH_TO_OUTPERFORM_v0.1.md: generate n8n workflow JSON from a spec, score
# it with a free programmatic verifier (JSON parse -> node whitelist -> n8n
# validate_workflow), and report valid@1 / valid@k with bootstrap CIs.
#
# cortex_client.py  - OpenAI-compatible client for the vLLM cortex (:8000)
# builder_prompt.py - the frozen Builder GENERATE prompt template
# verifier.py       - the verifier oracle (parse -> whitelist -> n8n validate)
# build_dataset.py  - (re)generates the frozen held-out Builder spec set
# run_builder_eval.py - the runner: baseline valid@1 vs verifier-guided best-of-N
# oracle_bridge/validate_oracle.js - long-lived bridge to n8n-mcp validate_workflow
__all__ = []
