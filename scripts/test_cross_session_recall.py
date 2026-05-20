"""
Sprint 2 done-criterion test: cross-session recall.

Writes a synthetic 5-turn conversation in session A, simulates a full
service restart by tearing down and recreating the Chroma persistent
client at the same on-disk path, then issues a query from session B
that references a specific fact from session A turn 3. Asserts that
turn 3's `parent_turn_id` appears in the top-5 retrieval results.

Run directly:
    python scripts/test_cross_session_recall.py

Exits 0 on success, non-zero with a diagnostic on failure. The script
exercises the same chunker, embedding model, and Chroma store the
production embedder service uses (just via direct import instead of
HTTP), so a pass here is a real pass of the Sprint 2 done-criterion
modulo the FastAPI wrapper.
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "nodes"))
sys.path.insert(0, str(REPO_ROOT))


def _concat(user: str, assistant: str) -> str:
    return f"### User\n{user.strip()}\n\n### Assistant\n{assistant.strip()}"


def _write_turn(
    *,
    session_id: str,
    turn_idx: int,
    user_text: str,
    assistant_text: str,
) -> str:
    """Mirror the embedder service's /memory/write logic. Returns the
    parent_turn_id for use in assertions."""
    from embedder_4070 import chroma_store
    from embedder_4070.chunker import chunk_turn
    from embedder_4070.embed import embed_texts, tokenize
    from embedder_4070.config import settings

    parent_turn_id = f"{session_id}:{turn_idx}"
    body = _concat(user_text, assistant_text)
    chunks = chunk_turn(
        body,
        tokenize=tokenize,
        threshold=settings.chunk_threshold_tokens,
        target=settings.chunk_target_tokens,
        overlap=settings.chunk_overlap_tokens,
    )
    embeddings = embed_texts(chunks)
    ids = [f"{parent_turn_id}:{i}" for i in range(len(chunks))]
    metas = [
        {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "ts": datetime.now(timezone.utc).isoformat(),
            "model_used": "test-model",
            "user_token_count": 0,
            "assistant_token_count": 0,
            "source_service": "test_cross_session_recall",
            "tool_calls_present": False,
            "chunk_idx": i,
            "chunk_total": len(chunks),
            "parent_turn_id": parent_turn_id,
        }
        for i in range(len(chunks))
    ]
    chroma_store.add_documents(
        ids=ids, documents=chunks, embeddings=embeddings, metadatas=metas
    )
    return parent_turn_id


def _query(query_text: str, k: int = 5) -> List[Dict]:
    from embedder_4070 import chroma_store
    from embedder_4070.embed import embed_texts

    vec = embed_texts([query_text])[0]
    return chroma_store.query(vec, k=k, where=None)


def _reset_chroma_module_state() -> None:
    """Force the embedder modules to release the Chroma client so the
    next call constructs a fresh one. This is what simulates a service
    restart: the persistent files on disk are untouched, but every
    in-memory handle to them is gone."""
    import embedder_4070.chroma_store as cs
    # The PersistentClient holds open handles; resetting the module
    # globals is sufficient for our purposes (the OS releases the
    # underlying files when the client is GC'd).
    cs._client = None
    cs._collection = None


def main() -> int:
    # Use a temp dir for Chroma so a failed test never pollutes
    # the real /chroma volume.
    persist_dir = Path(tempfile.mkdtemp(prefix="nexus_recall_test_"))
    os.environ["EMBEDDER_CHROMA_PERSIST_DIR"] = str(persist_dir)
    os.environ["EMBEDDER_CHROMA_COLLECTION"] = "memory_test"

    try:
        # ---- Session A: write 5 turns -----------------------------
        session_a = "sess_AAAAAAAAAAAA"
        turn_ids: List[str] = []

        conversation = [
            (
                "Hey, my dog's name is Pepper and she's a border collie mix.",
                "Got it, Pepper the border collie mix.",
            ),
            (
                "What's a good park near downtown?",
                "Lincoln Park is well-regarded and central.",
            ),
            (
                "Side note for the record: I drive a 2014 Subaru Outback Limited "
                "in metallic blue, license plate ends in 7QF. Just so you know "
                "when I mention the car later.",
                "Noted, 2014 Subaru Outback Limited, metallic blue, plate ending 7QF.",
            ),
            (
                "Can you summarize the second law of thermodynamics in one line?",
                "Entropy of an isolated system never decreases.",
            ),
            (
                "Tell me a quick dad joke.",
                "Why did the scarecrow win an award? Because he was outstanding in his field.",
            ),
        ]

        for i, (u, a) in enumerate(conversation):
            tid = _write_turn(
                session_id=session_a,
                turn_idx=i,
                user_text=u,
                assistant_text=a,
            )
            turn_ids.append(tid)

        target_turn = turn_ids[2]  # the "what car do I drive" turn
        print(f"[setup] wrote 5 turns to {session_a}; target turn = {target_turn}")

        # ---- Simulate service restart -----------------------------
        _reset_chroma_module_state()
        # Force a fresh re-import path: re-resolve the persistent client
        # against the same on-disk directory. The data must still be
        # there.
        from embedder_4070 import chroma_store
        on_disk_count = chroma_store.count()
        print(f"[restart] re-opened Chroma; on-disk count = {on_disk_count}")
        assert on_disk_count >= 5, (
            f"Expected at least 5 docs after restart, got {on_disk_count}. "
            "Persistence is broken."
        )

        # ---- Session B: query that targets turn 3 -----------------
        session_b = "sess_BBBBBBBBBBBB"  # noqa: F841 (not used in query, but represents the new session)
        query_text = "What car do I drive?"
        matches = _query(query_text, k=5)

        print(f"[query] '{query_text}' returned {len(matches)} matches:")
        for i, m in enumerate(matches, start=1):
            meta = m.get("metadata") or {}
            print(
                f"  #{i}  dist={m.get('distance'):.4f}  "
                f"parent={meta.get('parent_turn_id')}  turn_idx={meta.get('turn_idx')}"
            )

        hit_ids = {(m.get("metadata") or {}).get("parent_turn_id") for m in matches}
        if target_turn not in hit_ids:
            print(
                f"\nFAIL: target parent_turn_id {target_turn} not in top-5 hits "
                f"{sorted(x for x in hit_ids if x)}"
            )
            return 1

        # Bonus check: target should be the #1 hit, not just within top-5.
        # If it isn't, the test still passes but we surface the rank.
        top1 = (matches[0].get("metadata") or {}).get("parent_turn_id") if matches else None
        if top1 == target_turn:
            print(f"\nPASS: target {target_turn} retrieved as top-1.")
        else:
            target_rank = None
            for i, m in enumerate(matches, start=1):
                if (m.get("metadata") or {}).get("parent_turn_id") == target_turn:
                    target_rank = i
                    break
            print(
                f"\nPASS: target {target_turn} in top-5 at rank {target_rank}. "
                f"(top-1 was {top1}.)"
            )
        return 0
    finally:
        # Always release Chroma handles before deleting the dir.
        _reset_chroma_module_state()
        shutil.rmtree(persist_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
