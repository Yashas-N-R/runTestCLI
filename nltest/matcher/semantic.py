"""Semantic matching via sentence embeddings -- the real replacement for a
hand-maintained synonym dictionary.

Instead of requiring someone to anticipate and hardcode every way a concept
might be phrased ("save" / "persist" / "store" / "create a new record" /
"bulk upload a CSV" / ...), this encodes the query and every test's
descriptive text into vectors with a small pretrained sentence-embedding
model and compares them by cosine similarity. Two phrases that mean the same
thing end up close together in that vector space regardless of which words
were used, without anyone having to enumerate the relationship.

The PyPI wheel bundles the MiniLM model locally so ``pip install nltest`` works
fully offline with no Hugging Face download. Set ``NLTEST_ALLOW_NETWORK=1``
only if you need to fetch a custom model via ``NLTEST_EMBEDDING_MODEL``.
"""

from __future__ import annotations

import functools
import hashlib
import os

from nltest.security import network_allowed

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_NAME = os.environ.get("NLTEST_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)

_warned_unavailable = False


def _bundled_model_path() -> str | None:
    pkg_dir = os.path.dirname(os.path.dirname(__file__))
    candidate = os.path.join(pkg_dir, "bundled_models", "all-MiniLM-L6-v2")
    if os.path.isfile(os.path.join(candidate, "config.json")):
        return candidate
    return None


def _resolve_model_source() -> str:
    if os.environ.get("NLTEST_EMBEDDING_MODEL"):
        source = MODEL_NAME
        if not network_allowed() and not os.path.isdir(source):
            raise RuntimeError(
                "NLTEST_EMBEDDING_MODEL points to a remote/custom model but "
                "NLTEST_ALLOW_NETWORK is not set. nltest does not phone home by default."
            )
        return source
    bundled = _bundled_model_path()
    if bundled:
        return bundled
    if network_allowed():
        return DEFAULT_MODEL_NAME
    raise RuntimeError(
        "Bundled embedding model is missing and NLTEST_ALLOW_NETWORK is not set. "
        "Reinstall nltest from PyPI or set NLTEST_ALLOW_NETWORK=1 to download the model once."
    )


@functools.lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        source = _resolve_model_source()
        # Offline-first: never hit Hugging Face Hub unless explicitly allowed.
        local_only = not network_allowed() and not os.environ.get("NLTEST_EMBEDDING_MODEL")
        return SentenceTransformer(source, local_files_only=local_only)
    except Exception:
        return None


def is_available() -> bool:
    return _load_model() is not None


def warn_if_unavailable(announce) -> None:
    """Print a one-time, non-fatal notice explaining degraded matching mode."""
    global _warned_unavailable
    if _warned_unavailable or is_available():
        return
    _warned_unavailable = True
    try:
        import sentence_transformers  # noqa: F401

        if _bundled_model_path() is None and not network_allowed():
            reason = "the bundled embedding model is missing and network access is disabled (set NLTEST_ALLOW_NETWORK=1 to download once)"
        else:
            reason = "the embedding model couldn't be loaded"
    except ImportError:
        reason = "sentence-transformers is not installed"
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
    lifetime of the process."""
    if not texts:
        return None
    key = _corpus_key(texts)
    if key not in _CORPUS_CACHE:
        _CORPUS_CACHE[key] = embed(texts)
    return _CORPUS_CACHE[key]


def similarities(query: str, corpus_embeddings) -> list[float] | None:
    """Cosine similarity of `query` against each row of `corpus_embeddings`."""
    if corpus_embeddings is None:
        return None
    query_embedding = embed([query])
    if query_embedding is None:
        return None
    return (corpus_embeddings @ query_embedding[0]).tolist()
