# nodes/brainstem_4070/embed.py
"""
DEPRECATED as of Sprint 2 Chunk A.

The brainstem no longer owns the embedding model. Embedding lives in
the embedder service (see `nodes/embedder_4070/`). Use
`brainstem_4070.embedder_client.EmbedderClient` instead, which is what
`server.py` does.

This stub stays in place for one release so any straggler import fails
loudly with a useful pointer instead of silently importing a stale
sentence-transformers stack into the brainstem.
"""
from typing import List


class _DeprecatedEmbedError(RuntimeError):
    pass


def get_model():  # pragma: no cover
    raise _DeprecatedEmbedError(
        "brainstem_4070.embed is deprecated. Use brainstem_4070.embedder_client "
        "which talks to the embedder service over HTTP."
    )


def embed_texts(texts: List[str]):  # pragma: no cover
    raise _DeprecatedEmbedError(
        "brainstem_4070.embed.embed_texts is deprecated. Use "
        "brainstem_4070.embedder_client.EmbedderClient.embed(texts) instead."
    )
