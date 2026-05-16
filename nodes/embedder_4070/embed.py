# nodes/embedder_4070/embed.py
"""
Sentence-transformer wrapper. Lazy-loads the model on first use so the
service can boot fast and serve health checks before the model is
warm. All text in this service goes through this module so we always
know which model produced any given vector.
"""
from __future__ import annotations

from typing import List, TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_model: "SentenceTransformer | None" = None


def get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.model_name, device=settings.device)
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """L2-normalized embeddings. Normalization is important: Chroma's
    default distance is L2; with normalized vectors L2 distance
    monotonically tracks cosine similarity, which is what BGE was
    trained for."""
    model = get_model()
    emb = model.encode(
        texts,
        batch_size=16,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return emb.tolist()


def tokenize(text: str) -> List[int]:
    """Return token ids using the embedding model's own tokenizer. Used
    by the chunker for accurate length checks."""
    model = get_model()
    # HuggingFace tokenizers expose .encode -> list[int]
    return model.tokenizer.encode(text, add_special_tokens=False)


def dim() -> int:
    return get_model().get_sentence_embedding_dimension()
