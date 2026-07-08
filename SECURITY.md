# Security Policy

## Threat model

`nltest` is a **local CLI tool** that reads your test automation repository to
discover tests, matches them against a natural-language query, and invokes your
existing test runners (`pytest`, `playwright`, `cypress`, `mvn`, etc.) on your
machine.

It is **not** a hosted service. It does **not** upload your repository, test
source code, credentials, or match results to any server by default.

## What nltest does with your repo

| Action | Scope | Sent over network? |
|--------|--------|-------------------|
| Scan test files | Read-only, inside `--repo` root | No |
| Load `.nltestrc.yml` | Read-only config in repo root | No |
| Semantic matching | Encodes test metadata locally with a bundled embedding model | No (default wheel) |
| Run tests | Invokes your installed frameworks as subprocesses | No (nltest itself) |
| Write reports | Only to paths you pass via `--json` / `--html` | No |

Your test frameworks may contact external services (browsers, APIs under test,
etc.) — that is **your test code**, not `nltest`.

## Built-in protections

1. **Repo boundary** — All file reads are resolved and checked to stay inside the
   canonical repo root. Path traversal (`../`), symlink escapes, and
   `include_dirs` tricks outside the repo are rejected.

2. **Sensitive file denylist** — Credential files (`.env`, `*.pem`, `*.key`,
   `id_rsa`, `secrets.json`, `.npmrc`, etc.) are never opened. Test source
   files are still scanned; do not hard-code secrets in test code.

3. **Read budgets** — Per-file (2 MB) and per-repo (256 MB) caps prevent
   runaway scanning of huge generated trees.

4. **No network by default** — The PyPI wheel bundles the MiniLM embedding model.
   Outbound HTTP is blocked unless you explicitly set `NLTEST_ALLOW_NETWORK=1`
   (e.g. to download a custom model). There is no telemetry or analytics.

5. **Stripped subprocess environment** — When `nltest` runs pytest/playwright/mvn,
   it does **not** forward your shell's API keys, tokens, or cloud credentials.
   Only safe runner variables (`PATH`, `JAVA_HOME`, `NLTEST_*` step-skip flags,
   etc.) are passed through.

6. **Safe `--extra-args`** — Shell metacharacters (`;`, `|`, `$()`, backticks,
   etc.) are rejected. Arguments are parsed with `shlex`, never `shell=True`.

7. **Disabled `run_overrides`** — Arbitrary shell command templates in
   `.nltestrc.yml` are not supported (they would be a remote-code-execution
   vector if a malicious config were committed).

8. **Safe YAML** — Config files are parsed with `yaml.safe_load` (no arbitrary
   Python object deserialization).

## What nltest cannot guarantee

- **Malicious test code** — `nltest` runs *your* tests. If a test file contains
  malware, that code executes when the test runs — the same as `pytest` or
  `npm test` would. Only run `nltest` in repositories you trust.

- **Compromised dependencies** — Install `nltest` from PyPI or the official
  GitHub repository. Verify package hashes in security-sensitive environments.

- **Secrets inside test source** — We skip obvious credential *files*, but if
  someone hard-coded an API key inside a `test_login.py` body, scanning that
  file for matching is unavoidable. Do not commit secrets to test repos.

- **Framework side effects** — `pytest`, browsers, and API tests may use network,
  filesystem, and credentials configured in *your* project — outside nltest's
  control.

## Reporting a vulnerability

If you believe you have found a security issue in `nltest` itself (path escape,
data exfiltration, command injection via nltest flags, etc.), please open a
private security advisory on GitHub:

https://github.com/Yashas-N-R/runTestCLI/security/advisories/new

Do **not** open public issues for unfixed exploit details.

## Recommended usage in sensitive environments

```bash
pip install nltest
cd your-trusted-test-repo
nltest run "smoke test login" --dry-run   # inspect before running
nltest run "smoke test login" -y
```

- Run in CI with a dedicated service account and least-privilege tokens.
- Keep `.env` and secrets out of the repo (use your CI secret store).
- Use `--dry-run` to review which commands will execute before running on prod-like data.
