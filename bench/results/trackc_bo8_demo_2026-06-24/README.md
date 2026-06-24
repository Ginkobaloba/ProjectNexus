# trackc_bo8_demo_2026-06-24

Reference artifact for Sprint 3d Card 6: the verifier-guided best-of-8 pipeline shape.

## What is in here

- `_generate_demo.py` — regenerator. Run from the repo root with `PYTHONPATH=.` to recreate every file in this folder byte-for-byte.
- `trackc_bo8_demo_code_pub_seed{0,1,2}.json` — baseline arm per-seed results (temp 0.0, n=1).
- `trackc_bo8_demo_code_pub_summary.json` — baseline arm task summary across seeds.
- `trackc_bo8_demo_code_pub_bestofn_seed{0,1,2}.json` — best-of-8 arm per-seed results, including every candidate's completion, per-candidate metrics, picked-candidate index, picked-reason.
- `trackc_bo8_demo_code_pub_bestofn_summary.json` — best-of-8 arm task summary with bootstrap CIs, selection-mode totals, cost-axis aggregate.
- `trackc_bo8_demo_code_pub_comparison.json` — the comparison record consumed by the chart and any future dashboard.
- `trackc_bo8_demo_code_pub_comparison.svg` — the two-bar chart with CI whiskers and the lift annotation. Renders inline in PRs.

## Why a stub provider

This folder is a pipeline shape demonstration, not a real Track C result. It uses `bench.eval.provider.StubProvider` with a deterministic canned-fn that returns wrong outputs for 4 of every 8 candidate seeds and correct outputs for the rest, so:

- the baseline arm scores 0.0 (the stub always returns the wrong-canned response)
- the best-of-8 arm scores 1.0 (the verifier always finds at least one correct candidate within N=8)
- the lift is the maximum possible (+100 pp) and the CIs are non-overlapping by construction

The deliberate +100 pp lift is the worst possible benchmark number to compare a real run against and the best possible shape verification for the artifact pipeline. Real Track C runs against the 4090 cortex emit the same file shapes; the numbers will be in the [0, 1] interior rather than at the endpoints.

## Regenerate

```powershell
cd C:\dev\project-nexus
$env:PYTHONPATH = '.'
python bench/results/trackc_bo8_demo_2026-06-24/_generate_demo.py
```

Expected output:

```
baseline mean: 0.0
best-of-8 mean: 1.0
lift: +100.00 pp
non-overlapping CI: True
```

## Real run command

Once the 4090 cortex is up, the equivalent against the real model is:

```powershell
cd C:\dev\project-nexus
$env:NEXUS_BENCH_BASE_URL = 'http://localhost:8000/v1'
$env:NEXUS_BENCH_MODEL    = 'cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit'
python -m bench.eval `
  --task code_pub `
  --seeds 3 `
  --best-of-n 8 `
  --bestofn-temperature 0.8 `
  --label trackc_bo8_2026-06-XX
```

Or the headline Builder run:

```powershell
python -m bench.eval `
  --task builder `
  --seeds 3 `
  --best-of-n 8 `
  --bestofn-temperature 0.8 `
  --label trackc_bo8_2026-06-XX
```

See `docs/sprints/SPRINT_3d_BENCH_PLAN_2026-06-21.md` section 6.
