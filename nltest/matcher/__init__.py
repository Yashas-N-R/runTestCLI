"""Natural language matching engine: turns free-text queries like
"test recording" into a ranked list of relevant TestCase objects."""

from __future__ import annotations

from nltest.config import NLTestConfig
from nltest.models import MatchResult, TestCase

from .nlp import expand_query_tokens, score_test, tokenize

__all__ = ["match_query", "tokenize", "expand_query_tokens", "score_test"]


def match_query(query: str, tests: list[TestCase], config: NLTestConfig) -> list[MatchResult]:
    """Return TestCases relevant to `query`, sorted by descending relevance score.

    Only results scoring at or above `config.match_threshold` are returned,
    capped at `config.max_matches`.
    """
    query_tokens = tokenize(query)
    expanded = expand_query_tokens(query_tokens, config.synonyms)

    results: list[MatchResult] = []
    for test in tests:
        score, matched_on = score_test(expanded, test)
        if score >= config.match_threshold:
            results.append(MatchResult(test=test, score=score, matched_on=matched_on))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[: config.max_matches]
