"""Repo-local configuration for nltest (`.nltestrc.yml`)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from nltest.security import resolve_repo_root, safe_repo_path

DEFAULT_CONFIG_NAMES = (".nltestrc.yml", ".nltestrc.yaml", "nltest.config.yml")

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "target",
    "build",
    "dist",
    ".pytest_cache",
    ".tox",
    "coverage",
    ".idea",
    ".vscode",
    # Credential / secret stores — never scanned even if misnamed as tests.
    ".aws",
    ".ssh",
    ".gnupg",
    "secrets",
}

# Deliberately EMPTY. Earlier versions shipped a hardcoded dictionary of
# English word relationships ("save" -> "persist"/"create"/"store", "import"
# -> "upload"/"ingest", etc.) -- that approach doesn't scale (nobody can
# hand-enumerate every synonym in English, let alone every team's own
# domain vocabulary) and caused real false positives from accidental word
# collisions (e.g. "record" meaning both "a recording" and "an employment
# record"). Understanding that "save" and "persist" mean the same thing is
# now handled by actual semantic understanding -- see `matcher/semantic.py`,
# which uses a sentence-embedding model instead of a lookup table. This dict
# remains available purely as an opt-in, per-repo override (`.nltestrc.yml`
# `synonyms:`) for teams who want to pin specific deterministic aliases
# (e.g. an internal codename) on top of that, not as nltest's own
# understanding of English.
DEFAULT_SYNONYMS: dict[str, list[str]] = {}


@dataclass
class NLTestConfig:
    repo_root: str
    exclude_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_DIRS))
    include_dirs: list[str] = field(default_factory=list)
    synonyms: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_SYNONYMS))
    match_threshold: float = 0.35
    max_matches: int = 200

    search_body: bool = True
    """Also match against test source code (not just title/tags/docstring).
    Turn off for very large repos if scanning/matching becomes slow."""

    semantic_matching: bool = True
    """Use a sentence-embedding model (if the optional `sentence-transformers`
    dependency is installed) to understand differently-worded queries for the
    same feature ("save" / "persist" / "store a new record") without a
    hardcoded synonym dictionary. Degrades gracefully to lexical/tag/fuzzy
    matching if the dependency isn't installed or a model can't be loaded."""

    include_dependencies: bool = True
    """Automatically pull in tests that a matched test explicitly depends on
    (TestNG dependsOnMethods/dependsOnGroups, pytest-dependency, or a
    `# depends-on:` / `// depends-on:` comment), so isolated runs don't skip
    required setup steps."""

    respect_ci_order: bool = True
    """Read the repo's CI pipeline YAML (GitHub Actions/GitLab CI/CircleCI/
    Azure Pipelines/Bitbucket Pipelines) to see how test suites are already
    staged/ordered there (e.g. smoke before regression), and run matched
    tests in that same relative order."""

    feature_map: dict[str, list[str]] = field(default_factory=dict)
    """Manual escape hatch for phrases that scanning/matching can't infer on
    their own. Maps a phrase (matched as a substring/fuzzy match against the
    query) to a list of selectors: tags, exact test names, or substrings of
    the file path. Any test matching a selector is force-included.

    Example:
        feature_map:
          "video capture":
            - "tag:recording"
            - "file:src/media/"
    """

    @classmethod
    def load(cls, repo_root: str) -> "NLTestConfig":
        cfg = cls(repo_root=resolve_repo_root(repo_root))
        for name in DEFAULT_CONFIG_NAMES:
            path = os.path.join(cfg.repo_root, name)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                cfg._apply(data)
                break
        return cfg

    def _apply(self, data: dict) -> None:
        if "exclude_dirs" in data:
            self.exclude_dirs |= set(data["exclude_dirs"])
        if "include_dirs" in data:
            self.include_dirs = [
                os.path.relpath(safe_repo_path(self.repo_root, d), self.repo_root) for d in data["include_dirs"]
            ]
        if "synonyms" in data:
            for canonical, words in data["synonyms"].items():
                self.synonyms.setdefault(canonical, [])
                self.synonyms[canonical] = sorted(set(self.synonyms[canonical]) | set(words))
        if "match_threshold" in data:
            self.match_threshold = float(data["match_threshold"])
        if "max_matches" in data:
            self.max_matches = int(data["max_matches"])
        if "run_overrides" in data:
            # Disabled for security: arbitrary shell command templates would
            # let a malicious .nltestrc.yml execute anything in the repo context.
            raise ValueError(
                "run_overrides in .nltestrc.yml is not supported (removed for security). "
                "Use --extra-args on the CLI instead."
            )
        if "search_body" in data:
            self.search_body = bool(data["search_body"])
        if "semantic_matching" in data:
            self.semantic_matching = bool(data["semantic_matching"])
        if "include_dependencies" in data:
            self.include_dependencies = bool(data["include_dependencies"])
        if "respect_ci_order" in data:
            self.respect_ci_order = bool(data["respect_ci_order"])
        if "feature_map" in data:
            for phrase, selectors in data["feature_map"].items():
                self.feature_map[phrase] = list(selectors)
