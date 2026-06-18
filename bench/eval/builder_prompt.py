# bench/eval/builder_prompt.py
"""
The frozen Nexus.Builder GENERATE prompt template.

This is a faithful port of the prompt that Nexus.Builder NODE 2 ("Validate Input")
builds for the GENERATE strategy (automation/docs/builder-architecture.md). Keeping
it here, verbatim and version-controlled, is the program design's rule: "Store every
prompt template in the repo. No per-run prompt tweaking." If the production Builder
prompt changes, bump PROMPT_VERSION and re-baseline -- a prompt change is a separate,
logged experiment, not a silent edit.

We only implement the GENERATE branch (no similarity_match), because the held-out
eval set is all from-scratch generation.
"""
from __future__ import annotations

from typing import Any, Dict, List

PROMPT_VERSION = "builder-generate-v1"

# Mirrors Nexus.Builder NODE 2 CREDENTIAL_MAP.
CREDENTIAL_MAP = {
    "email": "Gmail account",
    "calendar": "Google Calendar account",
    "sheets": "Google Sheets account",
    "drive": "Google Drive account",
}


def workflow_name(spec: Dict[str, Any]) -> str:
    """Domain.Operation name, mirroring NODE 2's naming logic.

    The spec carries an explicit `operation` so the name is deterministic; the
    production node derives it from the description, but a frozen dataset should
    not depend on that regex.
    """
    domain = str(spec["domain"])
    domain_cap = domain[:1].upper() + domain[1:]
    operation = spec.get("operation")
    if not operation:
        # Fallback mirrors NODE 2: first CapWord(s) in the description.
        import re

        m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", spec["description"])
        operation = m.group(0).replace(" ", "") if m else "Custom"
    return f"{domain_cap}.{operation}"


# Augmented variant: the faithful prompt verbatim PLUS rules that close the
# systematic representational gaps the base model shows under n8n's validate_workflow
# (nodes emitted without a unique `id`, empty Code-node bodies, credentials nested
# inside parameters). This is a logged prompt experiment, not an edit to the frozen
# production prompt -- it answers "what can test-time compute reach once the trivial,
# deploy-time-fixable blockers are removed?" Select it with prompt_variant="augmented".
_AUGMENT_RULES = (
    '6. Give EVERY node a unique "id" (a short non-empty string, distinct per node) '
    'and a unique "name".\n'
    '7. Every Code node (n8n-nodes-base.code) MUST include a non-empty "jsCode" string '
    'in its parameters that returns the items.\n'
    "8. Put any node credentials at the node level (a top-level \"credentials\" key on "
    "the node), never inside parameters.\n"
    "9. For service nodes (gmail, googleCalendar), set a valid \"operation\" parameter "
    "supported by that node.\n"
)

PROMPT_VARIANTS = ("faithful", "augmented")


def build_messages(
    spec: Dict[str, Any],
    node_whitelist: List[str],
    prompt_variant: str = "faithful",
) -> List[Dict[str, str]]:
    """Build the chat messages for one Builder GENERATE spec.

    spec keys: description, domain, required_inputs (object), expected_outputs (object),
    and optionally operation. prompt_variant selects the frozen production prompt
    ("faithful") or that prompt plus gap-closing rules ("augmented").
    """
    import json

    if prompt_variant not in PROMPT_VARIANTS:
        raise ValueError(f"prompt_variant must be one of {PROMPT_VARIANTS}")

    name = workflow_name(spec)
    domain = str(spec["domain"])
    credential_hint = CREDENTIAL_MAP.get(domain.lower())
    cred_line = (
        f'CREDENTIAL: Use credential named "{credential_hint}" for any OAuth nodes.\n'
        if credential_hint
        else ""
    )
    content = (
        "You are an expert n8n workflow architect. Generate a complete, valid n8n "
        "workflow JSON for the following spec.\n\n"
        f"WORKFLOW NAME: {name}\n"
        f"DOMAIN: {domain}\n"
        f"DESCRIPTION: {spec['description']}\n"
        f"REQUIRED INPUTS: {json.dumps(spec.get('required_inputs', {}), indent=2)}\n"
        f"EXPECTED OUTPUTS: {json.dumps(spec.get('expected_outputs', {}), indent=2)}\n"
        f"{cred_line}\n"
        "RULES:\n"
        "1. Start with an Execute Workflow Trigger node (type: "
        "n8n-nodes-base.executeWorkflowTrigger, typeVersion: 1.1, inputSource: "
        '"workflowInputs")\n'
        f"2. Only use node types from this whitelist: {json.dumps(node_whitelist)}\n"
        "3. End with a Set node (type: n8n-nodes-base.set, typeVersion: 3.4) named "
        '"Format Output" that outputs exactly the fields in EXPECTED OUTPUTS\n'
        "4. Include proper connections array\n"
        "5. Use typeVersion values: code=2, set=3.4, httpRequest=4.2, if=2, gmail=2, "
        "googleCalendar=2\n"
        f"{_AUGMENT_RULES if prompt_variant == 'augmented' else ''}"
        "\n"
        "Output ONLY the raw JSON object -- no markdown fences, no explanation. The "
        "entire response must be parseable by JSON.parse().\n\n"
        "Required top-level fields: name, nodes, connections, settings"
    )
    return [{"role": "user", "content": content}]
