"""Natural language matching engine: turns free-text queries like
"test recording" into a ranked list of relevant TestCase objects."""

from __future__ import annotations

from nltest.config import NLTestConfig
from nltest.models import MatchResult, TestCase

from .dependencies import expand_with_dependencies
from .nlp import expand_query_tokens, group_query_concepts, score_test, tokenize

__all__ = [
    "match_query",
    "tokenize",
    "expand_query_tokens",
    "group_query_concepts",
    "score_test",
    "expand_with_dependencies",
]


def _apply_feature_map(query: str, tests: list[TestCase], config: NLTestConfig, existing_ids: set[str]) -> list[MatchResult]:
    """Manual escape hatch: if the query matches a configured feature_map
    phrase, force-include tests matching its selectors, even if automatic
    scanning/scoring wouldn't have found them (e.g. the feature name never
    appears anywhere in the test's title, tags, docstring, or code)."""
    query_tokens = set(tokenize(query))
    extra: list[MatchResult] = []

    for phrase, selectors in config.feature_map.items():
        phrase_tokens = set(tokenize(phrase))
        if not phrase_tokens or not (phrase_tokens & query_tokens) and phrase.lower() not in query.lower():
            continue

        for selector in selectors:
            kind, _, value = selector.partition(":")
            kind, value = kind.strip().lower(), value.strip()
            for test in tests:
                if test.id in existing_ids:
                    continue
                matched = (
                    (kind == "tag" and value in test.tags)
                    or (kind == "name" and value == test.name)
                    or (kind == "file" and value in test.file_path)
                )
                if matched:
                    existing_ids.add(test.id)
                    extra.append(MatchResult(test=test, score=1.0, matched_on=[f"feature_map:{phrase}"]))

    return extra


def score_matches(query: str, tests: list[TestCase], config: NLTestConfig) -> list[MatchResult]:
    """Score every test against `query` and return those at/above
    `config.match_threshold`, sorted by descending score and capped at
    `config.max_matches`. Does not apply `feature_map` or dependency expansion
    -- see `augment_matches` / `match_query` for that."""
    query_tokens = tokenize(query)
    concepts = group_query_concepts(query_tokens, config.synonyms)

    results: list[MatchResult] = []
    for test in tests:
        score, matched_on = score_test(concepts, test, include_body=config.search_body)
        if score >= config.match_threshold:
            results.append(MatchResult(test=test, score=score, matched_on=matched_on))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[: config.max_matches]


def augment_matches(query: str, matches: list[MatchResult], tests: list[TestCase], config: NLTestConfig) -> list[MatchResult]:
    """Apply `feature_map` overrides and (unless disabled) transitively pull in
    any tests the matches explicitly depend on. Call this *after* any
    user-facing `--limit` has been applied to the score-based matches, so
    dependencies of a kept test are never silently dropped."""
    existing_ids = {m.test.id for m in matches}
    matches = list(matches) + _apply_feature_map(query, tests, config, existing_ids)

    if config.include_dependencies:
        matches = expand_with_dependencies(matches, tests)

    return matches


def match_query(query: str, tests: list[TestCase], config: NLTestConfig) -> list[MatchResult]:
    """Convenience wrapper: score + augment in one call (used for previewing
    matches, where there's no `--limit` to worry about ordering around)."""
    return augment_matches(query, score_matches(query, tests, config), tests, config)
