"""Security boundaries for nltest.

nltest reads a user's test automation repo to discover and run tests. This
module enforces a strict local-only, read-mostly threat model:

- All repo file access stays inside the resolved repo root (no path traversal
  via ``../``, symlinks, or config tricks).
- Sensitive credential files are never read, even if they look like test code.
- Per-file and per-repo read budgets prevent runaway scanning of huge trees.
- Subprocesses run with a stripped environment so secrets in the parent shell
  are not forwarded to pytest/playwright/mvn unless explicitly whitelisted.
- No network I/O unless the user opts in with ``NLTEST_ALLOW_NETWORK=1``
  (e.g. to download the embedding model when the pip wheel was built without
  bundled weights). The default PyPI wheel ships the model offline.
- ``--extra-args`` is parsed safely and rejects shell metacharacters.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
from pathlib import Path

# Per-file cap while scanning (test files are usually small; this blocks
# accidental reads of generated bundles, heap dumps, etc.).
MAX_SCAN_FILE_BYTES = 2 * 1024 * 1024

# Total bytes nltest will read from a single repo in one invocation.
MAX_REPO_SCAN_BYTES = 256 * 1024 * 1024

# Filenames / globs we never open — even if they end in .py / .java.
SENSITIVE_NAME_GLOBS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.jks",
    "*.pfx",
    "*.keystore",
    "id_rsa",
    "id_rsa.*",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials.json",
    "secrets.json",
    "secrets.yml",
    "secrets.yaml",
    ".aws/credentials",
)

# Environment variable name patterns never forwarded to test subprocesses.
_SENSITIVE_ENV_RE = re.compile(
    r"(SECRET|PASSWORD|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTH|AWS_|AZURE_|GCP_|GITHUB_|GITLAB_|"
    r"OPENAI_|HF_|HUGGING|DATABASE_URL|CONNECTION_STRING|JWT)",
    re.IGNORECASE,
)

# Safe subprocess env keys always copied when present.
_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "NODE_PATH",
        "NODE_OPTIONS",
        "JAVA_HOME",
        "MAVEN_HOME",
        "M2_HOME",
        "GRADLE_HOME",
        "GRADLE_USER_HOME",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "PYENV_ROOT",
        "PYTHONPATH",
        "PYTHONHOME",
        "CI",
        "TERM",
        "COLORTERM",
        "NO_COLOR",
        "FORCE_COLOR",
    }
)

# NLTEST_* vars we set ourselves (step-skip overrides) are allowed through.
_NLTEST_ENV_RE = re.compile(r"^NLTEST_", re.IGNORECASE)

_EXTRA_ARGS_FORBIDDEN = re.compile(r"[;|&`$<>()\\]")


class SecurityError(Exception):
    """Raised when an operation would violate nltest's security boundaries."""


class ScanBudget:
    """Tracks aggregate bytes read while scanning a repo."""

    def __init__(self, limit: int = MAX_REPO_SCAN_BYTES) -> None:
        self.limit = limit
        self.used = 0

    def charge(self, nbytes: int) -> None:
        self.used += nbytes
        if self.used > self.limit:
            raise SecurityError(
                f"Repo scan read budget exceeded ({self.limit} bytes). "
                "Narrow scanning with include_dirs / exclude_dirs in .nltestrc.yml."
            )


_SCAN_BUDGET: ScanBudget | None = None


def reset_scan_budget(limit: int = MAX_REPO_SCAN_BYTES) -> ScanBudget:
    global _SCAN_BUDGET
    _SCAN_BUDGET = ScanBudget(limit)
    return _SCAN_BUDGET


def current_scan_budget() -> ScanBudget:
    global _SCAN_BUDGET
    if _SCAN_BUDGET is None:
        _SCAN_BUDGET = ScanBudget()
    return _SCAN_BUDGET


def resolve_repo_root(repo_root: str) -> str:
    """Canonical absolute repo root; rejects missing paths."""
    path = Path(repo_root).expanduser()
    if not path.exists():
        raise SecurityError(f"Repo path does not exist: {repo_root}")
    if not path.is_dir():
        raise SecurityError(f"Repo path is not a directory: {repo_root}")
    return str(path.resolve())


def is_within_repo(repo_root: str, path: str) -> bool:
    """True if ``path`` resolves to a location inside ``repo_root``."""
    root = os.path.realpath(resolve_repo_root(repo_root))
    target = os.path.realpath(path)
    return target == root or target.startswith(root + os.sep)


def safe_repo_path(repo_root: str, *parts: str) -> str:
    """Join ``parts`` under ``repo_root`` and verify the result stays inside."""
    root = resolve_repo_root(repo_root)
    candidate = os.path.normpath(os.path.join(root, *parts))
    if not is_within_repo(root, candidate):
        raise SecurityError(f"Path escapes repo root: {candidate}")
    return candidate


def is_sensitive_filename(name: str) -> bool:
    lowered = name.lower()
    for pattern in SENSITIVE_NAME_GLOBS:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def safe_read_text(path: str, repo_root: str, max_bytes: int = MAX_SCAN_FILE_BYTES) -> str | None:
    """Read a text file only if it is inside ``repo_root``, not sensitive, and
    within size limits. Returns None when the file should be skipped."""
    if not is_within_repo(repo_root, path):
        return None
    if is_sensitive_filename(os.path.basename(path)):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size > max_bytes:
        return None
    budget = current_scan_budget()
    budget.charge(min(size, max_bytes))
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(max_bytes)
    except OSError:
        return None


def validate_output_path(path: str, *, must_exist_parent: bool = True) -> str:
    """Resolve a user-supplied report/output path to an absolute path.

    Rejects paths that traverse through symlinks outside the user's home or
    cwd when the resolved parent does not exist yet.
    """
    resolved = Path(path).expanduser().resolve()
    if must_exist_parent:
        parent = resolved.parent
        if not parent.exists():
            raise SecurityError(f"Output directory does not exist: {parent}")
    return str(resolved)


def parse_extra_args(extra_args: str) -> list[str]:
    """Parse forwarded runner args safely; reject shell injection patterns."""
    if not extra_args or not extra_args.strip():
        return []
    if _EXTRA_ARGS_FORBIDDEN.search(extra_args):
        raise SecurityError(
            "Unsafe characters in --extra-args (shell metacharacters are not allowed). "
            "Pass only simple runner flags, e.g. --extra-args='-x --maxfail=1'."
        )
    return shlex.split(extra_args)


def build_subprocess_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal environment for invoking test frameworks.

    Parent-shell secrets (API keys, tokens, cloud credentials) are stripped.
    Explicit ``overrides`` (e.g. NLTEST_SKIP_* step flags) are applied last.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _SAFE_ENV_KEYS:
            env[key] = value
        elif _NLTEST_ENV_RE.match(key):
            env[key] = value
        elif _SENSITIVE_ENV_RE.search(key):
            continue
        # Everything else is dropped by default — test runners should not
        # inherit arbitrary developer secrets from the nltest invocation shell.
    if overrides:
        for key, value in overrides.items():
            if _SENSITIVE_ENV_RE.search(key) and not _NLTEST_ENV_RE.match(key):
                raise SecurityError(f"Refusing to set sensitive environment variable: {key}")
            env[key] = value
    return env


def network_allowed() -> bool:
    """Whether outbound network access is permitted for this process."""
    return os.environ.get("NLTEST_ALLOW_NETWORK", "").strip().lower() in ("1", "true", "yes")
