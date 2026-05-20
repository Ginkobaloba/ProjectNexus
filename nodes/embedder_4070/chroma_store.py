# nodes/embedder_4070/chroma_store.py
"""
Chroma persistent client wrapper. Single `memory` collection, persistent
directory mounted to the `chroma_data` named volume so the data survives
container restarts. We pass embeddings in directly (computed by our own
BGE model) rather than letting Chroma compute them, so the model used
for write and the model used for query are guaranteed to be the same.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    import chromadb

_client: "chromadb.api.ClientAPI | None" = None
_collection = None


def get_client() -> "chromadb.api.ClientAPI":
    global _client
    if _client is None:
        import chromadb
        _client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _client


def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=settings.chroma_collection,
            # cosine works well with normalized BGE embeddings and is
            # the natural fit for sentence-transformer retrieval.
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def add_documents(
    ids: List[str],
    documents: List[str],
    embeddings: List[List[float]],
    metadatas: List[Dict[str, Any]],
) -> None:
    """Add a batch of documents. All four lists must have the same length."""
    if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
        raise ValueError("ids/documents/embeddings/metadatas length mismatch")
    if not ids:
        return
    coll = get_collection()
    coll.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def query(
    embedding: List[float],
    k: int = 5,
    where: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Top-k nearest neighbors. `where` is a Chroma metadata filter; pass
    None for no filter (the cross-session retrieval path)."""
    coll = get_collection()
    res = coll.query(
        query_embeddings=[embedding],
        n_results=k,
        where=where or None,
    )
    out: List[Dict[str, Any]] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, doc, meta, dist in zip(ids, docs, metas, dists):
        out.append({
            "id": i,
            "text": doc,
            "metadata": meta or {},
            "distance": float(dist) if dist is not None else None,
        })
    return out


def count() -> int:
    return get_collection().count()
