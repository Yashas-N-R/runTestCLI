"""Repo-local configuration for nltest (`.nltestrc.yml`)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

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
}

# Built-in synonym map: NL words -> canonical keywords that may appear as tags,
# test names, or descriptions. Repo configs can extend/override this.
DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "recording": ["record", "recorder", "capture", "screen-record"],
    "login": ["signin", "sign-in", "auth", "authentication", "logon"],
    "logout": ["signout", "sign-out"],
    "checkout": ["payment", "purchase", "order"],
    "cart": ["basket", "shopping-cart"],
    "search": ["find", "query", "lookup"],
    "upload": ["import", "attach"],
    "download": ["export"],
    "signup": ["register", "registration", "sign-up"],
    "profile": ["account", "settings", "preferences"],
    "notification": ["notify", "alert", "push"],
    "api": ["rest", "endpoint", "service"],
    "smoke": ["sanity"],
    "regression": ["full", "complete"],
}


@dataclass
class NLTestConfig:
    repo_root: str
    exclude_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_DIRS))
    include_dirs: list[str] = field(default_factory=list)
    synonyms: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_SYNONYMS))
    match_threshold: float = 0.35
    max_matches: int = 200
    run_overrides: dict[str, str] = field(default_factory=dict)
    """Framework name -> shell command template override."""

    @classmethod
    def load(cls, repo_root: str) -> "NLTestConfig":
        cfg = cls(repo_root=os.path.abspath(repo_root))
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
            self.include_dirs = list(data["include_dirs"])
        if "synonyms" in data:
            for canonical, words in data["synonyms"].items():
                self.synonyms.setdefault(canonical, [])
                self.synonyms[canonical] = sorted(set(self.synonyms[canonical]) | set(words))
        if "match_threshold" in data:
            self.match_threshold = float(data["match_threshold"])
        if "max_matches" in data:
            self.max_matches = int(data["max_matches"])
        if "run_overrides" in data:
            self.run_overrides.update(data["run_overrides"])
