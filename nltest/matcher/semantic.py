"""Semantic matching via sentence embeddings -- the real replacement for a
hand-maintained synonym dictionary.

Instead of requiring someone to anticipate and hardcode every way a concept
might be phrased ("save" / "persist" / "store" / "create a new record" /
"bulk upload a CSV" / ...), this encodes the query and every test's
descriptive text into vectors with a small pretrained sentence-embedding
model and compares them by cosine similarity. Two phrases that mean the same
thing end up close together in that vector space regardless of which words
were used, without anyone having to enumerate the relationship.

This is an OPTIONAL layer: it activates automatically if the
`sentence-transformers` package is installed (`pip install nltest[semantic]`)
and a model can be loaded (first use downloads a small ~90MB model from
Hugging Face and caches it locally; after that it's fully offline). If it's
not installed, or the model can't be loaded (no network on first run, etc.),
nltest degrades gracefully to lexical/tag/fuzzy matching only -- it does not
fall back to a hardcoded word-to-word dictionary.
"""

from __future__ import annotations

import functools
import hashlib
import os

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_NAME = os.environ.get("NLTEST_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)

_warned_unavailable = False


@functools.lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        return SentenceTransformer(MODEL_NAME)
    except Exception:
        # No network on first use, corrupt cache, unsupported platform, etc.
        # -- semantic matching just isn't available this run.
        return None


def is_available() -> bool:
    return _load_model() is not None


def warn_if_unavailable(announce) -> None:
    """Print a one-time, non-fatal notice explaining degraded matching mode,
    so users understand *why* recall might be lower rather than silently
    wondering why a differently-worded query didn't match."""
    global _warned_unavailable
    if _warned_unavailable or is_available():
        return
    _warned_unavailable = True
    try:
        import sentence_transformers  # noqa: F401

        reason = "the embedding model couldn't be loaded (no network on first use?)"
    except ImportError:
        reason = "the optional `sentence-transformers` package isn't installed (`pip install nltest[semantic]`)"
    announce(
        f"[dim]Semantic matching is unavailable ({reason}) -- falling back to tag/name/fuzzy matching only. "
        "Differently-worded queries for the same feature may not be found.[/dim]"
    )


def embed(texts: list[str]):
    """Encode `texts` into L2-normalized embedding vectors, or None if
    semantic matching isn't available."""
    model = _load_model()
    if model is None or not texts:
        return None
    return model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)


_CORPUS_CACHE: dict[str, "object"] = {}


def _corpus_key(texts: list[str]) -> str:
    joined = "\x1f".join(texts)
    return hashlib.sha1(joined.encode("utf-8", errors="ignore")).hexdigest()


def embed_corpus_cached(texts: list[str]):
    """Like `embed`, but memoized per unique corpus (by content hash) for the
    lifetime of the process -- so resolving multiple clauses of a compound
    query against the same set of tests only encodes the corpus once."""
    if not texts:
        return None
    key = _corpus_key(texts)
    if key not in _CORPUS_CACHE:
        _CORPUS_CACHE[key] = embed(texts)
    return _CORPUS_CACHE[key]


def similarities(query: str, corpus_embeddings) -> list[float] | None:
    """Cosine similarity of `query` against each row of `corpus_embeddings`
    (already L2-normalized), or None if semantic matching isn't available."""
    if corpus_embeddings is None:
        return None
    query_embedding = embed([query])
    if query_embedding is None:
        return None
    return (corpus_embeddings @ query_embedding[0]).tolist()
