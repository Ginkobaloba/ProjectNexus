"""
Standalone latency probe for the embedder primitives. Not part of the
production metric harness; this is a one-shot for the Sprint 2 handoff
so we have ballpark numbers without needing a running brainstem +
Cortex + thin-client stack.

Measures:
  - cold embed_texts() on a single 50-word turn (first call, model load
    + first inference)
  - warm embed_texts() on the same turn (subsequent calls)
  - chunk_turn() on the same turn (should return one chunk; cheap)
  - chroma_store.add_documents() write of one chunk
  - chroma_store.query() against a one-doc collection

Run from the repo root:
    python scripts/bench_embedder_primitives.py
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "nodes"))


def main() -> int:
    persist_dir = Path(tempfile.mkdtemp(prefix="nexus_bench_"))
    os.environ["EMBEDDER_CHROMA_PERSIST_DIR"] = str(persist_dir)
    os.environ["EMBEDDER_CHROMA_COLLECTION"] = "memory_bench"

    try:
        from embedder_4070.chunker import chunk_turn
        from embedder_4070 import chroma_store
        from embedder_4070.embed import embed_texts, tokenize
        from embedder_4070.config import settings

        sample = (
            "### User\nI'm thinking about how the brainstem should handle "
            "retrieve-before-generate. Should the retrieved turns be a "
            "system message or a prepended user message?\n\n### Assistant\n"
            "System message keeps user intent clean and lets the model "
            "treat the prior context as instruction-like background."
        )

        t = time.perf_counter()
        embed_texts([sample])
        cold_ms = (time.perf_counter() - t) * 1000

        timings = []
        for _ in range(5):
            t = time.perf_counter()
            embed_texts([sample])
            timings.append((time.perf_counter() - t) * 1000)
        warm_ms = sum(timings) / len(timings)

        t = time.perf_counter()
        chunks = chunk_turn(
            sample, tokenize=tokenize,
            threshold=settings.chunk_threshold_tokens,
            target=settings.chunk_target_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
        chunk_ms = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        emb = embed_texts(chunks)
        chroma_store.add_documents(
            ids=["bench:0:0"],
            documents=chunks,
            embeddings=emb,
            metadatas=[{"session_id": "bench", "turn_idx": 0,
                        "parent_turn_id": "bench:0", "chunk_idx": 0,
                        "chunk_total": 1}],
        )
        write_ms = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        chroma_store.query(emb[0], k=5, where=None)
        query_ms = (time.perf_counter() - t) * 1000

        print(f"cold embed_texts (1 turn): {cold_ms:.1f} ms  (includes model load)")
        print(f"warm embed_texts (1 turn, avg of 5): {warm_ms:.1f} ms")
        print(f"chunk_turn (1 turn, under threshold): {chunk_ms:.3f} ms")
        print(f"memory_write (encode + chroma.add, 1 chunk): {write_ms:.1f} ms")
        print(f"memory_query (encode + chroma.query, k=5): {query_ms:.1f} ms")
        return 0
    finally:
        try:
            import embedder_4070.chroma_store as cs
            cs._client = None
            cs._collection = None
        except Exception:
            pass
        shutil.rmtree(persist_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
