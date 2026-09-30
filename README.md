# AI Test Triage

[![CI](https://github.com/Rushi7795/ai-test-triage/actions/workflows/self-test.yml/badge.svg)](https://github.com/Rushi7795/ai-test-triage/actions/workflows/self-test.yml)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

A CI run goes red. You open the Actions log, scroll through a few hundred lines of stack trace, and start working out whether it is a real bug, a broken test, or the environment having a bad morning.

This action does that first pass for you. It reads your JUnit XML reports, sends the failures to Claude, and writes a plain-English triage summary into the job summary and onto the pull request.

For each failure you get a likely cause, a classification (**PRODUCT BUG**, **TEST BUG**, **ENVIRONMENT/FLAKY** or **UNCLEAR**), and a suggested next step. Then a two-line summary for whoever has thirty seconds.

## See it in action

<img width="700" alt="triage-comment" src="https://github.com/user-attachments/assets/3583aee1-f966-45ec-8ed4-a31bfd81bb48" />

No failing tests of your own? The [example project](https://github.com/Rushi7795/ai-test-triage-example) has 4 tests that fail on purpose, each for a different reason. Open the [demo pull request](https://github.com/Rushi7795/ai-test-triage-example/pull/1) to see the triage comment without any setup, or fork it and run it yourself.

---

## Usage

```yaml
- name: Run tests
  run: mvn -B test

- name: AI test triage
  if: failure()
  uses: Rushi7795/ai-test-triage@v1
  with:
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

That is the whole setup. `if: failure()` means it only runs when something broke, so it costs nothing on green runs.

To let it comment on pull requests, give the job permission:

```yaml
permissions:
  contents: read
  pull-requests: write
```

Works with anything that emits JUnit XML: Maven Surefire, Gradle, pytest, Jest, PHPUnit, .NET, Playwright, and most other runners.

---

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `anthropic-api-key` | (none) | Your API key. Without it the action posts a plain list of failures instead of an AI summary. |
| `report-paths` | `**/surefire-reports/*.xml,**/test-results/**/*.xml,**/junit*.xml` | Comma-separated globs for your report files. |
| `model` | `claude-sonnet-5` | Model used for triage. |
| `context` | (none) | One line about the project, e.g. `Spring Boot API behind a flaky staging gateway`. Sharpens the analysis noticeably. |
| `max-failures` | `20` | Cap on failures sent for analysis, to bound cost on a mass failure. |
| `comment-on-pr` | `true` | Post the summary as a PR comment. |

## Outputs

| Output | Description |
|--------|-------------|
| `triaged` | `true` when an AI summary was produced. |
| `summary` | The Markdown summary, for use in later steps. |

---

## Design rules

These are deliberate and worth knowing before you add this to a pipeline:

- **It never changes your build result.** This step reports; your test step decides. A red build stays red.
- **It never fails your workflow.** If the API is down, the key is missing, or the reports are unreadable, the action says so and exits 0. A broken triage must never mask the real failure underneath it.
- **It degrades instead of disappearing.** No key: you still get a clean list of what failed. API error: you get the error and the counts. All green: it says so and stops.
- **It is told not to guess.** The prompt forbids inventing file names, line numbers, or causes not present in the output, and requires `UNCLEAR` when evidence is thin. AI triage is a first pass, not a verdict.

## Cost

One API call per failed run, regardless of how many tests failed. Roughly a cent per run at default settings. Green runs cost nothing because of `if: failure()`.

## How it works

```
JUnit XML reports --> parser --> failures + counts --> Claude --> Markdown
                                                                    |
                                                    +---------------+--------------+
                                                    |                              |
                                          Actions job summary            PR comment (optional)
```

The parser (`junit_parser.py`) is tolerant by design: it handles `<testsuite>` and nested `<testsuites>`, missing attributes, and runner-specific quirks, because every framework writes this format slightly differently.

---

## Local development

```bash
INPUT_REPORT_PATHS="tests/fixtures/*.xml" \
INPUT_ANTHROPIC_API_KEY=sk-ant-... \
python3 triage.py
```

Fixtures for Surefire, pytest and Jest output are in `tests/fixtures/`.

---

## Author

**Rushi Prajapati** - QA Automation Engineer / SDET and Java developer, Ahmedabad, India.

This grew out of the failure-triage piece of my [AI-augmented test automation framework](https://github.com/Rushi7795/ai-test-automation-framework), pulled out so it works with any test runner rather than just that one.

[LinkedIn](https://www.linkedin.com/in/77rushi77) · [GitHub](https://github.com/Rushi7795)

MIT licensed.
