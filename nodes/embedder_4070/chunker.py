# nodes/embedder_4070/chunker.py
"""
Recursive, markdown-aware chunker for conversational turns.

Why this and not the other obvious options:
  - Fixed-size with overlap: splits mid-sentence and mid-code-fence;
    each chunk loses semantic coherence. Cheapest, but worst retrieval.
  - Sentence-aware (spaCy/NLTK): solid for prose, struggles on code,
    lists, abbreviations; adds an NLP dep we do not otherwise need.
  - Semantic (split where embedding similarity drops): pays a per-turn
    embedding tax to find boundaries we will rarely use, since
    user+assistant pairs are usually one topic.
  - Recursive (this): respects natural structure (paragraphs, sentence
    breaks, then words, then characters) with markdown-aware separators
    so code fences and headings stay intact when possible. Free in
    compute, degrades gracefully on weird content.

Lock from Sprint 2 Chunk A:
  - threshold 450 tokens (don't chunk below this)
  - target 400 tokens per chunk
  - 50-token overlap between chunks
  - token counts come from the embedding model's own tokenizer so the
    count matches what the encoder will actually see
"""
from __future__ import annotations

from typing import Callable, List

# Separator priority. We try the largest natural boundary first and only
# fall back to finer ones when a candidate chunk is still too big.
# Order matters. Markdown-aware bits (code fences, headings) come early
# so we prefer splitting at the start of a fenced block over splitting
# at a paragraph break inside one.
_SEPARATORS: List[str] = [
    "\n```",     # fenced code start/end
    "\n### ",    # h3
    "\n## ",     # h2
    "\n# ",      # h1
    "\n\n",      # paragraph
    "\n",        # line
    ". ",        # sentence-ish
    " ",         # word
    "",          # character (last resort)
]


def _token_len(text: str, tokenize: Callable[[str], List[int]]) -> int:
    return len(tokenize(text))


def _split_on(text: str, sep: str) -> List[str]:
    """Split keeping the separator attached to the front of the next
    piece (so when we re-join we don't lose structure). Empty sep means
    character-level which is handled by the caller."""
    if sep == "":
        return list(text)
    if sep not in text:
        return [text]
    parts = text.split(sep)
    # re-attach the separator to all but the first piece
    out: List[str] = [parts[0]]
    for p in parts[1:]:
        out.append(sep + p)
    return [p for p in out if p]


def _recursive(
    text: str,
    target: int,
    tokenize: Callable[[str], List[int]],
    sep_idx: int = 0,
) -> List[str]:
    """Return a list of chunks each at or below `target` tokens, splitting
    on progressively finer separators."""
    if _token_len(text, tokenize) <= target:
        return [text]
    if sep_idx >= len(_SEPARATORS):
        return [text]  # cannot subdivide further; accept the oversize

    sep = _SEPARATORS[sep_idx]
    pieces = _split_on(text, sep)
    if len(pieces) == 1:
        # this separator did nothing; try the next one
        return _recursive(text, target, tokenize, sep_idx + 1)

    out: List[str] = []
    for piece in pieces:
        if _token_len(piece, tokenize) <= target:
            out.append(piece)
        else:
            out.extend(_recursive(piece, target, tokenize, sep_idx + 1))
    return out


def _pack(
    pieces: List[str],
    target: int,
    overlap: int,
    tokenize: Callable[[str], List[int]],
) -> List[str]:
    """Greedy packing: walk pieces, accumulate into a chunk until adding
    the next piece would exceed `target`, then emit and start a new
    chunk seeded with the last `overlap` tokens of the previous one.

    Overlap is measured in tokens, not characters, because that is what
    the encoder sees. We approximate the overlap window by walking
    backwards through pieces until we have at least `overlap` tokens.
    """
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if current:
            chunks.append("".join(current).strip())
            # seed next chunk with overlap from tail of `current`
            if overlap <= 0:
                current = []
                current_tokens = 0
                return
            tail: List[str] = []
            tail_tokens = 0
            for p in reversed(current):
                tail.insert(0, p)
                tail_tokens += _token_len(p, tokenize)
                if tail_tokens >= overlap:
                    break
            current = tail
            current_tokens = tail_tokens

    for piece in pieces:
        piece_tokens = _token_len(piece, tokenize)
        if current_tokens + piece_tokens > target and current:
            flush()
        current.append(piece)
        current_tokens += piece_tokens

    if current:
        chunks.append("".join(current).strip())
    return [c for c in chunks if c]


def chunk_turn(
    text: str,
    tokenize: Callable[[str], List[int]],
    threshold: int = 450,
    target: int = 400,
    overlap: int = 50,
) -> List[str]:
    """Public entry point. Returns the original text as a single-element
    list when it is under the threshold (the common case for short
    conversational turns). Otherwise splits recursively and re-packs to
    the target size with overlap.

    `tokenize` is a function that turns text into a list of token ids
    using the embedding model's tokenizer. We accept it as a callable so
    this module does not import sentence-transformers itself."""
    total = _token_len(text, tokenize)
    if total <= threshold:
        return [text]
    pieces = _recursive(text, target, tokenize)
    return _pack(pieces, target=target, overlap=overlap, tokenize=tokenize)
