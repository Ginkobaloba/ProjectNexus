# nodes/nas-memory/semantic_store.py
from typing import Any, Dict, List, Tuple
import uuid

import chromadb
from chromadb.config import Settings as ChromaSettings

from .config import settings


_client = None
_collection = None


def get_client() -> chromadb.Client:
    global _client
    if _client is None:
        _client = chromadb.Client(
            ChromaSettings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=str(settings.chroma_persist_dir),
            )
        )
    return _client


def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=settings.chroma_collection_name
        )
    return _collection


def write_items(
    items: List[Tuple[str, str, List[float], Dict[str, Any]]]
) -> List[str]:
    """
    items: list of (id, text, embedding, metadata)
    Returns list of ids written.
    """
    col = get_collection()

    ids = [i[0] for i in items]
    documents = [i[1] for i in items]
    embeddings = [i[2] for i in items]
    metadatas = [i[3] for i in items]

    col.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    # Persist to disk
    get_client().persist()
    return ids


def search(
    query_embedding: List[float],
    top_k: int = 5,
) -> Tuple[List[str], List[str], List[float], List[Dict[str, Any]]]:
    col = get_collection()
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]

    # Chroma returns distance; convert to similarity-ish score
    scores = [1.0 - float(d) if d is not None else 0.0 for d in dists]

    return ids, docs, scores, metas
