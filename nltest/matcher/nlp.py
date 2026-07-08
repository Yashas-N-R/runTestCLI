"""Lightweight NLP helpers: tokenization, synonym expansion, and fuzzy scoring.

Deliberately dependency-light (no heavy NLP/embeddings) so the CLI stays fast
and installable anywhere, while still handling the common cases: plurals,
camelCase/snake_case/kebab-case test identifiers, and domain synonyms.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from nltest.models import TestCase

STOPWORDS = {
    "test",
    "tests",
    "testing",
    "case",
    "cases",
    "run",
    "runs",
    "running",
    "please",
    "all",
    "the",
    "a",
    "an",
    "for",
    "of",
    "with",
    "related",
    "associated",
    "to",
    "and",
    "check",
    "verify",
    "on",
    "in",
    "flow",
    "flows",
    "scenario",
    "scenarios",
}

CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def _split_identifier(word: str) -> list[str]:
    """Split camelCase/PascalCase/snake_case/kebab-case identifiers into lowercase parts."""
    word = word.replace("_", " ").replace("-", " ")
    word = CAMEL_BOUNDARY_RE.sub(" ", word)
    return [w.lower() for w in WORD_RE.findall(word)]


def _singularize(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    """Tokenize free text (query or identifiers) into normalized lowercase words."""
    raw_words = WORD_RE.findall(text)
    tokens: list[str] = []
    for w in raw_words:
        for part in _split_identifier(w):
            norm = _singularize(part)
            if drop_stopwords and norm in STOPWORDS:
                continue
            if norm:
                tokens.append(norm)
    return tokens


def expand_query_tokens(tokens: list[str], synonyms: dict[str, list[str]]) -> set[str]:
    """Expand query tokens with configured synonyms in both directions."""
    expanded = set(tokens)
    for token in tokens:
        for canonical, variants in synonyms.items():
            normalized_variants = {_singularize(v.lower()) for v in variants}
            if token == _singularize(canonical.lower()) or token in normalized_variants:
                expanded.add(_singularize(canonical.lower()))
                expanded.update(normalized_variants)
    return expanded


FIELD_WEIGHTS: dict[str, float] = {
    "tag": 3.0,
    "name": 2.0,
    "stack": 1.5,
    "description": 1.0,
    "file_path": 0.5,
}

FUZZY_MATCH_THRESHOLD = 85
FUZZY_MATCH_CREDIT = 0.8


def _field_tokens(test: TestCase, field_name: str) -> set[str]:
    if field_name == "tag":
        text = " ".join(test.tags)
    elif field_name == "name":
        text = f"{test.name} {test.class_name or ''}"
    elif field_name == "stack":
        text = test.stack.value
    elif field_name == "description":
        text = test.description
    elif field_name == "file_path":
        text = test.file_path
    else:
        text = ""
    return set(tokenize(text, drop_stopwords=False))


def score_test(query_tokens: set[str], test: TestCase) -> tuple[float, list[str]]:
    """Score a test case against an (already expanded) set of query tokens.

    Returns a normalized score in [0, 1] and a list of human-readable
    "field:token" explanations for why it matched.
    """
    if not query_tokens:
        return 0.0, []

    total_weight = sum(FIELD_WEIGHTS.values())
    matched_weight = 0.0
    matched_on: list[str] = []

    for field_name, weight in FIELD_WEIGHTS.items():
        field_tokens = _field_tokens(test, field_name)
        if not field_tokens:
            continue

        best_credit = 0.0
        best_reason = None
        for qt in query_tokens:
            if qt in field_tokens:
                best_credit = 1.0
                best_reason = f"{field_name}:{qt}"
                break
            for ft in field_tokens:
                ratio = fuzz.ratio(qt, ft)
                if ratio >= FUZZY_MATCH_THRESHOLD and FUZZY_MATCH_CREDIT > best_credit:
                    best_credit = FUZZY_MATCH_CREDIT
                    best_reason = f"{field_name}:{ft}~{qt}"

        if best_reason:
            matched_on.append(best_reason)
        matched_weight += best_credit * weight

    score = matched_weight / total_weight if total_weight else 0.0
    return score, matched_on
