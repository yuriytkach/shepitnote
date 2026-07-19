#!/usr/bin/env python3

"""
Unit tests for hooks/publish.py -- the post-summary dispatcher. Pure logic, no
network and no subprocesses: enabled_publishers() is a table-driven env check and
run_all()/main() are driven by an injected fake runner so no real publisher is
spawned. Covers the enable/skip matrix, the deliberate confluence-before-slack
ordering, exit-code aggregation and the no-publisher warn+return-0 case.

Run with: python3 -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import publish as pub


class TestEnabledPublishers(unittest.TestCase):
    def test_none_when_nothing_set(self):
        self.assertEqual(pub.enabled_publishers({}), [])

    def test_confluence_only(self):
        self.assertEqual(
            pub.enabled_publishers({"CONFLUENCE_BASE_URL": "https://org/wiki"}),
            ["confluence"],
        )

    def test_slack_only_via_webhook(self):
        self.assertEqual(
            pub.enabled_publishers({"SLACK_WEBHOOK_URL": "https://hooks/x"}),
            ["slack"],
        )

    def test_slack_only_via_bot_token(self):
        self.assertEqual(
            pub.enabled_publishers({"SLACK_BOT_TOKEN": "xoxb-1"}),
            ["slack"],
        )

    def test_both_confluence_first(self):
        env = {
            "CONFLUENCE_BASE_URL": "https://org/wiki",
            "SLACK_WEBHOOK_URL": "https://hooks/x",
        }
        # Order is load-bearing: confluence must precede slack so the page-id
        # marker exists before slack reads it.
        self.assertEqual(pub.enabled_publishers(env), ["confluence", "slack"])

    def test_blank_values_do_not_enable(self):
        env = {"CONFLUENCE_BASE_URL": "  ", "SLACK_WEBHOOK_URL": "", "SLACK_BOT_TOKEN": "   "}
        self.assertEqual(pub.enabled_publishers(env), [])


class TestRunAll(unittest.TestCase):
    def test_calls_in_order(self):
        calls = []

        def runner(name, summary_file):
            calls.append((name, summary_file))
            return 0

        overall, results = pub.run_all("s.md", ["confluence", "slack"], runner)
        self.assertEqual(calls, [("confluence", "s.md"), ("slack", "s.md")])
        self.assertEqual(overall, 0)
        self.assertEqual(results, [("confluence", 0), ("slack", 0)])

    def test_overall_nonzero_if_any_fails(self):
        def runner(name, summary_file):
            return 1 if name == "slack" else 0

        overall, results = pub.run_all("s.md", ["confluence", "slack"], runner)
        self.assertEqual(overall, 1)
        self.assertEqual(results, [("confluence", 0), ("slack", 1)])

    def test_slack_deferred_when_confluence_fails_and_no_marker(self):
        # Transient Confluence failure with no page yet: slack must NOT run (else it
        # would post a linkless message and latch .slack_done). It is DEFERRED and
        # the overall exit is non-zero so hushnote retries.
        seen = []

        def runner(name, summary_file):
            seen.append(name)
            return 1 if name == "confluence" else 0

        overall, results = pub.run_all(
            "s.md", ["confluence", "slack"], runner, marker_present=lambda s: False
        )
        self.assertEqual(seen, ["confluence"])  # slack never invoked
        self.assertEqual(overall, 1)
        self.assertEqual(results, [("confluence", 1), ("slack", pub.DEFERRED)])

    def test_slack_runs_when_confluence_fails_but_marker_exists(self):
        # Confluence failed THIS run but a page already exists from before, so the
        # link is available: slack runs (a retry of a prior slack failure) with the
        # link. Overall is still non-zero because confluence failed.
        seen = []

        def runner(name, summary_file):
            seen.append(name)
            return 1 if name == "confluence" else 0

        overall, results = pub.run_all(
            "s.md", ["confluence", "slack"], runner, marker_present=lambda s: True
        )
        self.assertEqual(seen, ["confluence", "slack"])
        self.assertEqual(overall, 1)
        self.assertEqual(results, [("confluence", 1), ("slack", 0)])

    def test_slack_runs_when_confluence_succeeds_without_marker_check(self):
        # Confluence exited 0 this run -> ready via the exit code; the (would-fail)
        # marker check must be short-circuited and never consulted.
        def boom(_s):
            raise AssertionError("marker_present must not be called when confluence exited 0")

        seen = []

        def runner(name, summary_file):
            seen.append(name)
            return 0

        overall, results = pub.run_all(
            "s.md", ["confluence", "slack"], runner, marker_present=boom
        )
        self.assertEqual(seen, ["confluence", "slack"])
        self.assertEqual(overall, 0)

    def test_slack_only_not_gated(self):
        # Slack enabled without confluence is never gated (nothing to wait for).
        seen = []

        def runner(name, summary_file):
            seen.append(name)
            return 0

        overall, results = pub.run_all(
            "s.md", ["slack"], runner, marker_present=lambda s: False
        )
        self.assertEqual(seen, ["slack"])
        self.assertEqual(overall, 0)

    def test_marker_noop_zero_counts_as_success(self):
        # A publisher that no-ops (returns 0 because its marker exists) is success.
        overall, _ = pub.run_all("s.md", ["slack"], lambda n, s: 0)
        self.assertEqual(overall, 0)


class TestMain(unittest.TestCase):
    def test_no_publisher_warns_and_returns_zero(self):
        # Avoid an infinite hook-retry loop on a bare misconfiguration.
        rc = pub.main(["s.md"], runner=lambda n, s: 0, env={})
        self.assertEqual(rc, 0)

    def test_runs_enabled_and_aggregates(self):
        called = []

        def runner(name, summary_file):
            called.append(name)
            return 0

        env = {"CONFLUENCE_BASE_URL": "https://org/wiki", "SLACK_BOT_TOKEN": "xoxb-1"}
        rc = pub.main(["s.md"], runner=runner, env=env)
        self.assertEqual(rc, 0)
        self.assertEqual(called, ["confluence", "slack"])

    def test_aggregate_nonzero_when_enabled_publisher_fails(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks/x"}
        rc = pub.main(["s.md"], runner=lambda n, s: 3, env=env)
        self.assertEqual(rc, 1)

    def test_missing_arg_returns_usage_code(self):
        rc = pub.main([], runner=lambda n, s: 0, env={"SLACK_WEBHOOK_URL": "https://x"})
        self.assertEqual(rc, 2)

    def test_main_defers_slack_when_confluence_fails_no_marker(self):
        # End-to-end through main(): both enabled, confluence fails, no marker ->
        # slack deferred (not invoked), overall non-zero so hushnote retries.
        seen = []

        def runner(name, summary_file):
            seen.append(name)
            return 1 if name == "confluence" else 0

        env = {"CONFLUENCE_BASE_URL": "https://org/wiki", "SLACK_WEBHOOK_URL": "https://hooks/x"}
        rc = pub.main(["s.md"], runner=runner, env=env, marker_present=lambda s: False)
        self.assertEqual(rc, 1)
        self.assertEqual(seen, ["confluence"])  # slack held back this run


class TestConfluenceMarkerPresent(unittest.TestCase):
    def test_absent_marker_is_false(self):
        with tempfile.TemporaryDirectory() as d:
            summary = Path(d) / "meeting_20260718_233340_summary.md"
            summary.write_text("notes")
            self.assertFalse(pub.confluence_marker_present(str(summary)))

    def test_present_marker_is_true(self):
        with tempfile.TemporaryDirectory() as d:
            base = "meeting_20260718_233340"
            summary = Path(d) / f"{base}_summary.md"
            summary.write_text("notes")
            (Path(d) / f"{base}.confluence_page_id").write_text("12345\n")
            self.assertTrue(pub.confluence_marker_present(str(summary)))


if __name__ == "__main__":
    unittest.main()
