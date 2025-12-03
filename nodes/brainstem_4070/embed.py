# nodes/brainstem_4070/embed.py
from typing import List

from sentence_transformers import SentenceTransformer
from .config import settings

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
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
