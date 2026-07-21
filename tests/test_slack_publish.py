#!/usr/bin/env python3

"""
Unit tests for hooks/slack_publish.py -- pure stdlib logic, no network, no real
Ollama and no real Slack. The Ollama call is exercised through an injected fake
callable; the Slack POST is never touched. Covers the TL;DR prompt building, the
markdown -> Slack mrkdwn renderer, the Confluence-link construction and marker
read, config/target/mode resolution, required-var validation per mode, payload
assembly, message assembly, secret redaction and the .slack_done skip logic.

Run with: python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the bundled hooks/ dir importable so we can import slack_publish (and the
# confluence_publish helpers it reuses) exactly as test_confluence_publish.py does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import slack_publish as sp


class TestModuleImport(unittest.TestCase):
    def test_imports_without_network_or_requests(self):
        """The module must import even when requests is absent (guarded import)."""
        self.assertTrue(hasattr(sp, "markdown_to_slack"))
        self.assertTrue(sp.requests is None or hasattr(sp.requests, "request"))

    def test_reuses_confluence_pure_helpers(self):
        # The confluence_publish helpers are rebound onto this module.
        self.assertTrue(callable(sp.derive_base_stem))
        self.assertTrue(callable(sp.read_metadata))
        self.assertEqual(sp.derive_base_stem("/x/meeting_1_summary.md"), "meeting_1")


class TestTldrPrompt(unittest.TestCase):
    def test_prompt_embeds_summary(self):
        p = sp.build_tldr_prompt("## Summary\nWe shipped it.")
        self.assertIn("We shipped it.", p)

    def test_prompt_asks_for_tldr_and_action_items(self):
        p = sp.build_tldr_prompt("x")
        self.assertIn("TL;DR", p)
        self.assertIn("Action items", p)

    def test_prompt_is_terse_instruction(self):
        # Must instruct against restating the full notes / adding sections.
        p = sp.build_tldr_prompt("x").lower()
        self.assertIn("terse", p)


class TestStripCodeFence(unittest.TestCase):
    def test_strips_plain_fence(self):
        self.assertEqual(sp._strip_code_fence("```\nhi\n```"), "hi")

    def test_strips_language_fence(self):
        self.assertEqual(sp._strip_code_fence("```markdown\nhi\n```"), "hi")

    def test_leaves_unfenced(self):
        self.assertEqual(sp._strip_code_fence("hi there"), "hi there")


class TestGenerateTldr(unittest.TestCase):
    def test_fake_ollama_receives_built_prompt(self):
        captured = {}

        def fake(prompt, model=None, ollama_url=None):
            captured["prompt"] = prompt
            captured["model"] = model
            captured["ollama_url"] = ollama_url
            return "- one\n- two"

        out = sp.generate_tldr("## Summary\nBody", "m1", "http://o", ollama_fn=fake)
        self.assertEqual(out, "- one\n- two")
        self.assertIn("Body", captured["prompt"])
        self.assertEqual(captured["model"], "m1")
        self.assertEqual(captured["ollama_url"], "http://o")

    def test_result_code_fence_stripped(self):
        out = sp.generate_tldr("x", "m", "u", ollama_fn=lambda *a, **k: "```\n- a\n```")
        self.assertEqual(out, "- a")

    def test_no_real_ollama_or_summarize_imported(self):
        # Injecting a fake must not import summarize or hit the network.
        sys.modules.pop("summarize", None)
        sp.generate_tldr("x", "m", "u", ollama_fn=lambda *a, **k: "ok")
        self.assertNotIn("summarize", sys.modules)


class TestMarkdownToSlack(unittest.TestCase):
    def test_heading_becomes_bold_line(self):
        self.assertEqual(sp.markdown_to_slack("## Action items"), "*Action items*")

    def test_bold_double_asterisk_to_single(self):
        out = sp.markdown_to_slack("we shipped the **rollout** today")
        self.assertIn("*rollout*", out)
        self.assertNotIn("**", out)

    def test_bold_underscores_to_single_asterisk(self):
        out = sp.markdown_to_slack("a __bold__ word")
        self.assertIn("*bold*", out)
        self.assertNotIn("__", out)

    def test_italic_asterisk_to_underscore(self):
        self.assertEqual(sp.markdown_to_slack("an *italic* word"), "an _italic_ word")

    def test_unordered_bullet(self):
        self.assertEqual(sp.markdown_to_slack("- item one"), "• item one")

    def test_mixed_bullet_chars(self):
        out = sp.markdown_to_slack("* a\n+ b\n- c")
        self.assertEqual(out, "• a\n• b\n• c")

    def test_ordered_list_keeps_number(self):
        self.assertEqual(sp.markdown_to_slack("1. first\n2. second"), "1. first\n2. second")

    def test_unchecked_task(self):
        self.assertEqual(sp.markdown_to_slack("- [ ] do it"), "• ☐ do it")

    def test_checked_task(self):
        self.assertEqual(sp.markdown_to_slack("- [x] done"), "• ☑ done")

    def test_uppercase_checked_task(self):
        self.assertEqual(sp.markdown_to_slack("- [X] done"), "• ☑ done")

    def test_code_span_left_literal_not_italicized(self):
        out = sp.markdown_to_slack("run `a*b*c` now")
        self.assertIn("`a*b*c`", out)
        self.assertNotIn("_", out)

    def test_spaced_asterisks_not_italicized(self):
        out = sp.markdown_to_slack("scale 2 * 3 * 4 servers")
        self.assertNotIn("_", out)
        self.assertIn("2 * 3 * 4", out)

    def test_no_heading_hashes_leak(self):
        self.assertNotIn("#", sp.markdown_to_slack("# TL;DR\n## Action items"))

    def test_collapses_excess_blank_lines(self):
        self.assertEqual(sp.markdown_to_slack("a\n\n\n\nb"), "a\n\nb")

    def test_full_sample_renders_cleanly(self):
        sample = (
            "## TL;DR\n"
            "- Shipped the **rollout**\n"
            "- Discussed *latency* under load\n\n"
            "## Action items\n"
            "- [ ] Bob to deploy the fix\n"
            "- [x] RFC drafted\n"
        )
        out = sp.markdown_to_slack(sample)
        self.assertIn("*TL;DR*", out)
        self.assertIn("*Action items*", out)
        self.assertIn("• Shipped the *rollout*", out)
        self.assertIn("• Discussed _latency_ under load", out)
        self.assertIn("• ☐ Bob to deploy the fix", out)
        self.assertIn("• ☑ RFC drafted", out)
        self.assertNotIn("**", out)
        self.assertNotIn("#", out)
        self.assertNotIn("[ ]", out)
        self.assertNotIn("[x]", out)


class TestReadPageId(unittest.TestCase):
    def test_reads_stripped_id(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "meeting_1.confluence_page_id").write_text("123456\n")
            self.assertEqual(sp.read_page_id(d, "meeting_1"), "123456")

    def test_missing_marker_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(sp.read_page_id(d, "meeting_1"))

    def test_empty_marker_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "meeting_1.confluence_page_id").write_text("   \n")
            self.assertIsNone(sp.read_page_id(d, "meeting_1"))


class TestBuildConfluenceLink(unittest.TestCase):
    def test_link_built_when_both_present(self):
        self.assertEqual(
            sp.build_confluence_link("https://org.atlassian.net/wiki", "123"),
            "https://org.atlassian.net/wiki/pages/viewpage.action?pageId=123",
        )

    def test_trailing_slash_stripped(self):
        self.assertEqual(
            sp.build_confluence_link("https://org.atlassian.net/wiki/", "123"),
            "https://org.atlassian.net/wiki/pages/viewpage.action?pageId=123",
        )

    def test_none_when_no_base_url(self):
        self.assertIsNone(sp.build_confluence_link("", "123"))

    def test_none_when_no_page_id(self):
        self.assertIsNone(sp.build_confluence_link("https://x/wiki", None))


class TestResolveMode(unittest.TestCase):
    def test_webhook_when_url_set(self):
        self.assertEqual(sp.resolve_mode({"SLACK_WEBHOOK_URL": "https://hooks/x"}), "webhook")

    def test_bot_when_only_token_set(self):
        self.assertEqual(sp.resolve_mode({"SLACK_BOT_TOKEN": "xoxb-1"}), "bot")

    def test_both_set_webhook_wins(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks/x", "SLACK_BOT_TOKEN": "xoxb-1"}
        self.assertEqual(sp.resolve_mode(env), "webhook")

    def test_none_when_neither_set(self):
        self.assertIsNone(sp.resolve_mode({}))

    def test_forced_bot_overrides_webhook_presence(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks/x", "SLACK_AUTH_MODE": "bot"}
        self.assertEqual(sp.resolve_mode(env), "bot")

    def test_forced_webhook_overrides_token_presence(self):
        env = {"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_AUTH_MODE": "webhook"}
        self.assertEqual(sp.resolve_mode(env), "webhook")

    def test_unknown_forced_mode_falls_back_to_derivation(self):
        env = {"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_AUTH_MODE": "weird"}
        self.assertEqual(sp.resolve_mode(env), "bot")


class TestResolveConfig(unittest.TestCase):
    def test_ollama_defaults_when_unset(self):
        cfg = sp.resolve_config({})
        self.assertEqual(cfg["ollama_model"], sp.DEFAULT_OLLAMA_MODEL)
        self.assertEqual(cfg["ollama_url"], sp.DEFAULT_OLLAMA_URL)

    def test_ollama_overridden(self):
        cfg = sp.resolve_config({"OLLAMA_MODEL": "mistral", "OLLAMA_URL": "http://h:1"})
        self.assertEqual(cfg["ollama_model"], "mistral")
        self.assertEqual(cfg["ollama_url"], "http://h:1")

    def test_bot_token_carried_verbatim(self):
        cfg = sp.resolve_config({"SLACK_BOT_TOKEN": " xoxb-space "})
        self.assertEqual(cfg["bot_token"], " xoxb-space ")

    def test_webhook_url_stripped(self):
        cfg = sp.resolve_config({"SLACK_WEBHOOK_URL": "  https://hooks/x  "})
        self.assertEqual(cfg["webhook_url"], "https://hooks/x")

    def test_confluence_base_url_captured_and_stripped(self):
        cfg = sp.resolve_config({"CONFLUENCE_BASE_URL": "https://org/wiki/"})
        self.assertEqual(cfg["confluence_base_url"], "https://org/wiki")

    def test_dry_run_flag_parsed(self):
        self.assertTrue(sp.resolve_config({"SLACK_DRY_RUN": "1"})["dry_run"])
        self.assertFalse(sp.resolve_config({})["dry_run"])


class TestValidateRequired(unittest.TestCase):
    def test_webhook_valid(self):
        cfg = sp.resolve_config({"SLACK_WEBHOOK_URL": "https://hooks/x"})
        sp.validate_required(cfg)  # should not raise

    def test_bot_valid(self):
        cfg = sp.resolve_config({"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_CHANNEL": "#m"})
        sp.validate_required(cfg)  # should not raise

    def test_no_target_raises(self):
        cfg = sp.resolve_config({})
        with self.assertRaises(sp.ConfigError) as ctx:
            sp.validate_required(cfg)
        msg = str(ctx.exception)
        self.assertIn("SLACK_WEBHOOK_URL", msg)
        self.assertIn("SLACK_BOT_TOKEN", msg)

    def test_bot_missing_channel_names_it(self):
        cfg = sp.resolve_config({"SLACK_BOT_TOKEN": "xoxb-1"})
        with self.assertRaises(sp.ConfigError) as ctx:
            sp.validate_required(cfg)
        self.assertIn("SLACK_CHANNEL", str(ctx.exception))
        self.assertNotIn("SLACK_BOT_TOKEN", str(ctx.exception))

    def test_forced_bot_missing_both_names_both(self):
        cfg = sp.resolve_config({"SLACK_AUTH_MODE": "bot"})
        with self.assertRaises(sp.ConfigError) as ctx:
            sp.validate_required(cfg)
        self.assertIn("SLACK_BOT_TOKEN", str(ctx.exception))
        self.assertIn("SLACK_CHANNEL", str(ctx.exception))

    def test_forced_webhook_missing_url_names_it(self):
        cfg = sp.resolve_config({"SLACK_AUTH_MODE": "webhook"})
        with self.assertRaises(sp.ConfigError) as ctx:
            sp.validate_required(cfg)
        self.assertIn("SLACK_WEBHOOK_URL", str(ctx.exception))


class TestBuildPayload(unittest.TestCase):
    def test_webhook_payload_is_text_only(self):
        cfg = sp.resolve_config({"SLACK_WEBHOOK_URL": "https://hooks/x"})
        self.assertEqual(sp.build_payload(cfg, "hi"), {"text": "hi"})

    def test_bot_payload_has_channel(self):
        cfg = sp.resolve_config({"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_CHANNEL": "#m"})
        self.assertEqual(sp.build_payload(cfg, "hi"), {"channel": "#m", "text": "hi"})

    def test_payload_carries_no_secret(self):
        cfg = sp.resolve_config({"SLACK_BOT_TOKEN": "xoxb-secret", "SLACK_CHANNEL": "#m"})
        self.assertNotIn("xoxb-secret", json.dumps(sp.build_payload(cfg, "hi")))


class TestDescribeTarget(unittest.TestCase):
    def test_webhook_hides_url(self):
        cfg = sp.resolve_config({"SLACK_WEBHOOK_URL": "https://hooks/secret"})
        desc = sp.describe_target(cfg)
        self.assertNotIn("secret", desc)
        self.assertIn("webhook", desc)

    def test_bot_shows_channel_not_token(self):
        cfg = sp.resolve_config({"SLACK_BOT_TOKEN": "xoxb-secret", "SLACK_CHANNEL": "#m"})
        desc = sp.describe_target(cfg)
        self.assertIn("#m", desc)
        self.assertNotIn("xoxb-secret", desc)

    def test_none_target(self):
        self.assertIn("no SLACK target", sp.describe_target(sp.resolve_config({})))


class TestBuildMessageText(unittest.TestCase):
    def test_link_included_when_present(self):
        msg = sp.build_message_text(
            "• point", title="Sprint", date="2026-07-18", time="09:00",
            confluence_link="https://org/wiki/pages/viewpage.action?pageId=1",
        )
        self.assertIn("*Sprint — 2026-07-18 09:00*", msg)
        self.assertIn("• point", msg)
        self.assertIn(
            "<https://org/wiki/pages/viewpage.action?pageId=1|Full meeting notes on Confluence>",
            msg,
        )

    def test_link_omitted_when_absent(self):
        msg = sp.build_message_text("• point", title="Sprint", date="2026-07-18")
        self.assertNotIn("Confluence", msg)
        self.assertIn("*Sprint — 2026-07-18*", msg)

    def test_header_without_title_falls_back(self):
        msg = sp.build_message_text("• point", title="", date="2026-07-18", time="09:00")
        self.assertIn("*Meeting notes — 2026-07-18 09:00*", msg)

    def test_header_without_title_or_date(self):
        msg = sp.build_message_text("• point")
        self.assertTrue(msg.startswith("*Meeting notes*"))


class TestRedact(unittest.TestCase):
    def test_bot_token_redacted(self):
        cfg = {"bot_token": "xoxb-super-secret", "webhook_url": ""}
        self.assertNotIn("xoxb-super-secret", sp._redact("boom xoxb-super-secret boom", cfg))

    def test_webhook_url_redacted(self):
        cfg = {"bot_token": "", "webhook_url": "https://hooks.slack.com/services/AAA/BBB"}
        out = sp._redact("failed posting to https://hooks.slack.com/services/AAA/BBB now", cfg)
        self.assertNotIn("hooks.slack.com/services/AAA/BBB", out)

    def test_truncated_to_500(self):
        self.assertLessEqual(len(sp._redact("x" * 1000, {"bot_token": "", "webhook_url": ""})), 500)


class TestShouldSkip(unittest.TestCase):
    def test_true_when_marker_exists(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "meeting_1.slack_done"
            marker.write_text("posted\n")
            self.assertTrue(sp.should_skip(str(marker)))

    def test_false_when_marker_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(sp.should_skip(str(Path(d) / "meeting_1.slack_done")))


class TestMainDryRunAndSkip(unittest.TestCase):
    """End-to-end main() exercises with no network: a fake ollama_fn feeds the
    TL;DR and every Slack call is avoided (dry-run / marker skip)."""

    def _make_meeting(self, d, with_page_id=False):
        base = "meeting_20260718_093000"
        summary = Path(d) / f"{base}_summary.md"
        summary.write_text("## Summary\nWe shipped it and agreed next steps.\n")
        (Path(d) / f"{base}_metadata.json").write_text(
            json.dumps({"title": "Sprint Planning", "date": "20260718",
                        "timestamp": "20260718_093000"})
        )
        if with_page_id:
            (Path(d) / f"{base}.confluence_page_id").write_text("777\n")
        return base, str(summary)

    def test_dry_run_prints_and_does_not_post_or_mark(self):
        with tempfile.TemporaryDirectory() as d:
            base, summary = self._make_meeting(d, with_page_id=True)
            # Provide a webhook via env just to prove the target is resolved; dry-run
            # must not post and must not need it. We pass a fake ollama_fn.
            import os, io, contextlib
            old = dict(os.environ)
            os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/SECRET"
            os.environ["CONFLUENCE_BASE_URL"] = "https://org.atlassian.net/wiki"
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rc = sp.main([summary, "--dry-run"],
                                 ollama_fn=lambda *a, **k: "- shipped it\n- next steps")
            finally:
                os.environ.clear()
                os.environ.update(old)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            # Dry-run previewed the message with the Confluence link, without leaking
            # the webhook secret.
            self.assertIn("pageId=777", out)
            self.assertNotIn("SECRET", out)
            # No marker written on dry-run.
            self.assertFalse((Path(d) / f"{base}.slack_done").exists())

    def test_existing_marker_is_noop_success(self):
        with tempfile.TemporaryDirectory() as d:
            base, summary = self._make_meeting(d)
            (Path(d) / f"{base}.slack_done").write_text("posted\n")

            def boom(*a, **k):
                raise AssertionError("ollama must not be called when marker exists")

            rc = sp.main([summary], ollama_fn=boom)
            self.assertEqual(rc, 0)

    def test_no_confluence_posts_full_summary_without_ollama(self):
        # No CONFLUENCE_BASE_URL and no page-id marker -> no link to point to, so
        # the full notes are posted verbatim and the (would-be) TL;DR pass must
        # never be invoked.
        with tempfile.TemporaryDirectory() as d:
            base, summary = self._make_meeting(d, with_page_id=False)
            import os
            old = dict(os.environ)
            os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/SECRET"
            os.environ.pop("CONFLUENCE_BASE_URL", None)

            def boom(*a, **k):
                raise AssertionError("TL;DR must not be generated with no Confluence link")

            captured = {}
            real_post = sp.post_to_slack

            def fake_post(cfg, payload):
                captured["payload"] = payload

            try:
                sp.post_to_slack = fake_post
                rc = sp.main([summary], ollama_fn=boom)
            finally:
                sp.post_to_slack = real_post
                os.environ.clear()
                os.environ.update(old)
            self.assertEqual(rc, 0)
            self.assertIn("We shipped it and agreed next steps.", captured["payload"]["text"])
            self.assertNotIn("Confluence", captured["payload"]["text"])

    def test_confluence_link_present_uses_tldr_not_full_summary(self):
        with tempfile.TemporaryDirectory() as d:
            base, summary = self._make_meeting(d, with_page_id=True)
            import os
            old = dict(os.environ)
            os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/SECRET"
            os.environ["CONFLUENCE_BASE_URL"] = "https://org.atlassian.net/wiki"
            captured = {}
            real_post = sp.post_to_slack

            def fake_post(cfg, payload):
                captured["payload"] = payload

            try:
                sp.post_to_slack = fake_post
                rc = sp.main(
                    [summary],
                    ollama_fn=lambda *a, **k: "- shipped it\n- next steps",
                )
            finally:
                sp.post_to_slack = real_post
                os.environ.clear()
                os.environ.update(old)
            self.assertEqual(rc, 0)
            text = captured["payload"]["text"]
            self.assertIn("shipped it", text)
            self.assertNotIn("We shipped it and agreed next steps.", text)
            self.assertIn("pageId=777", text)

    def test_missing_config_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            base, summary = self._make_meeting(d)
            import os
            old = dict(os.environ)
            for k in ("SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "SLACK_CHANNEL",
                      "SLACK_AUTH_MODE", "SLACK_DRY_RUN"):
                os.environ.pop(k, None)
            try:
                rc = sp.main([summary], ollama_fn=lambda *a, **k: "- x")
            finally:
                os.environ.clear()
                os.environ.update(old)
            self.assertEqual(rc, 1)
            self.assertFalse((Path(d) / f"{base}.slack_done").exists())


if __name__ == "__main__":
    unittest.main()
