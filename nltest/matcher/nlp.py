"""Lightweight NLP helpers: tokenization, synonym expansion, and fuzzy scoring.

Deliberately dependency-light (no heavy NLP/embeddings) so the CLI stays fast
and installable anywhere, while still handling the common cases: plurals,
camelCase/snake_case/kebab-case test identifiers, and domain synonyms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


def _degerund_variants(word: str) -> set[str]:
    """For a gerund/present-participle like "importing" or "saving", produce
    candidate verb-stem forms ("import", "save") so a query like "after
    importing" matches a test/tag written as "import". Purely additive --
    the original word is always kept as a token too -- so this never removes
    a match, only adds recall for verb-form phrasing."""
    if not word.endswith("ing") or len(word) < 6:
        return set()
    stem = word[:-3]
    variants = {stem}
    if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
        variants.add(stem[:-1])  # "running" -> "runn" -> "run"
    variants.add(stem + "e")  # "saving" -> "sav" -> "save"
    return {v for v in variants if len(v) >= 3}


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    """Tokenize free text (query or identifiers) into normalized lowercase words
    (one token per input word -- see `word_variants` for morphological
    (gerund/plural) alternatives of an individual token)."""
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


def word_variants(word: str) -> set[str]:
    """Morphological alternative forms of a single already-normalized token,
    e.g. "importing" -> {"importing", "import"}. Used both to expand a
    query concept's own group (so "after importing" matches a test/tag
    written as "import") and to enrich field-side token sets symmetrically."""
    return {word} | _degerund_variants(word)


def expand_query_tokens(tokens: list[str], synonyms: dict[str, list[str]]) -> set[str]:
    """Expand query tokens with configured synonyms in both directions.

    Returns a flat set (kept for backwards compatibility / simple callers).
    Scoring itself uses `group_query_concepts` instead, since synonyms are OR
    alternatives for a single concept, not additional required tokens.
    """
    expanded = set(tokens)
    for concept in group_query_concepts(tokens, synonyms):
        expanded.update(concept.all_variants())
    return expanded


@dataclass
class Concept:
    """One distinct word/idea from the query, split into two confidence
    tiers so ambiguous automatic derivations don't carry the same weight as
    the word the user actually typed (or an explicitly configured synonym).
    """

    strong: set[str]
    """The literal token plus any explicitly configured synonyms -- high
    confidence, e.g. "recording" and (if configured) "capture"."""

    weak: set[str] = field(default_factory=set)
    """Automatically derived morphological variants only (e.g. "recording"
    -> "record") -- lower confidence, since e.g. "record" is also an
    ordinary noun ("employment record") unrelated to video recording."""

    def all_variants(self) -> set[str]:
        return self.strong | self.weak


def group_query_concepts(tokens: list[str], synonyms: dict[str, list[str]]) -> list[Concept]:
    """Group each distinct query token with its synonym alternatives.

    Each returned Concept represents ONE idea the user mentioned; a field
    only needs to contain one variant to satisfy it, but strong-tier
    variants (the literal word / configured synonyms) count for full credit
    while weak-tier (automatically derived, e.g. gerund-stripped) variants
    count for partial credit -- see `score_test`.
    """
    concepts: list[Concept] = []
    for token in tokens:
        strong = {token}
        weak = word_variants(token) - {token}
        for canonical, variants in synonyms.items():
            canonical_norm = _singularize(canonical.lower())
            normalized_variants = {_singularize(v.lower()) for v in variants}
            configured = {canonical_norm} | normalized_variants
            if (strong | weak) & configured:
                strong.update(configured)
        concepts.append(Concept(strong=strong, weak=weak - strong))
    return concepts


FIELD_WEIGHTS: dict[str, float] = {
    "tag": 3.0,
    "name": 2.0,
    "stack": 1.5,
    "description": 1.0,
    "body": 0.75,
    "file_context": 0.6,
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

FUZZY_MATCH_THRESHOLD = 90
"""Deliberately strict: short/common-word pairs like "record"/"recorder"
score ~86 on rapidfuzz's ratio despite meaning different things (a verb root
vs. an unrelated noun elsewhere), so the threshold needs to sit above that to
avoid false positives while still catching genuine near-misses/typos."""
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
    elif field_name == "file_context":
        text = test.file_context
    else:
        text = ""
    # Deliberately NOT enriched with word_variants() here: the repo's own
    # text is whatever form it naturally is (a tag like "import_data" already
    # contains "import" literally), and expanding it with morphological
    # guesses only adds noise (e.g. "recording" -> "record" bleeding into
    # unrelated "employment record" queries). Gerund normalization matters
    # on the QUERY side (see `group_query_concepts`), not here.
    return set(tokenize(text, drop_stopwords=(field_name in ("body", "file_context"))))


WEAK_MATCH_CREDIT = 0.2
"""Credit for a concept matching only via an automatically-derived weak
variant (e.g. "recording" -> "record") that ISN'T also tied to a configured
synonym. Deliberately low: these are often genuinely ambiguous (e.g.
"record" the verb-root vs. "record" the ordinary noun, as in "employment
record"). In practice this tier rarely matters -- a gerund like "importing"
or "saving" whose stem ("import"/"save") is a configured synonym key gets
promoted to a full-credit strong match instead (see `group_query_concepts`);
this only covers stems with no such configured relationship."""


def _concept_credit(concept: Concept, field_tokens: set[str]) -> tuple[float, str | None]:
    """Best credit for ONE query concept against a field's tokens: 1.0 for an
    exact match on the literal word/configured synonym, `WEAK_MATCH_CREDIT`
    for a match only via an automatically-derived variant, or partial credit
    for a close fuzzy match -- whichever is highest."""
    if concept.strong & field_tokens:
        return 1.0, next(iter(concept.strong & field_tokens))

    best_credit = 0.0
    best_reason = None
    if concept.weak & field_tokens:
        best_credit = WEAK_MATCH_CREDIT
        best_reason = next(iter(concept.weak & field_tokens))

    # Fuzzy matching is deliberately restricted to STRONG variants only (the
    # literal query word / configured synonyms), not automatically-derived
    # weak ones -- otherwise a weak variant that's itself an uncertain guess
    # (e.g. "recording" -> "recorde", a guess for "record"+"e") can fuzzy-
    # match its way to a false high-confidence hit, compounding uncertainty
    # rather than bounding it.
    for variant in concept.strong:
        for ft in field_tokens:
            ratio = fuzz.ratio(variant, ft)
            if ratio >= FUZZY_MATCH_THRESHOLD and FUZZY_MATCH_CREDIT > best_credit:
                best_credit = FUZZY_MATCH_CREDIT
                best_reason = f"{ft}~{variant}"
    return best_credit, best_reason


def score_test(query_concepts: list[Concept], test: TestCase, include_body: bool = True) -> tuple[float, list[str]]:
    """Score a test case against the query's concept groups (see
    `group_query_concepts`: one set of interchangeable synonym tokens per
    distinct word the user typed).

    Returns a normalized score in [0, 1] and a list of human-readable
    "field:token" explanations for why it matched.
    """
    if not query_concepts:
        return 0.0, []

    active_weights = FIELD_WEIGHTS if include_body else {k: v for k, v in FIELD_WEIGHTS.items() if k not in ("body", "file_context")}
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
