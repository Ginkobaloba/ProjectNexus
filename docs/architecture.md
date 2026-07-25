# Nexus architecture

The architecture of record is being reshaped from the V1 "distributed cognition
fabric" (brainstem / cortex division of labor) to the V2 "family of models"
design.

- **V2 (proposed):** `docs/architecture_v2_family_of_models.md` — a household
  of individual AI family members with private per-member memory, shared
  household memory fed by the Jetson sensor pipeline, provenance-enforced
  privacy, and a model manager that swaps members on the 4090 via llama.cpp
  offloading.
- **V1 (implemented):** see `readme.md`, `docs/memory_system.md`, and
  `docs/node_details.md` for the brainstem/embedder/NAS/cortex stack that V2
  builds on.
