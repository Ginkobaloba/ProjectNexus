# bench/eval/build_dataset.py
"""
(Re)generate the frozen held-out Builder spec set: datasets/builder_heldout_v1.jsonl.

The program design (NEXUS_PATH_TO_OUTPERFORM_v0.1.md, task family 1) calls for a
held-out set of 50 (spec -> workflow) cases. The honest data situation, audited at
build time: the episodic JSONL transcript log is ~empty (no logged Builder runs to
mine). So per the doc's explicit allowance ("synthesize tight test cases if not"),
the set is built from two in-distribution sources:

  1. The real automation/workflow-registry.json -- every atomic Domain.Operation
     workflow Nexus actually runs becomes a spec (description + I/O schema). These
     are the genuine target distribution.
  2. A curated set of synthesized specs in the same domains, to reach 50 and add
     variety the registry lacks (more http/code-shaped tasks).

"Held out" here means held out from any future Track A/B training: no model has
been fine-tuned, so the whole set is unseen for the Track C (test-time-compute)
experiment by construction. The output JSONL is the frozen artifact; this script
is the reproducible recipe. Re-running it must produce byte-identical output
(sorted, no timestamps), so the dataset is auditable.

Usage:
    python -m bench.eval.build_dataset [--registry PATH] [--out PATH] [--limit 50]
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

# Meta / compound workflows that are NOT atomic 4-node generations. The Builder
# generates atomic Domain.Operation workflows; these orchestrators would be a
# misrepresentative (and unfairly hard) target, so they are excluded from the set.
_DENYLIST = {
    "Nexus.Builder",
    "Nexus.Orchestrator",
    "Nexus.Agent",
    "Nexus.CortexTask",
    "Nexus.SMS.Send",
    "Nexus.Remind",
    "LLM.Council",
    "Cortex.DailySynthesis",
    "Cortex.BuildHealthCheck",
    "Brainstem.InboxTriage",
    "Portfolio.ProcessRepo",
    "Portfolio.ProcessAll",
}

# Domains that map cleanly to the Builder's 4-node atomic pattern.
_ALLOWED_DOMAINS = {"email", "web", "calendar", "drive", "sheets", "docs", "llm", "portfolio"}


def _slug(name: str) -> str:
    return name.replace(".", "_").lower()


def _spec_from_registry(name: str, entry: Dict[str, Any]) -> Dict[str, Any] | None:
    if name in _DENYLIST:
        return None
    if "." not in name:
        return None
    domain, *rest = name.split(".")
    domain = domain.lower()
    if domain not in _ALLOWED_DOMAINS:
        return None
    description = entry.get("description")
    if not description:
        return None
    operation = "".join(rest)
    return {
        "id": _slug(name),
        "domain": domain,
        "operation": operation,
        "description": description,
        "required_inputs": entry.get("input", {}) or {},
        "expected_outputs": entry.get("output", {}) or {},
        "source": "registry",
    }


# Synthesized in-distribution specs. Same Domain.Operation shape and whitelist
# constraints as the registry, covering http/code/branching patterns more heavily
# than the (mostly OAuth-node) registry does. Kept deliberately tight and concrete.
_SYNTHESIZED: List[Dict[str, Any]] = [
    {
        "domain": "web", "operation": "PostJson",
        "description": "POST a JSON payload to an arbitrary HTTPS URL and return the parsed response body and status code.",
        "required_inputs": {
            "url": {"type": "string", "required": True, "description": "Target HTTPS endpoint"},
            "payload": {"type": "object", "required": True, "description": "JSON body to send"},
        },
        "expected_outputs": {
            "status": {"type": "number", "description": "HTTP status code"},
            "body": {"type": "object", "description": "Parsed JSON response"},
        },
    },
    {
        "domain": "web", "operation": "HeadCheck",
        "description": "Make a HEAD request to a URL and report whether it is reachable (2xx) and its content type.",
        "required_inputs": {"url": {"type": "string", "required": True, "description": "URL to probe"}},
        "expected_outputs": {
            "reachable": {"type": "boolean", "description": "True if status is 2xx"},
            "content_type": {"type": "string", "description": "Content-Type header value"},
        },
    },
    {
        "domain": "web", "operation": "DownloadAndHash",
        "description": "Fetch the text body at a URL and return its SHA-256 hash and byte length.",
        "required_inputs": {"url": {"type": "string", "required": True, "description": "URL to fetch"}},
        "expected_outputs": {
            "sha256": {"type": "string", "description": "Hex SHA-256 of the body"},
            "length": {"type": "number", "description": "Body length in bytes"},
        },
    },
    {
        "domain": "llm", "operation": "Classify",
        "description": "Send text to the Cortex LLM and classify it into one of a provided list of labels, returning the chosen label.",
        "required_inputs": {
            "text": {"type": "string", "required": True, "description": "Text to classify"},
            "labels": {"type": "array", "required": True, "description": "Candidate labels"},
        },
        "expected_outputs": {"label": {"type": "string", "description": "Chosen label"}},
    },
    {
        "domain": "llm", "operation": "Translate",
        "description": "Translate input text into a target language using the Cortex LLM and return the translation.",
        "required_inputs": {
            "text": {"type": "string", "required": True, "description": "Source text"},
            "target_language": {"type": "string", "required": True, "description": "Target language name"},
        },
        "expected_outputs": {"translation": {"type": "string", "description": "Translated text"}},
    },
    {
        "domain": "llm", "operation": "Sentiment",
        "description": "Score the sentiment of input text via the Cortex LLM and return a label and a -1..1 score.",
        "required_inputs": {"text": {"type": "string", "required": True, "description": "Text to score"}},
        "expected_outputs": {
            "sentiment": {"type": "string", "description": "positive | neutral | negative"},
            "score": {"type": "number", "description": "Float in [-1, 1]"},
        },
    },
    {
        "domain": "web", "operation": "RetryFetch",
        "description": "Fetch a URL and, if the status is not 2xx, branch to a retry path that waits and tries once more, returning the final body.",
        "required_inputs": {"url": {"type": "string", "required": True, "description": "URL to fetch"}},
        "expected_outputs": {
            "body": {"type": "string", "description": "Response body"},
            "attempts": {"type": "number", "description": "Number of attempts made"},
        },
    },
    {
        "domain": "web", "operation": "RouteByStatus",
        "description": "Fetch a URL and route on the status code: success path on 2xx, error path otherwise, returning a normalized result object.",
        "required_inputs": {"url": {"type": "string", "required": True, "description": "URL to fetch"}},
        "expected_outputs": {
            "ok": {"type": "boolean", "description": "Whether the request succeeded"},
            "status": {"type": "number", "description": "HTTP status code"},
        },
    },
    {
        "domain": "email", "operation": "DraftDigest",
        "description": "Given a list of items, format a plain-text digest body and return it ready to send via Gmail.",
        "required_inputs": {"items": {"type": "array", "required": True, "description": "Items to include"}},
        "expected_outputs": {
            "subject": {"type": "string", "description": "Digest subject"},
            "body": {"type": "string", "description": "Formatted digest body"},
        },
    },
    {
        "domain": "calendar", "operation": "CountToday",
        "description": "List today's Google Calendar events and return the count and the title of the next event.",
        "required_inputs": {"calendar_id": {"type": "string", "required": True, "description": "Calendar to query"}},
        "expected_outputs": {
            "count": {"type": "number", "description": "Number of events today"},
            "next_title": {"type": "string", "description": "Title of the next event"},
        },
    },
    {
        "domain": "sheets", "operation": "SumColumn",
        "description": "Read a Google Sheet range and return the numeric sum of a named column.",
        "required_inputs": {
            "spreadsheet_id": {"type": "string", "required": True, "description": "Sheet id"},
            "column": {"type": "string", "required": True, "description": "Column header to sum"},
        },
        "expected_outputs": {"sum": {"type": "number", "description": "Sum of the column"}},
    },
    {
        "domain": "sheets", "operation": "FindRow",
        "description": "Read a Google Sheet and return the first row where a given column matches a value.",
        "required_inputs": {
            "spreadsheet_id": {"type": "string", "required": True, "description": "Sheet id"},
            "column": {"type": "string", "required": True, "description": "Column to match"},
            "value": {"type": "string", "required": True, "description": "Value to find"},
        },
        "expected_outputs": {"row": {"type": "object", "description": "Matching row, or null"}},
    },
    {
        "domain": "drive", "operation": "FindByName",
        "description": "Search Google Drive for files whose name contains a query string and return their ids and names.",
        "required_inputs": {"query": {"type": "string", "required": True, "description": "Name substring"}},
        "expected_outputs": {"files": {"type": "array", "description": "Matching files (id, name)"}},
    },
    {
        "domain": "web", "operation": "ExtractField",
        "description": "Fetch JSON from a URL and extract a single dot-path field, returning its value.",
        "required_inputs": {
            "url": {"type": "string", "required": True, "description": "JSON endpoint"},
            "path": {"type": "string", "required": True, "description": "Dot path, e.g. data.id"},
        },
        "expected_outputs": {"value": {"type": "string", "description": "Extracted value"}},
    },
    {
        "domain": "llm", "operation": "Keywords",
        "description": "Extract up to five keywords from input text using the Cortex LLM and return them as an array.",
        "required_inputs": {"text": {"type": "string", "required": True, "description": "Text to mine"}},
        "expected_outputs": {"keywords": {"type": "array", "description": "Up to five keywords"}},
    },
    {
        "domain": "web", "operation": "MergeTwo",
        "description": "Fetch two URLs in parallel, merge their JSON bodies into one object, and return the merged result.",
        "required_inputs": {
            "url_a": {"type": "string", "required": True, "description": "First JSON endpoint"},
            "url_b": {"type": "string", "required": True, "description": "Second JSON endpoint"},
        },
        "expected_outputs": {"merged": {"type": "object", "description": "Merged JSON object"}},
    },
    {
        "domain": "docs", "operation": "WordCount",
        "description": "Read a Google Doc by id and return its word count and character count.",
        "required_inputs": {"document_id": {"type": "string", "required": True, "description": "Doc id"}},
        "expected_outputs": {
            "words": {"type": "number", "description": "Word count"},
            "chars": {"type": "number", "description": "Character count"},
        },
    },
    {
        "domain": "email", "operation": "CountUnread",
        "description": "Search Gmail for unread messages matching a query and return the count.",
        "required_inputs": {"query": {"type": "string", "required": True, "description": "Gmail search query"}},
        "expected_outputs": {"unread": {"type": "number", "description": "Unread message count"}},
    },
    {
        "domain": "web", "operation": "GetWithAuth",
        "description": "GET a URL with a Bearer token header and return the parsed JSON body and status code.",
        "required_inputs": {
            "url": {"type": "string", "required": True, "description": "Target endpoint"},
            "token": {"type": "string", "required": True, "description": "Bearer token"},
        },
        "expected_outputs": {
            "status": {"type": "number", "description": "HTTP status code"},
            "body": {"type": "object", "description": "Parsed JSON response"},
        },
    },
    {
        "domain": "web", "operation": "FilterList",
        "description": "Fetch a JSON array from a URL and return only the items whose named field equals a given value.",
        "required_inputs": {
            "url": {"type": "string", "required": True, "description": "Endpoint returning a JSON array"},
            "field": {"type": "string", "required": True, "description": "Field to match on"},
            "value": {"type": "string", "required": True, "description": "Value to keep"},
        },
        "expected_outputs": {"items": {"type": "array", "description": "Filtered items"}},
    },
]


def _finish_synth(s: Dict[str, Any]) -> Dict[str, Any]:
    s = dict(s)
    s["id"] = _slug(f"{s['domain'].capitalize()}.{s['operation']}")
    s["source"] = "synthesized"
    return s


def build(registry_path: str, limit: int = 50) -> List[Dict[str, Any]]:
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    specs: List[Dict[str, Any]] = []
    seen = set()
    # Registry first (the real target distribution), sorted by name for stability.
    for name in sorted((registry.get("workflows") or {}).keys()):
        spec = _spec_from_registry(name, registry["workflows"][name])
        if spec and spec["id"] not in seen:
            specs.append(spec)
            seen.add(spec["id"])
    # Then synthesized, to reach `limit` and add http/code variety.
    for raw in _SYNTHESIZED:
        spec = _finish_synth(raw)
        if spec["id"] not in seen:
            specs.append(spec)
            seen.add(spec["id"])
    specs.sort(key=lambda s: s["id"])
    return specs[:limit]


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", ".."))
    ap = argparse.ArgumentParser(description="Build the frozen held-out Builder spec set")
    ap.add_argument(
        "--registry",
        default=os.path.join(repo_root, "automation", "workflow-registry.json"),
    )
    ap.add_argument("--out", default=os.path.join(here, "datasets", "builder_heldout_v1.jsonl"))
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    specs = build(args.registry, args.limit)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for s in specs:
            f.write(json.dumps(s, sort_keys=True, ensure_ascii=True) + "\n")

    n_reg = sum(1 for s in specs if s["source"] == "registry")
    n_syn = len(specs) - n_reg
    print(f"wrote {len(specs)} specs to {args.out}  (registry={n_reg}, synthesized={n_syn})")
    if len(specs) < args.limit:
        print(
            f"WARNING: only {len(specs)} specs available; wanted {args.limit}. "
            f"Add more synthesized specs to reach the target."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
