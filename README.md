# nltest

Run your automation test suite with plain English.

```bash
$ nltest run "test recording"
```

`nltest` scans a test automation repo, figures out which test cases relate to
a natural-language phrase (e.g. *"test recording"*, *"run login and checkout
tests"*, *"smoke test the api"*), and executes exactly those tests — no
matter which framework or language they're written in — then prints a clean
pass/fail report.

It's designed to sit on top of whatever you already have: Selenium,
Playwright (Python or JS/TS), Cypress, Jest, Mocha, JUnit, TestNG, REST
Assured, pytest, etc. There's no new DSL to learn and no test cases to
rewrite — `nltest` reads your existing test files, tags, and names.

## Why

Automation repos accumulate hundreds of test cases across multiple stacks
(UI tests in Selenium/Playwright/Cypress, API tests in REST Assured/pytest,
mobile tests in Appium...). Remembering exact test IDs, tags, and CLI
incantations for each framework is tedious. `nltest` gives you a single,
framework-agnostic interface:

```bash
nltest run "test recording"          # -> runs every recording-related test,
                                      #    in every stack in the repo
nltest run "run all login tests" -y  # skip the confirmation prompt
nltest run "smoke test checkout" --dry-run   # see what WOULD run
nltest index                         # see every test case nltest can find
nltest list-tags                     # see every tag/marker/group discovered
```

## How it works

1. **Scan** — `nltest` walks the target repo and parses test files for each
   supported framework, extracting a normalized `TestCase` for every test:
   name, file, tags/markers/groups, docstring/display name, and the
   underlying stack (Selenium / Playwright / Cypress / REST Assured / ...).
2. **Match** — your natural-language query is tokenized, expanded with a
   configurable synonym dictionary (e.g. "recording" ↔ "record", "capture",
   "screencast"), and scored against each test's tags, name, description,
   stack, and file path using exact + fuzzy matching.
3. **Run** — matched tests are grouped by framework and handed to the right
   runner (`pytest`, `npx playwright test`, `npx cypress run`, `npx jest`,
   `npx mocha`, `mvn`/Gradle for JUnit/TestNG), which is invoked with only
   the matched test IDs. Wherever the framework supports a machine-readable
   reporter (JUnit XML, Playwright/Jest/Mocha JSON), results are parsed for
   precise pass/fail/skip status per test.
4. **Report** — a console table always prints; `--json` / `--html` optionally
   write a report file for CI artifacts or dashboards.

## Supported stacks

| Language   | Frameworks                                  | Detected via                                   |
|------------|----------------------------------------------|-------------------------------------------------|
| Python     | pytest, Selenium, Playwright                  | `test_*.py` / `*_test.py`, `@pytest.mark.*`      |
| JavaScript/TypeScript | Playwright, Cypress, Jest, Mocha  | `*.spec.*` / `*.test.*`, `describe`/`it`/`test`  |
| Java       | JUnit 4/5, TestNG, Selenium, REST Assured     | `@Test`, `@Tag`, TestNG `groups = {...}`         |

Adding a new language/framework means adding one scanner (parses source →
`TestCase`) and one runner (`TestCase[]` → shell command → `TestResult[]`).
See [`nltest/scanners/`](nltest/scanners/) and [`nltest/runners/`](nltest/runners/).

## Installation

```bash
pip install -e .
```

This installs the `nltest` command (backed by `nltest/cli.py`).

## Usage

```bash
# From inside (or pointing --repo at) your test automation repo:
nltest index                        # list every test nltest discovered
nltest list-tags                    # list every tag/marker/group found
nltest match "test recording"       # preview matches without running
nltest run "test recording"         # match + run + report (prompts to confirm)
nltest run "test recording" -y      # skip the confirmation prompt
nltest run "test recording" --dry-run          # show commands, run nothing
nltest run "test recording" --json out.json --html out.html
nltest run "test recording" --threshold 0.5    # be stricter about matches
nltest run "test recording" --extra-args="-x"  # forwarded to the underlying runner
nltest run "test recording" --exact            # only run matched tests, not whole files/classes
nltest run "test recording" --no-deps          # don't auto-include declared dependencies
nltest run "test recording" --no-ci-order      # ignore CI pipeline staging, use match-score order
nltest --repo /path/to/other/repo run "smoke test checkout"
```

Exit code is `0` if every matched test passed (or `--dry-run` was used), and
`1` if anything failed/errored or nothing matched.

## How tests get tagged for matching

`nltest` uses whatever tagging mechanism your framework already has, plus a
lightweight `// tags:` / `# tags:` comment convention for frameworks/styles
that don't have one:

```python
@pytest.mark.recording          # pytest marker -> tag "recording"
def test_start_recording(): ...

# tags: recording, playback
def test_recording_playback(): ...   # comment-based tag (any framework)
```

```javascript
it("shows a countdown before recording starts @recording", () => {});  // inline @tag
// tags: recording
it("allows pausing an active recording", () => {});
```

```java
@Test
@Tag("recording")                          // JUnit 5
public void recordingButtonToggles() {}

@Test(groups = {"recording", "api"})       // TestNG
public void startRecordingReturns201() {}
```

Even *untagged* tests still match on their name, docstring/display name, and
file path — tags simply make matching more precise.

## Understanding compound scenarios, not just keywords

A query like

```bash
nltest run "test save employment after importing"
```

isn't fuzzy-matched as one bag of words `{save, employment, after, importing}`.
`nltest` parses it into **two distinct scenarios with an explicit run
order** — "importing" (a prerequisite) and "save employment" (what's
actually being tested) — resolves each independently, and runs them in that
order (`-- stage: prerequisite: importing --` then `-- stage: main: test
save employment --`). Recognized connectors: `after`, `once`, `following`,
`before`, `then`, `and then`, `followed by`, `prior to`, `subsequent to`,
`given that`, `assuming`.

Verb forms are understood too — `"after importing"` matches a test tagged
`import` (not just the literal word "importing"), `"once saving succeeds"`
matches one tagged `save`, etc.

**When a scenario has no corresponding test case, nltest says so and asks
what to do**, instead of silently guessing:

```
No test case found for the prerequisite step: "importing".
  How should nltest handle "importing"?
    [s] I already did this manually -- skip it
    [t] Use a specific tag or exact test name for this step
    [a] Abort
  >
```

- **`[s]`** — treats that step as already satisfied and proceeds to resolve
  the remaining scenario(s) on their own.
- **`[t]`** — lets you point nltest at a specific tag or test name to stand
  in for that step.
- **`[a]`** — aborts the run.

This also handles the "only a full-fledged combined case exists" situation:
if the *only* test covering "importing" also covers "save employment" (a
single composite test doing both), nltest tells you that explicitly —

```
No DEDICATED test case found for the prerequisite step: "importing" -- it
only appears as part of a combined case (test_import_and_save_employment_full_flow)
that also covers another part of this request.
  How should nltest handle "importing"?
    [s] I already did this manually -- skip it
    [t] Use a specific tag or exact test name for this step
    [u] Use the combined case as-is (run it in full)
    [a] Abort
  >
```

— and if you say `[s]`, it looks for a `# step: <name>` marker with a
detected skip-env-var convention (see below) inside that composite test and,
if found, runs it with that env var set to bypass just the import portion,
rather than either re-running the whole thing from scratch or refusing to
help:

```python
def test_import_and_save_employment_full_flow():
    # step: import (skippable via NLTEST_SKIP_IMPORT)
    if not os.environ.get("NLTEST_SKIP_IMPORT"):
        import_employment_csv()
    # step: save
    save_new_employment_record()
```

```bash
$ nltest run "test save employment after importing"
...
  "test_import_and_save_employment_full_flow" also performs the "importing"
  step you skipped -- running it with NLTEST_SKIP_IMPORT=1 to bypass that part.
```

If no such convention is detected, nltest says so plainly rather than
pretending it sliced the test — most frameworks execute a test
method/function atomically, so isolating an arbitrary code region at runtime
generally isn't possible without the test itself supporting it.

## "What if the feature isn't mentioned in the test title?"

Matching doesn't just look at titles. It searches everything nltest can find
a signal in, each weighted by how reliable a signal it typically is:

- **Tags/markers/groups** (highest weight) — `@pytest.mark.recording`, `@Tag("recording")`, TestNG `groups = {"recording"}`.
- **The test's own name**.
- **The test's source code (body)** — a Cypress test with no "recording" in
  its title/tags will still match `"test recording"` if its body does
  `cy.get('[data-testid=recording-toggle-button]')`.
- **The docstring/`@DisplayName`**, even when the title itself is generic.
- **Every comment in the file** the test lives in (a file-level comment or
  class javadoc describing the feature, even if it's not repeated in the
  individual test) — plus, best-effort, **the content of any locally-defined
  page-object/helper file the test imports** (e.g. a `RecordingPage` class),
  since the feature might only be named there.
- **The file/class name** (lowest weight — being co-located in a relevant
  file/class is a weaker signal than the test itself being about it).

This means "anything in the code or comments that has to do with the
feature" gets pulled in, not just exact title matches. The trade-off is
that file-level signals (comments, imported helpers) are shared by every
test in that file, so an unrelated test living in a very on-topic file can
occasionally surface as a weak match — the `Why` column in `nltest match`
always shows exactly which field(s) matched so this stays transparent
rather than being a black box.

For the rare case where a feature is only referred to by an internal
codename that appears *nowhere* in the test (title, tags, docstring, or
code), add a manual override to `.nltestrc.yml`:

```yaml
feature_map:
  recording:
    - "tag:beacon_internal_codename"   # force-include tests with this tag
    - "file:src/media/beacon"          # or living under this path
    - "name:some_exact_test_name"      # or with this exact name
```

See it in action: `examples/sample-multistack-repo` has a test tagged only
`beacon_internal_codename` that `nltest match "test recording"` still finds,
purely via its `.nltestrc.yml` feature_map entry.

## "What if a test has a dependency on another test?"

Two separate problems, two separate mitigations:

**1. Safe execution granularity (default).** Cherry-picking a single matched
test by node ID/method name can skip setup that an *unselected* sibling test
in the same file/class performs (shared `beforeEach` state, class-scoped
fixtures, test ordering). By default, `nltest run` executes at **file/class
granularity** — it runs the whole file (JS) or class (Java) the matched
test(s) belong to, not just the matched test IDs — so that shared state and
setup still happen exactly as they would in a full suite run. Only the
originally matched tests are reported on. Pass `--exact` to instead run only
the matched tests (faster, but riskier for suites with cross-test state).

**2. Explicit dependency resolution.** When a test *declares* a dependency on
another specific test, `nltest` resolves and auto-includes it even if the
query wouldn't otherwise have matched it:

- TestNG `dependsOnMethods = {...}` / `dependsOnGroups = {...}`
- pytest's [pytest-dependency](https://pytest-dependency.readthedocs.io/)
  convention: `@pytest.mark.dependency(name=...)` / `@pytest.mark.dependency(depends=[...])`
- A universal `# depends-on: <test name>` / `// depends-on: <test name>`
  comment for frameworks without a native mechanism (Cypress, Mocha, Jest,
  Playwright, plain JUnit)

Auto-included dependencies are shown separately in the console report and can
be disabled with `--no-deps` if you're confident they aren't needed.

```java
// TestNG: deleteRecording depends on a recording having been started first.
@Test(dependsOnMethods = {"startRecordingReturns201"})
public void deleteRecordingRemovesDownloadUrl() { ... }
```

```python
# pytest-dependency
@pytest.mark.dependency(name="recording_started")
def test_recording_can_be_started_for_share_test(): ...

@pytest.mark.dependency(depends=["recording_started"])
def test_share_button_opens_dialog(): ...
```

```javascript
// Universal comment convention (any JS framework)
// depends-on: shows a countdown before recording starts
it("shows an error if storage is full while recording", () => { ... });
```

This won't catch *implicit* dependencies (tests that happen to rely on
ordering/state without declaring it) — that's what safe-mode file/class
execution is for. If your suite has cross-file dependencies, keep those
tests' triggers in the same file/class, or declare them explicitly.

## Respecting how your CI already stages/orders tests

Most automation repos already encode a run order in their CI pipeline —
smoke tests before regression, login before checkout, a fast suite before a
slow one. `nltest run` reads that pipeline YAML (`.github/workflows/*.yml`,
`.gitlab-ci.yml`, `.circleci/config.yml`, `azure-pipelines.yml`,
`bitbucket-pipelines.yml`) and executes matched tests in the **same relative
order/staging**, instead of an arbitrary one:

```yaml
# .github/workflows/e2e-tests.yml
jobs:
  smoke:      { steps: [{ run: pytest -m smoke }] }
  login:      { needs: smoke,     steps: [{ run: pytest -k login }] }
  recording:  { needs: login,     steps: [{ run: pytest -m recording }] }
  checkout:   { needs: recording, steps: [{ run: mvn test -Dtest=...checkout }] }
```

Given that pipeline, `nltest run "test recording"` will run any
smoke-tagged recording tests first (they're covered by the `smoke` job),
then the rest of the recording suite — grouped into sequential stages named
after the CI job, printed as `-- stage: recording --` etc. as it executes,
and shown in a `Stage` column in `nltest match`/`run` previews. Tests that
don't correspond to any recognized CI step still run, just placed after all
recognized stages. Disable this with `--no-ci-order` to run in plain
match-score order instead.

How a test is matched to a stage:
1. **File reference** — if a CI step's command references the test's file
   directly (e.g. `cypress run --spec cypress/e2e/recording.cy.js`), every
   test in that file is assigned to that step.
2. **Tag overlap** — a step's marker/grep/group expression (`-m recording`,
   `-k login`, `-Dgroups=recording`, `--tests ...`) is matched against the
   test's own tags (not free-text name, to avoid false positives from
   ordinary shared English words).

This is a heuristic, not a full CI-schema parser — for GitLab CI specifically,
job order is re-sorted by its declared `stages:` list (since GitLab's
top-level job key order doesn't reflect run order the way GitHub
Actions/Azure/Bitbucket's nested step lists do).

## Configuration

Drop a `.nltestrc.yml` in your repo root to customize scanning/matching for
that repo:

```yaml
exclude_dirs:
  - fixtures
  - __snapshots__

synonyms:
  recording:
    - screencast
    - screen-capture

match_threshold: 0.35   # 0.0 (loose) - 1.0 (strict)
max_matches: 200
```

See [`examples/sample-multistack-repo/.nltestrc.yml`](examples/sample-multistack-repo/.nltestrc.yml)
for a full example.

## Example: a repo with 5 different stacks

[`examples/sample-multistack-repo/`](examples/sample-multistack-repo/) contains a
fixture repo with recording-related tests written in pytest+Selenium,
Playwright (Python), Playwright (TS), Cypress, JUnit 5+Selenium, and
TestNG+REST Assured. Try it out:

```bash
cd examples/sample-multistack-repo
nltest index
nltest run "test recording" --dry-run
```

`nltest match "test recording"` will surface all 14 recording-related tests
across every one of those 6 frameworks, while correctly excluding unrelated
login/checkout/search tests.

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

## Architecture

```
nltest/
  cli.py           # argparse-based CLI: run / index / list-tags / match
  config.py        # .nltestrc.yml loading + defaults (synonyms, thresholds, excludes, feature_map)
  models.py        # TestCase, MatchResult, TestResult, RunReport
  ci_order.py      # reads CI pipeline YAML to stage/order execution (smoke before regression, etc.)
  scenario.py      # compound-query resolution: clauses, missing-step prompts, composite-test skip logic
  steps.py         # `# step: <name>` marker + skip-env-var convention detection within a test's body
  scanners/        # repo -> TestCase[] per language/framework
    python_scanner.py   # pytest / Selenium(py) / Playwright(py), via ast
    js_scanner.py        # Playwright(js) / Cypress / Jest / Mocha, via regex
    java_scanner.py      # JUnit / TestNG / Selenium / REST Assured, via regex
    context.py            # shared: file-level comments + locally-imported helper file content
  matcher/         # NL query -> ranked TestCase[]
    nlp.py               # tokenization, concept/synonym grouping, gerund normalization, fuzzy scoring
    intent.py             # compound-query decomposition into ordered clauses (after/before/then)
    dependencies.py       # resolves TestNG/pytest-dependency/comment-based test dependencies
  runners/         # TestCase[] -> shell command -> TestResult[]
    pytest_runner.py
    js_runner.py          # playwright/jest/mocha (JSON reporters) + cypress (best-effort)
    java_runner.py        # maven/gradle, per-module project detection, surefire/gradle XML
    junit_xml.py          # shared JUnit-XML parsing
  report/          # console table (rich), JSON, HTML report generation
```
