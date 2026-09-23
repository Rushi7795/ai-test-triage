"""
AI Test Triage - entry point for the GitHub Action.

Reads JUnit XML reports, asks Claude to triage the failures, and writes the
result to the Actions job summary and (on pull requests) as a PR comment.

Design rules, mirrored from the framework this grew out of:
  - Never change the build result. This step reports; it does not decide.
  - Never fail the workflow because triage failed. A broken API call must not
    mask the real test failure, so every error path exits 0 with a warning.
  - Degrade gracefully. No key, no reports, no failures: say so and stop.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from junit_parser import RunSummary, failures_as_text, parse_reports

ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are a senior test engineer triaging a failed CI run.

For each failure, output a Markdown section with:
  - A level-3 heading with the test name
  - **Likely cause**: one or two sentences in plain English
  - **Classification**: exactly one of PRODUCT BUG, TEST BUG, ENVIRONMENT/FLAKY, or UNCLEAR
  - **Suggested next step**: one concrete action

Then end with a section titled "## Summary" containing two or three lines for a
team lead who has thirty seconds.

Rules:
  - Be concrete and base every statement on the provided output.
  - Never invent file names, line numbers, or causes that are not evidenced.
  - If the evidence is thin, say so and classify as UNCLEAR.
  - Do not repeat full stack traces back; reference them briefly.
"""


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "")
    return value.strip() if value.strip() else default


def call_claude(api_key: str, model: str, prompt: str, max_tokens: int) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    request = urllib.request.Request(
        ANTHROPIC_ENDPOINT,
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))

    blocks = payload.get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return text.strip()


def build_prompt(summary: RunSummary, context: str) -> str:
    header = (
        f"Test run: {summary.total} tests, {summary.passed} passed, "
        f"{summary.failed} failed, {summary.errored} errored, "
        f"{summary.skipped} skipped.\n"
    )
    if context:
        header += f"Project context: {context}\n"
    return header + "\nFailures:\n\n" + failures_as_text(summary)


def write_job_summary(markdown: str) -> None:
    path = env("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    except OSError as exc:
        print(f"::warning::Could not write job summary: {exc}")


def post_pr_comment(markdown: str) -> None:
    """Post to the PR when running on a pull_request event with a token."""
    token = env("GITHUB_TOKEN")
    event_path = env("GITHUB_EVENT_PATH")
    repo = env("GITHUB_REPOSITORY")
    if not (token and event_path and repo):
        return

    try:
        with open(event_path, encoding="utf-8") as handle:
            event = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return

    pr_number = (event.get("pull_request") or {}).get("number")
    if not pr_number:
        return

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    body = json.dumps({"body": markdown}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "authorization": f"Bearer {token}",
            "accept": "application/vnd.github+json",
            "content-type": "application/json",
            "user-agent": "ai-test-triage",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status // 100 == 2:
                print("Posted triage comment to the pull request.")
    except urllib.error.HTTPError as exc:
        print(f"::warning::Could not post PR comment ({exc.code}). "
              f"Does the job have 'pull-requests: write' permission?")
    except urllib.error.URLError as exc:
        print(f"::warning::Could not reach the GitHub API: {exc.reason}")


def set_output(name: str, value: str) -> None:
    path = env("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            if "\n" in value:
                handle.write(f"{name}<<__EOF__\n{value}\n__EOF__\n")
            else:
                handle.write(f"{name}={value}\n")
    except OSError:
        pass


def finish(markdown: str, triaged: bool) -> None:
    write_job_summary(markdown)
    set_output("triaged", "true" if triaged else "false")
    set_output("summary", markdown)
    print(markdown)
    sys.exit(0)  # never fail the workflow because of this step


def main() -> None:
    patterns = [p.strip() for p in env("INPUT_REPORT_PATHS",
                "**/surefire-reports/*.xml,**/test-results/**/*.xml,**/junit*.xml"
                ).split(",") if p.strip()]
    api_key = env("INPUT_ANTHROPIC_API_KEY")
    model = env("INPUT_MODEL", "claude-sonnet-5")
    context = env("INPUT_CONTEXT")
    max_failures = int(env("INPUT_MAX_FAILURES", "20") or 20)
    comment_on_pr = env("INPUT_COMMENT_ON_PR", "true").lower() == "true"

    summary = parse_reports(patterns, max_failures=max_failures)

    if summary.files_read == 0:
        finish("## AI Test Triage\n\nNo test report files matched "
               f"`{', '.join(patterns)}`. Nothing to triage.", False)

    if not summary.has_failures:
        finish(f"## AI Test Triage\n\nAll {summary.total} tests passed "
               f"({summary.skipped} skipped). Nothing to triage.", False)

    counts = (f"**{summary.failed} failed, {summary.errored} errored** "
              f"out of {summary.total} tests "
              f"(read {summary.files_read} report file"
              f"{'s' if summary.files_read != 1 else ''}).")

    if not api_key:
        lines = "\n".join(f"- `{f.full_name}`: {f.message or f.kind}"
                          for f in summary.failures)
        finish(f"## AI Test Triage\n\n{counts}\n\n"
               f"_No API key supplied, so this is the raw list rather than an "
               f"AI summary._\n\n{lines}", False)

    try:
        analysis = call_claude(api_key, model, build_prompt(summary, context), 2000)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        finish(f"## AI Test Triage\n\n{counts}\n\n"
               f"_Triage unavailable: API returned {exc.code}._\n\n```\n{detail}\n```", False)
    except Exception as exc:  # noqa: BLE001 - never break the build
        finish(f"## AI Test Triage\n\n{counts}\n\n_Triage unavailable: {exc}_", False)

    markdown = (f"## AI Test Triage\n\n{counts}\n\n{analysis}\n\n"
                f"<sub>Generated by "
                f"[ai-test-triage](https://github.com/Rushi7795/ai-test-triage) "
                f"using `{model}`.</sub>")

    if comment_on_pr:
        post_pr_comment(markdown)

    finish(markdown, True)


if __name__ == "__main__":
    main()
