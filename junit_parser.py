"""
Parse JUnit-style XML reports into a normalised list of failures.

JUnit XML is the common output format for Maven Surefire, Gradle, pytest,
Jest, PHPUnit, .NET and most other runners, so one parser covers them all.
Dialects differ slightly, so this is deliberately tolerant: missing
attributes, nested <testsuites>, and runner-specific extras are all fine.
"""

from __future__ import annotations

import glob
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Failure:
    suite: str
    name: str
    classname: str
    kind: str  # "failure" or "error"
    message: str
    details: str
    time: float = 0.0

    @property
    def full_name(self) -> str:
        # Some runners (Jest) repeat the test name in classname; don't double it up.
        if not self.classname or self.classname == self.name:
            return self.name
        return f"{self.classname}.{self.name}"


@dataclass
class RunSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    failures: list[Failure] = field(default_factory=list)
    files_read: int = 0

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)


def _iter_testsuites(root: ET.Element):
    """Yield every <testsuite>, whether the root is one or wraps many."""
    if root.tag == "testsuite":
        yield root
    for suite in root.iter("testsuite"):
        if suite is not root:
            yield suite


def _text_of(node: ET.Element) -> str:
    parts = [node.text or ""]
    parts.extend((child.tail or "") for child in node)
    return "".join(parts).strip()


def parse_reports(patterns: list[str], max_failures: int = 20,
                  max_detail_chars: int = 4000) -> RunSummary:
    """Read every XML file matching the glob patterns into one RunSummary."""
    summary = RunSummary()
    seen_paths: set[str] = set()

    for pattern in patterns:
        for path in sorted(glob.glob(pattern, recursive=True)):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError) as exc:
                print(f"::warning::Skipping unreadable report {path}: {exc}")
                continue

            summary.files_read += 1

            for suite in _iter_testsuites(root):
                suite_name = suite.get("name", "")
                for case in suite.findall("testcase"):
                    summary.total += 1
                    if case.find("skipped") is not None:
                        summary.skipped += 1
                        continue

                    problem = case.find("failure")
                    kind = "failure"
                    if problem is None:
                        problem = case.find("error")
                        kind = "error"

                    if problem is None:
                        summary.passed += 1
                        continue

                    if kind == "failure":
                        summary.failed += 1
                    else:
                        summary.errored += 1

                    if len(summary.failures) >= max_failures:
                        continue

                    details = _text_of(problem)
                    if len(details) > max_detail_chars:
                        details = details[:max_detail_chars] + "\n... (truncated)"

                    try:
                        elapsed = float(case.get("time", "0") or 0)
                    except ValueError:
                        elapsed = 0.0

                    summary.failures.append(Failure(
                        suite=suite_name,
                        name=case.get("name", "unknown"),
                        classname=case.get("classname", ""),
                        kind=kind,
                        message=(problem.get("message") or "").strip(),
                        details=details,
                        time=elapsed,
                    ))

    return summary


def failures_as_text(summary: RunSummary) -> str:
    """Flatten failures into the prompt text sent to the model."""
    blocks = []
    for f in summary.failures:
        blocks.append(
            f"### {f.full_name}\n"
            f"Type: {f.kind}\n"
            f"Message: {f.message or '(none)'}\n"
            f"Details:\n{f.details or '(none)'}"
        )
    return "\n\n".join(blocks)
