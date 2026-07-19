#!/usr/bin/env python3

"""
Unit tests for meeting_ui.py -- the pure helpers behind the guided `shepitnote
meeting` flow (issue #5). No mic, no Ollama, no network: every helper is a pure
function or a small filesystem read/write against a tempdir. Covers the
configured-targets matrix, the fail-safe yes/no gate, the tolerant metadata
title read/update, language detection from the sibling transcription JSON, and
the confirm-gate exit codes via the module's own main() (argv + stdin).

Run with: python3 -m unittest discover -s tests
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meeting_ui as mu


class TestParseYesNo(unittest.TestCase):
    def test_explicit_yes_variants_true(self):
        for ans in ("y", "Y", "yes", "YES", "Yes", "  yes  ", "\tY\n"):
            self.assertTrue(mu.parse_yes_no(ans), repr(ans))

    def test_empty_is_no(self):
        self.assertFalse(mu.parse_yes_no(""))
        self.assertFalse(mu.parse_yes_no("   "))

    def test_none_eof_is_no(self):
        self.assertFalse(mu.parse_yes_no(None))

    def test_n_is_no(self):
        self.assertFalse(mu.parse_yes_no("n"))
        self.assertFalse(mu.parse_yes_no("no"))

    def test_anything_not_yes_is_no(self):
        for ans in ("maybe", "yep", "ok", "sure", "yesss", "1", "true", "publish"):
            self.assertFalse(mu.parse_yes_no(ans), repr(ans))


class TestConfiguredTargets(unittest.TestCase):
    def test_none_when_nothing_set(self):
        self.assertEqual(mu.configured_targets({}), [])

    def test_confluence_only(self):
        self.assertEqual(
            mu.configured_targets({"CONFLUENCE_BASE_URL": "https://org/wiki"}),
            ["confluence"],
        )

    def test_slack_only_webhook(self):
        self.assertEqual(
            mu.configured_targets({"SLACK_WEBHOOK_URL": "https://hooks/x"}),
            ["slack"],
        )

    def test_slack_only_bot_token(self):
        self.assertEqual(
            mu.configured_targets({"SLACK_BOT_TOKEN": "xoxb-1"}),
            ["slack"],
        )

    def test_both_ordered_confluence_first(self):
        self.assertEqual(
            mu.configured_targets(
                {"CONFLUENCE_BASE_URL": "https://org/wiki", "SLACK_WEBHOOK_URL": "https://hooks/x"}
            ),
            ["confluence", "slack"],
        )

    def test_blank_values_do_not_count(self):
        self.assertEqual(
            mu.configured_targets({"CONFLUENCE_BASE_URL": "   ", "SLACK_WEBHOOK_URL": ""}),
            [],
        )


class TestMetadataTitle(unittest.TestCase):
    def _write(self, tmp, name, text):
        p = Path(tmp) / name
        p.write_text(text)
        return p

    def test_update_writes_title_into_fake_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(
                tmp,
                "meeting_20260101_120000_metadata.json",
                json.dumps({"title": "old", "date": "20260101", "timestamp": "20260101_120000"}),
            )
            data = mu.update_metadata_title(str(p), "Sprint Planning")
            self.assertEqual(data["title"], "Sprint Planning")
            on_disk = json.loads(p.read_text())
            self.assertEqual(on_disk["title"], "Sprint Planning")
            # Other fields preserved.
            self.assertEqual(on_disk["date"], "20260101")
            self.assertEqual(on_disk["timestamp"], "20260101_120000")

    def test_update_missing_file_creates_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nope_metadata.json"
            data = mu.update_metadata_title(str(p), "Brand New")
            self.assertEqual(data, {"title": "Brand New"})
            self.assertEqual(json.loads(p.read_text())["title"], "Brand New")

    def test_update_garbage_json_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "garbage_metadata.json", "{ this is not json ]")
            data = mu.update_metadata_title(str(p), "Recovered")
            self.assertEqual(data, {"title": "Recovered"})
            self.assertEqual(json.loads(p.read_text())["title"], "Recovered")

    def test_update_non_object_json_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "list_metadata.json", "[1, 2, 3]")
            data = mu.update_metadata_title(str(p), "Fixed")
            self.assertEqual(data, {"title": "Fixed"})

    def test_update_none_title_becomes_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "m_metadata.json", json.dumps({"title": "x"}))
            data = mu.update_metadata_title(str(p), None)
            self.assertEqual(data["title"], "")

    def test_update_unicode_title_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "m_metadata.json", json.dumps({"title": "x"}))
            mu.update_metadata_title(str(p), "Планування")
            self.assertEqual(json.loads(p.read_text())["title"], "Планування")

    def test_read_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "m_metadata.json", json.dumps({"title": "Standup"}))
            self.assertEqual(mu.read_metadata_title(str(p)), "Standup")

    def test_read_title_missing_file_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mu.read_metadata_title(str(Path(tmp) / "nope.json")), "")

    def test_read_title_garbage_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "g.json", "not json")
            self.assertEqual(mu.read_metadata_title(str(p)), "")

    def test_read_title_null_title_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "n.json", json.dumps({"title": None}))
            self.assertEqual(mu.read_metadata_title(str(p)), "")


class TestDetectLanguage(unittest.TestCase):
    def test_plain_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x.json").write_text(json.dumps({"language": "en", "text": "hi"}))
            self.assertEqual(mu.detect_language(tmp, "meeting_x"), "en")

    def test_trimmed_json_when_no_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x_trimmed.json").write_text(json.dumps({"language": "uk"}))
            self.assertEqual(mu.detect_language(tmp, "meeting_x"), "uk")

    def test_dual_voice_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x.voice.json").write_text(json.dumps({"language": "ru"}))
            self.assertEqual(mu.detect_language(tmp, "meeting_x"), "ru")

    def test_plain_wins_over_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x.json").write_text(json.dumps({"language": "en"}))
            (Path(tmp) / "meeting_x_trimmed.json").write_text(json.dumps({"language": "de"}))
            self.assertEqual(mu.detect_language(tmp, "meeting_x"), "en")

    def test_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(mu.detect_language(tmp, "meeting_x"))

    def test_none_when_language_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x.json").write_text(json.dumps({"language": ""}))
            self.assertIsNone(mu.detect_language(tmp, "meeting_x"))

    def test_skips_unparsable_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x.json").write_text("{ broken")
            (Path(tmp) / "meeting_x_trimmed.json").write_text(json.dumps({"language": "fr"}))
            self.assertEqual(mu.detect_language(tmp, "meeting_x"), "fr")


class TestMainCLI(unittest.TestCase):
    def _run(self, argv, stdin_text=None):
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        out = io.StringIO()
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        sys.stdout = out
        try:
            rc = mu.main(argv)
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
        return rc, out.getvalue()

    # --- confirm gate: fail-safe --- #
    def test_confirm_yes_argv_exit0(self):
        self.assertEqual(self._run(["confirm", "yes"])[0], 0)
        self.assertEqual(self._run(["confirm", "y"])[0], 0)

    def test_confirm_no_argv_exit1(self):
        for a in ("n", "no", "maybe", "", "   ", "yesss"):
            self.assertEqual(self._run(["confirm", a])[0], 1, repr(a))

    def test_confirm_stdin_yes(self):
        self.assertEqual(self._run(["confirm"], stdin_text="yes\n")[0], 0)

    def test_confirm_stdin_blank_line_is_no(self):
        self.assertEqual(self._run(["confirm"], stdin_text="\n")[0], 1)

    def test_confirm_stdin_eof_is_no(self):
        self.assertEqual(self._run(["confirm"], stdin_text="")[0], 1)

    # --- targets --- #
    def test_targets_uses_real_environ(self):
        # Uses the real os.environ; assert the output only ever contains valid
        # target names regardless of what the surrounding env has set.
        rc, out = self._run(["targets"])
        self.assertEqual(rc, 0)
        for line in out.split():
            self.assertIn(line, ("confluence", "slack"))

    # --- get-title / set-title --- #
    def test_set_and_get_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "m_metadata.json"
            meta.write_text(json.dumps({"title": "old", "date": "20260101"}))
            rc, out = self._run(["set-title", str(meta), "New One"])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "New One")
            rc, out = self._run(["get-title", str(meta)])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "New One")
            self.assertEqual(json.loads(meta.read_text())["date"], "20260101")

    def test_get_title_missing_prints_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run(["get-title", str(Path(tmp) / "nope.json")])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    # --- language --- #
    def test_language_cli_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "meeting_x.json").write_text(json.dumps({"language": "en"}))
            rc, out = self._run(["language", tmp, "meeting_x"])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "en")

    def test_language_cli_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._run(["language", tmp, "meeting_x"])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "unknown")

    # --- misc --- #
    def test_no_args_usage_exit2(self):
        rc, _ = self._run([])
        self.assertEqual(rc, 2)

    def test_unknown_subcommand_exit2(self):
        rc, _ = self._run(["frobnicate"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
