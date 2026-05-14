# nodes/brainstem_4070/embed.py
from typing import TYPE_CHECKING, List

from .config import settings

if TYPE_CHECKING:  # import only for type checkers, not at runtime
    from sentence_transformers import SentenceTransformer

# sentence-transformers (and torch) is a heavy import. Keep it lazy so the
# service can start and serve the Cortex-relay path without paying the cost
# of loading the embedding stack until an embedding endpoint is actually hit.
_model: "SentenceTransformer | None" = None


def get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.model_name, device=settings.device)
    return _model


def embed_texts(texts: List[str]) -> List[list[float]]:
    """
    Returns L2-normalized embeddings for a list of texts.
    """
    model = get_model()
    emb = model.encode(
        texts,
        batch_size=16,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return emb.tolist()
