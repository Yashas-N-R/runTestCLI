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

## "What if the feature isn't mentioned in the test title?"

Matching doesn't just look at titles. It also searches:

- **The test's source code (body)** — a Cypress test with no "recording" in
  its title/tags will still match `"test recording"` if its body does
  `cy.get('[data-testid=recording-toggle-button]')`.
- **The docstring/`@DisplayName`**, even when the title itself is generic.
- **The file/class name** (with lower weight, since being co-located in a
  relevant file is a weaker signal than the test itself being about it).

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
  config.py        # .nltestrc.yml loading + defaults (synonyms, thresholds, excludes)
  models.py        # TestCase, MatchResult, TestResult, RunReport
  scanners/        # repo -> TestCase[] per language/framework
    python_scanner.py   # pytest / Selenium(py) / Playwright(py), via ast
    js_scanner.py        # Playwright(js) / Cypress / Jest / Mocha, via regex
    java_scanner.py      # JUnit / TestNG / Selenium / REST Assured, via regex
  matcher/         # NL query -> ranked TestCase[]
    nlp.py               # tokenization, synonym expansion, fuzzy scoring
  runners/         # TestCase[] -> shell command -> TestResult[]
    pytest_runner.py
    js_runner.py          # playwright/jest/mocha (JSON reporters) + cypress (best-effort)
    java_runner.py        # maven/gradle, per-module project detection, surefire/gradle XML
    junit_xml.py          # shared JUnit-XML parsing
  report/          # console table (rich), JSON, HTML report generation
```
