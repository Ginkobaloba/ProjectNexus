# bench/eval/datasets

Frozen problem sets used by `bench.eval` tasks. Every dataset is versioned in
its filename (e.g. `_v1`, `_v2`) so re-running an old baseline against the same
file produces the same problems byte-for-byte.

## Files

### builder_skeleton_v1.jsonl

Five-example placeholder set for Task 1 (Builder). Each record:

    {
      "problem_id": "bld_xxx",
      "spec": "<natural-language workflow specification>",
      "reference": {
        "required_nodes": ["webhook", "set", ...],
        "min_nodes": 3
      },
      "meta": {"family": "..."}
    }

This is intentionally small. Card 5 (baseline_v1 run) will swap this for a
curated held-out set of 50 examples once the dataset committee signs off.
The skeleton ships this file so the wiring is end-to-end testable and the
runner can produce a valid SeedResult against a real or stub provider.

### cache/

Local HF Datasets cache for Task 5 (HumanEval+/MBPP). Gitignored. First run
populates this via `datasets.load_dataset`. See `bench/eval/tasks/code_pub.py`
for the dataset IDs and license attribution.

## How to add a dataset

1. Write the JSONL file with the schema your task expects.
2. Reference it by relative path inside the task module's `load_problems`.
3. Bump the `_vN` suffix when content changes; never edit a published version
   in place.
