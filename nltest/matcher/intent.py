"""Decomposes a compound natural-language query into an ordered sequence of
scenario *clauses* with explicit dependency relationships.

This is the difference between treating

    "test save employment after importing"

as a bag of keywords {save, employment, after, importing} to fuzzy-match
against everything (which would just find whatever test scores highest on
those words), versus understanding it as **two distinct scenarios** --
"importing" and "save employment" -- where the query explicitly says the
first must happen before the second. That distinction is what lets nltest
notice when one of those scenarios has no corresponding test case at all,
instead of silently blending both into one keyword soup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Connector phrases and the run-order relationship they express between the
# text before and after them. Ordered so longer/more specific phrases are
# tried before their shorter substrings (e.g. "and then" before "then").
_CONNECTORS: tuple[tuple[str, str], ...] = (
    # (regex, relation) -- relation is "before_first" (left runs first) or
    # "right_first" (right runs first).
    (r"\bsubsequent to\b", "right_first"),
    (r"\bprior to\b", "before_first"),
    (r"\bfollowed by\b", "before_first"),
    (r"\bgiven that\b", "right_first"),
    (r"\band then\b", "before_first"),
    (r"\bafterwards?\b", "before_first"),
    (r"\bafter\b", "right_first"),
    (r"\bonce\b", "right_first"),
    (r"\bfollowing\b", "right_first"),
    (r"\bbefore\b", "before_first"),
    (r"\bthen\b", "before_first"),
    (r"\bassuming\b", "right_first"),
)

_CONNECTOR_RE = re.compile("|".join(f"({pattern})" for pattern, _ in _CONNECTORS), re.IGNORECASE)


@dataclass
class Clause:
    """One scenario/step within a (possibly compound) query."""

    text: str
    """The natural-language text for just this clause, e.g. 'importing'."""

    role: str
    """"prerequisite" (must be satisfied first) or "main" (the thing the
    user actually asked to test)."""


def _find_connector(query: str) -> tuple[re.Match, str] | tuple[None, None]:
    for pattern, relation in _CONNECTORS:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            return m, relation
    return None, None


def parse_query_into_clauses(query: str) -> list[Clause]:
    """Split `query` into an ordered list of clauses.

    A query with no recognized connector returns a single "main" clause
    (the whole query, unchanged) -- so simple queries like "test recording"
    behave exactly as before. A query with one connector returns exactly two
    clauses: the prerequisite (must run/be satisfied first) followed by the
    main scenario, in that run order.
    """
    match, relation = _find_connector(query)
    if not match:
        return [Clause(text=query.strip(), role="main")]

    left = query[: match.start()].strip(" ,.")
    right = query[match.end() :].strip(" ,.")

    if not left or not right:
        # Connector word present but nothing meaningful on one side (e.g. the
        # word appears as part of a larger phrase we don't want to split) --
        # treat the whole thing as a single clause rather than guessing.
        return [Clause(text=query.strip(), role="main")]

    if relation == "right_first":
        # "<main> after/once/following <prerequisite>"
        return [Clause(text=right, role="prerequisite"), Clause(text=left, role="main")]
    else:
        # "<prerequisite> before/then/followed by <main>"
        return [Clause(text=left, role="prerequisite"), Clause(text=right, role="main")]
