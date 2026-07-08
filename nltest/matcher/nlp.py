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
    """Expand query tokens with configured synonyms in both directions.

    Returns a flat set (kept for backwards compatibility / simple callers).
    Scoring itself uses `group_query_concepts` instead, since synonyms are OR
    alternatives for a single concept, not additional required tokens.
    """
    expanded = set(tokens)
    for group in group_query_concepts(tokens, synonyms):
        expanded.update(group)
    return expanded


def group_query_concepts(tokens: list[str], synonyms: dict[str, list[str]]) -> list[set[str]]:
    """Group each distinct query token with its synonym alternatives.

    Each returned set represents ONE concept the user mentioned (e.g.
    "recording" -> {"recording", "record", "recorder", "capture", ...}); a
    field only needs to contain ONE token from a concept's set to satisfy
    that concept, but (for multi-word queries) should ideally satisfy EVERY
    concept group to get full credit.
    """
    groups: list[set[str]] = []
    for token in tokens:
        group = {token}
        for canonical, variants in synonyms.items():
            canonical_norm = _singularize(canonical.lower())
            normalized_variants = {_singularize(v.lower()) for v in variants}
            if token == canonical_norm or token in normalized_variants:
                group.add(canonical_norm)
                group.update(normalized_variants)
        groups.append(group)
    return groups


FIELD_WEIGHTS: dict[str, float] = {
    "tag": 3.0,
    "name": 2.0,
    "stack": 1.5,
    "description": 1.0,
    "body": 0.75,
    "class_name": 0.5,
    "file_path": 0.5,
}
"""class_name/file_path are deliberately weighted low: being co-located in a
class/file that's broadly about the feature is a much weaker signal than the
test's own name/tags/body actually mentioning it, and shouldn't alone be
enough to match an unrelated test just because it happens to live nearby."""
"""Relative importance of each field when scoring a query against a test.

`body` (the test's source code) is weighted lower than tags/name/description
because it's noisier, but it's what lets a query like "test recording" match
a test that calls `recorder.start()` even though its title/tags never say
the word "recording"."""

FUZZY_MATCH_THRESHOLD = 85
FUZZY_MATCH_CREDIT = 0.8


def _field_tokens(test: TestCase, field_name: str) -> set[str]:
    if field_name == "tag":
        text = " ".join(test.tags)
    elif field_name == "name":
        text = test.name
    elif field_name == "class_name":
        # Weighted lower than `name`: being co-located in a class/file that's
        # broadly about the feature is a much weaker signal than the test's
        # own name/title actually mentioning it (e.g. a "login" test inside
        # `RecordingUiTest.java` shouldn't match "test recording" as strongly
        # as the recording tests in that same file do).
        text = test.class_name or ""
    elif field_name == "stack":
        text = test.stack.value
    elif field_name == "description":
        text = test.description
    elif field_name == "file_path":
        text = test.file_path
    elif field_name == "body":
        text = test.body
    else:
        text = ""
    return set(tokenize(text, drop_stopwords=(field_name == "body")))


def _concept_credit(concept: set[str], field_tokens: set[str]) -> tuple[float, str | None]:
    """Best credit for ONE query concept (a token + its synonyms) against a
    field's tokens: 1.0 for an exact match, partial credit for a close fuzzy
    match, else 0."""
    best_credit = 0.0
    best_reason = None
    for variant in concept:
        if variant in field_tokens:
            return 1.0, variant
        for ft in field_tokens:
            ratio = fuzz.ratio(variant, ft)
            if ratio >= FUZZY_MATCH_THRESHOLD and FUZZY_MATCH_CREDIT > best_credit:
                best_credit = FUZZY_MATCH_CREDIT
                best_reason = f"{ft}~{variant}"
    return best_credit, best_reason


def score_test(query_concepts: list[set[str]], test: TestCase, include_body: bool = True) -> tuple[float, list[str]]:
    """Score a test case against the query's concept groups (see
    `group_query_concepts`: one set of interchangeable synonym tokens per
    distinct word the user typed).

    Returns a normalized score in [0, 1] and a list of human-readable
    "field:token" explanations for why it matched.
    """
    if not query_concepts:
        return 0.0, []

    active_weights = FIELD_WEIGHTS if include_body else {k: v for k, v in FIELD_WEIGHTS.items() if k != "body"}
    # Normalize against the single highest-weighted field (tags) rather than
    # the sum of every field's weight. Otherwise a test with no tags could
    # never cross the default threshold from a perfect name/body match alone,
    # since it'd always be missing the tag field's share of the denominator --
    # exactly the "what if it's not in the title/tags" case we want to handle.
    reference_weight = max(active_weights.values())
    matched_weight = 0.0
    matched_on: list[str] = []

    for field_name, weight in active_weights.items():
        field_tokens = _field_tokens(test, field_name)
        if not field_tokens:
            continue

        # Proportional credit: a field that satisfies EVERY concept the user
        # mentioned (e.g. a test named "share_button_opens_dialog" for the
        # query "share button dialog") scores much higher than one that only
        # satisfies one of several concepts -- so precise multi-word queries
        # can match on name/body alone without needing a tag hit too.
        total_credit = 0.0
        reasons: list[str] = []
        for concept in query_concepts:
            credit, reason = _concept_credit(concept, field_tokens)
            total_credit += credit
            if reason:
                reasons.append(reason)

        field_credit = total_credit / len(query_concepts)
        if reasons:
            matched_on.append(f"{field_name}:{'+'.join(reasons)}" if len(reasons) > 1 else f"{field_name}:{reasons[0]}")
        matched_weight += field_credit * weight

    score = min(matched_weight / reference_weight, 1.0) if reference_weight else 0.0
    return score, matched_on
