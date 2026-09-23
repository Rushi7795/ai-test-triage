"""Unit tests for the JUnit parser. Plain stdlib unittest - no dependencies."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from junit_parser import parse_reports  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class TestParser(unittest.TestCase):

    def test_surefire_failure_is_parsed(self):
        s = parse_reports([os.path.join(FIXTURES, "surefire.xml")])
        self.assertEqual(s.total, 3)
        self.assertEqual(s.passed, 2)
        self.assertEqual(s.failed, 1)
        self.assertIn("btn-login-submit-OLD", s.failures[0].message)

    def test_pytest_separates_errors_from_failures(self):
        s = parse_reports([os.path.join(FIXTURES, "pytest.xml")])
        self.assertEqual(s.failed, 1)
        self.assertEqual(s.errored, 1)
        self.assertEqual(s.skipped, 1)
        kinds = sorted(f.kind for f in s.failures)
        self.assertEqual(kinds, ["error", "failure"])

    def test_jest_nested_testsuites(self):
        s = parse_reports([os.path.join(FIXTURES, "jest.xml")])
        self.assertEqual(s.total, 2)
        self.assertEqual(s.failed, 1)
        # classname repeats the name in Jest output; it must not be doubled
        self.assertEqual(s.failures[0].full_name, "cart clears")

    def test_passing_run_has_no_failures(self):
        s = parse_reports([os.path.join(FIXTURES, "passing.xml")])
        self.assertFalse(s.has_failures)
        self.assertEqual(s.passed, 2)

    def test_missing_files_are_not_an_error(self):
        s = parse_reports([os.path.join(FIXTURES, "does-not-exist-*.xml")])
        self.assertEqual(s.files_read, 0)
        self.assertFalse(s.has_failures)

    def test_max_failures_is_respected(self):
        s = parse_reports([os.path.join(FIXTURES, "*.xml")], max_failures=2)
        self.assertEqual(len(s.failures), 2)
        self.assertGreaterEqual(s.failed + s.errored, 3)  # counts stay accurate


if __name__ == "__main__":
    unittest.main(verbosity=2)
