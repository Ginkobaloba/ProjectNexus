# nodes/embedder_4070
"""
Embedder service. Separate container from the brainstem, owns:
    - the sentence-transformer model (BGE-small)
    - the chunking pipeline (recursive, markdown-aware)
    - the Chroma persistent collection `memory`

Brainstem talks to this service over localhost HTTP. See `server.py` for
the API contract and `docs/memory_system.md` for the design write-up.
"""
