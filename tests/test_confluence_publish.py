#!/usr/bin/env python3

"""
Unit tests for hooks/confluence_publish.py -- pure stdlib logic, no network and
no real requests calls. Covers the markdown -> Confluence storage-format
converter, page-title / date / time resolution, base-stem derivation, metadata
reading, and config / auth resolution.

Run with: python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the bundled hooks/ dir importable so we can import confluence_publish.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import confluence_publish as cp


class TestModuleImport(unittest.TestCase):
    def test_imports_without_network_or_requests(self):
        """The module must import even when requests is absent (guarded import)."""
        self.assertTrue(hasattr(cp, "markdown_to_storage"))
        # requests is either the real module or None -- never an ImportError.
        self.assertTrue(cp.requests is None or hasattr(cp.requests, "request"))


class TestEscape(unittest.TestCase):
    def test_escapes_amp_lt_gt(self):
        self.assertEqual(cp.escape("a & b < c > d"), "a &amp; b &lt; c &gt; d")

    def test_amp_escaped_first(self):
        # & must be escaped before < / > so &lt; is not double-escaped.
        self.assertEqual(cp.escape("<&>"), "&lt;&amp;&gt;")

    def test_quote_only_in_attribute_mode(self):
        self.assertEqual(cp.escape('a "b"'), 'a "b"')
        self.assertEqual(cp.escape('a "b"', quote=True), "a &quot;b&quot;")


class TestConverterHeadings(unittest.TestCase):
    def test_h1_h2_h3(self):
        out = cp.markdown_to_storage("# One\n\n## Two\n\n### Three")
        self.assertIn("<h1>One</h1>", out)
        self.assertIn("<h2>Two</h2>", out)
        self.assertIn("<h3>Three</h3>", out)

    def test_deepest_heading_is_h6(self):
        out = cp.markdown_to_storage("###### Deep")
        self.assertIn("<h6>Deep</h6>", out)

    def test_seven_hashes_is_not_a_heading(self):
        # >6 hashes is not a valid ATX heading; it degrades to a paragraph.
        out = cp.markdown_to_storage("####### Deep")
        self.assertIn("<p>####### Deep</p>", out)


class TestConverterInline(unittest.TestCase):
    def test_bold(self):
        self.assertIn("<strong>hi</strong>", cp.markdown_to_storage("**hi**"))

    def test_bold_underscore(self):
        self.assertIn("<strong>hi</strong>", cp.markdown_to_storage("__hi__"))

    def test_italic(self):
        self.assertIn("<em>hi</em>", cp.markdown_to_storage("*hi*"))

    def test_italic_underscore(self):
        self.assertIn("<em>emph</em>", cp.markdown_to_storage("an _emph_ word"))

    def test_bold_and_italic_together(self):
        out = cp.markdown_to_storage("**bold** and *italic*")
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>italic</em>", out)

    def test_inline_code(self):
        self.assertIn("<code>x = 1</code>", cp.markdown_to_storage("run `x = 1` now"))

    def test_inline_code_not_treated_as_italic(self):
        # markdown inside a code span must be left literal (not bolded/italicized).
        out = cp.markdown_to_storage("`a*b*c`")
        self.assertIn("<code>a*b*c</code>", out)
        self.assertNotIn("<em>", out)

    def test_spaced_asterisks_not_italicized(self):
        # "2 * 3 * 4" is arithmetic, not emphasis: no <em> should be produced.
        out = cp.markdown_to_storage("scale 2 * 3 * 4 servers")
        self.assertNotIn("<em>", out)

    def test_inline_code_content_is_xml_escaped(self):
        out = cp.markdown_to_storage("`<tag>`")
        self.assertIn("<code>&lt;tag&gt;</code>", out)


class TestConverterLists(unittest.TestCase):
    def test_unordered_bullets(self):
        out = cp.markdown_to_storage("- one\n- two\n- three")
        self.assertIn("<ul><li>one</li><li>two</li><li>three</li></ul>", out)

    def test_mixed_bullet_chars(self):
        out = cp.markdown_to_storage("* a\n+ b\n- c")
        self.assertIn("<ul><li>a</li><li>b</li><li>c</li></ul>", out)

    def test_ordered_list(self):
        out = cp.markdown_to_storage("1. first\n2. second")
        self.assertIn("<ol><li>first</li><li>second</li></ol>", out)

    def test_bullets_with_inline_formatting(self):
        out = cp.markdown_to_storage("- do **X**\n- see `y`")
        self.assertIn("<li>do <strong>X</strong></li>", out)
        self.assertIn("<li>see <code>y</code></li>", out)


class TestConverterTaskList(unittest.TestCase):
    def test_checklist_becomes_task_list(self):
        out = cp.markdown_to_storage("- [ ] todo\n- [x] done")
        self.assertIn("<ac:task-list>", out)
        self.assertIn("</ac:task-list>", out)

    def test_incomplete_and_complete_status(self):
        out = cp.markdown_to_storage("- [ ] todo\n- [x] done")
        self.assertIn("<ac:task-status>incomplete</ac:task-status>", out)
        self.assertIn("<ac:task-status>complete</ac:task-status>", out)

    def test_uppercase_x_is_complete(self):
        out = cp.markdown_to_storage("- [X] done")
        self.assertIn("<ac:task-status>complete</ac:task-status>", out)

    def test_task_ids_increment(self):
        out = cp.markdown_to_storage("- [ ] a\n- [ ] b\n- [x] c")
        self.assertIn("<ac:task-id>1</ac:task-id>", out)
        self.assertIn("<ac:task-id>2</ac:task-id>", out)
        self.assertIn("<ac:task-id>3</ac:task-id>", out)

    def test_task_body_wrapped_in_span_with_inline(self):
        out = cp.markdown_to_storage("- [ ] ping **Bob**")
        self.assertIn("<ac:task-body><span>ping <strong>Bob</strong></span></ac:task-body>", out)

    def test_task_ids_monotonic_across_sections(self):
        md = "## A\n\n- [ ] a\n\n## B\n\n- [ ] b"
        out = cp.markdown_to_storage(md)
        self.assertIn("<ac:task-id>1</ac:task-id>", out)
        self.assertIn("<ac:task-id>2</ac:task-id>", out)

    def test_checklist_not_rendered_as_plain_ul(self):
        out = cp.markdown_to_storage("- [ ] todo")
        # The checklist line must not also produce a bullet <li>.
        self.assertNotIn("<li>[ ] todo</li>", out)


class TestConverterCodeBlocks(unittest.TestCase):
    def test_fenced_code_to_code_macro(self):
        out = cp.markdown_to_storage("```\nprint(1)\n```")
        self.assertIn('<ac:structured-macro ac:name="code">', out)
        self.assertIn("<![CDATA[print(1)]]>", out)

    def test_fenced_code_with_language(self):
        out = cp.markdown_to_storage("```python\nx = 1\n```")
        self.assertIn('<ac:parameter ac:name="language">python</ac:parameter>', out)

    def test_code_content_not_xml_escaped(self):
        # Inside CDATA the raw < > & must be left literal.
        out = cp.markdown_to_storage("```\nif a < b and c > d & e:\n```")
        self.assertIn("if a < b and c > d & e:", out)
        self.assertNotIn("&lt;", out)

    def test_cdata_terminator_split(self):
        out = cp.markdown_to_storage("```\nx = ']]>'\n```")
        self.assertIn("]]]]><![CDATA[>", out)
        # The raw, unsplit terminator must not survive inside the payload.
        self.assertNotIn("']]>'", out)


class TestConverterXmlEscaping(unittest.TestCase):
    def test_paragraph_escapes_specials(self):
        out = cp.markdown_to_storage("a & b < c > d")
        self.assertIn("<p>a &amp; b &lt; c &gt; d</p>", out)

    def test_heading_with_angle_brackets(self):
        out = cp.markdown_to_storage("## Deploy <service>")
        self.assertIn("<h2>Deploy &lt;service&gt;</h2>", out)

    def test_paragraph_join_multiline(self):
        out = cp.markdown_to_storage("line one\nline two")
        self.assertIn("<p>line one line two</p>", out)


class TestDeriveBaseStem(unittest.TestCase):
    def test_summary_md(self):
        self.assertEqual(
            cp.derive_base_stem("/x/meeting_20260718_233340_summary.md"),
            "meeting_20260718_233340",
        )

    def test_summary_txt_and_json(self):
        self.assertEqual(cp.derive_base_stem("a_summary.txt"), "a")
        self.assertEqual(cp.derive_base_stem("a_summary.json"), "a")

    def test_bare_summary(self):
        self.assertEqual(cp.derive_base_stem("a_summary"), "a")


class TestMetadataAndTitle(unittest.TestCase):
    def _write(self, dir_path, base, content):
        p = Path(dir_path) / f"{base}_metadata.json"
        p.write_text(content)
        return p

    def test_title_present(self):
        with tempfile.TemporaryDirectory() as d:
            base = "meeting_20260718_233340"
            self._write(d, base, json.dumps({"title": "Sprint Planning", "date": "20260718"}))
            md = cp.read_metadata(d, base)
            # Time (from the base stem) is appended to disambiguate same-day meetings.
            self.assertEqual(cp.resolve_page_title(md, base), "Sprint Planning - 2026-07-18 23:33")

    def test_same_title_same_day_disambiguated_by_time(self):
        # Two distinct meetings with the same human title on the same date must get
        # DISTINCT page titles, or the second would overwrite the first's page.
        md = {"title": "Standup", "date": "20260718"}
        t1 = cp.resolve_page_title(md, "meeting_20260718_090000")
        t2 = cp.resolve_page_title(md, "meeting_20260718_143000")
        self.assertEqual(t1, "Standup - 2026-07-18 09:00")
        self.assertEqual(t2, "Standup - 2026-07-18 14:30")
        self.assertNotEqual(t1, t2)

    def test_title_truncated_to_confluence_limit(self):
        md = {"title": "X" * 400, "date": "20260718"}
        self.assertEqual(len(cp.resolve_page_title(md, "meeting_20260718_233340")), 255)

    def test_title_empty_falls_back_to_meeting_time(self):
        with tempfile.TemporaryDirectory() as d:
            base = "meeting_20260718_233340"
            self._write(d, base, json.dumps(
                {"title": "", "date": "20260718", "timestamp": "20260718_233340"}))
            md = cp.read_metadata(d, base)
            self.assertEqual(cp.resolve_page_title(md, base), "Meeting 23:33 - 2026-07-18")

    def test_missing_metadata_uses_filename_regex(self):
        with tempfile.TemporaryDirectory() as d:
            base = "meeting_20260718_233340"
            # No metadata file written -> empty dict, date/time from the base stem.
            md = cp.read_metadata(d, base)
            self.assertEqual(md, {})
            self.assertEqual(cp.resolve_page_title(md, base), "Meeting 23:33 - 2026-07-18")

    def test_garbage_json_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            base = "meeting_20260718_233340"
            self._write(d, base, "{ this is not valid json ")
            md = cp.read_metadata(d, base)
            self.assertEqual(md, {})
            self.assertEqual(cp.resolve_page_title(md, base), "Meeting 23:33 - 2026-07-18")

    def test_non_object_json_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            base = "meeting_20260718_233340"
            self._write(d, base, "[1, 2, 3]")
            self.assertEqual(cp.read_metadata(d, base), {})

    def test_title_present_but_date_unresolvable(self):
        md = {"title": "Ad-hoc chat"}
        self.assertEqual(cp.resolve_page_title(md, "notes"), "Ad-hoc chat")

    def test_date_only_when_no_title_no_time(self):
        md = {"date": "20260718"}
        self.assertEqual(cp.resolve_page_title(md, "notes"), "Meeting - 2026-07-18")

    def test_last_resort_is_base_stem(self):
        self.assertEqual(cp.resolve_page_title({}, "notes"), "notes")

    def test_stable_across_reruns(self):
        md = {"title": "Weekly", "date": "20260718", "timestamp": "20260718_090000"}
        base = "meeting_20260718_090000"
        self.assertEqual(cp.resolve_page_title(md, base), cp.resolve_page_title(md, base))


class TestDateTimeResolution(unittest.TestCase):
    def test_date_from_metadata(self):
        self.assertEqual(cp.resolve_meeting_date({"date": "20261231"}, "x"), "2026-12-31")

    def test_date_from_base_when_metadata_missing(self):
        self.assertEqual(
            cp.resolve_meeting_date({}, "meeting_20260718_233340"), "2026-07-18")

    def test_date_none_when_unresolvable(self):
        self.assertIsNone(cp.resolve_meeting_date({}, "notes"))

    def test_time_from_metadata_timestamp(self):
        self.assertEqual(
            cp.resolve_meeting_time({"timestamp": "20260718_091500"}, "x"), "09:15")

    def test_time_from_base_stem(self):
        self.assertEqual(
            cp.resolve_meeting_time({}, "meeting_20260718_233340"), "23:33")

    def test_time_none_when_unresolvable(self):
        self.assertIsNone(cp.resolve_meeting_time({}, "notes"))


class TestAuthMode(unittest.TestCase):
    def test_email_selects_basic(self):
        self.assertEqual(cp.resolve_auth_mode({"CONFLUENCE_EMAIL": "me@org.com"}), "basic")

    def test_no_email_selects_bearer(self):
        self.assertEqual(cp.resolve_auth_mode({}), "bearer")

    def test_explicit_bearer_overrides_email(self):
        env = {"CONFLUENCE_EMAIL": "me@org.com", "CONFLUENCE_AUTH_MODE": "bearer"}
        self.assertEqual(cp.resolve_auth_mode(env), "bearer")

    def test_explicit_basic_overrides_absent_email(self):
        self.assertEqual(cp.resolve_auth_mode({"CONFLUENCE_AUTH_MODE": "basic"}), "basic")

    def test_unknown_mode_falls_back_to_derivation(self):
        self.assertEqual(cp.resolve_auth_mode({"CONFLUENCE_AUTH_MODE": "weird"}), "bearer")


class TestConfigValidation(unittest.TestCase):
    def _full_env(self):
        return {
            "CONFLUENCE_BASE_URL": "https://org.atlassian.net/wiki",
            "CONFLUENCE_SPACE_KEY": "ENG",
            "CONFLUENCE_API_TOKEN": "secret-token",
            "CONFLUENCE_EMAIL": "me@org.com",
        }

    def test_valid_config_passes(self):
        cfg = cp.resolve_config(self._full_env())
        cp.validate_required(cfg)  # should not raise

    def test_base_url_trailing_slash_stripped(self):
        env = self._full_env()
        env["CONFLUENCE_BASE_URL"] = "https://org.atlassian.net/wiki/"
        cfg = cp.resolve_config(env)
        self.assertEqual(cfg["base_url"], "https://org.atlassian.net/wiki")

    def test_missing_token_raises_and_names_var(self):
        env = self._full_env()
        del env["CONFLUENCE_API_TOKEN"]
        cfg = cp.resolve_config(env)
        with self.assertRaises(cp.ConfigError) as ctx:
            cp.validate_required(cfg)
        self.assertIn("CONFLUENCE_API_TOKEN", str(ctx.exception))

    def test_missing_multiple_lists_all(self):
        cfg = cp.resolve_config({"CONFLUENCE_EMAIL": "me@org.com"})
        with self.assertRaises(cp.ConfigError) as ctx:
            cp.validate_required(cfg)
        msg = str(ctx.exception)
        self.assertIn("CONFLUENCE_BASE_URL", msg)
        self.assertIn("CONFLUENCE_SPACE_KEY", msg)
        self.assertIn("CONFLUENCE_API_TOKEN", msg)

    def test_basic_without_email_raises(self):
        env = {
            "CONFLUENCE_BASE_URL": "https://org.atlassian.net/wiki",
            "CONFLUENCE_SPACE_KEY": "ENG",
            "CONFLUENCE_API_TOKEN": "secret-token",
            "CONFLUENCE_AUTH_MODE": "basic",
        }
        cfg = cp.resolve_config(env)
        with self.assertRaises(cp.ConfigError) as ctx:
            cp.validate_required(cfg)
        self.assertIn("CONFLUENCE_EMAIL", str(ctx.exception))

    def test_bearer_without_email_ok(self):
        env = {
            "CONFLUENCE_BASE_URL": "https://server/confluence",
            "CONFLUENCE_SPACE_KEY": "ENG",
            "CONFLUENCE_API_TOKEN": "pat-token",
        }
        cfg = cp.resolve_config(env)
        self.assertEqual(cfg["auth_mode"], "bearer")
        cp.validate_required(cfg)  # should not raise

    def test_dry_run_flag_parsed(self):
        cfg = cp.resolve_config({"CONFLUENCE_DRY_RUN": "1"})
        self.assertTrue(cfg["dry_run"])
        self.assertFalse(cp.resolve_config({})["dry_run"])

    def test_token_never_trimmed(self):
        # A token with surrounding spaces must be carried verbatim, not stripped.
        cfg = cp.resolve_config({"CONFLUENCE_API_TOKEN": " tok en "})
        self.assertEqual(cfg["api_token"], " tok en ")


class TestRedact(unittest.TestCase):
    def test_token_redacted_from_text(self):
        cfg = {"api_token": "super-secret"}
        self.assertNotIn("super-secret", cp._redact("boom super-secret boom", cfg))

    def test_text_truncated(self):
        cfg = {"api_token": ""}
        self.assertLessEqual(len(cp._redact("x" * 1000, cfg)), 500)


class TestFullSummaryConversion(unittest.TestCase):
    """A representative end-to-end summarize.py-shaped document converts to
    well-formed-looking storage markup with all expected constructs."""

    SAMPLE = (
        "## Summary\n"
        "We discussed the **rollout** and agreed on next steps.\n\n"
        "## Discussion\n"
        "- Reviewed the `deploy.sh` script\n"
        "- Talked about *latency* under load\n\n"
        "## Action Items\n"
        "- [ ] Ship the fix (owner: Bob)\n"
        "- [x] Draft the RFC\n\n"
        "## Notes\n"
        "```bash\nkubectl get pods\n```\n"
    )

    def test_all_constructs_present(self):
        out = cp.markdown_to_storage(self.SAMPLE)
        self.assertIn("<h2>Summary</h2>", out)
        self.assertIn("<strong>rollout</strong>", out)
        self.assertIn("<ul><li>Reviewed the <code>deploy.sh</code> script</li>", out)
        self.assertIn("<em>latency</em>", out)
        self.assertIn("<ac:task-list>", out)
        self.assertIn("<ac:task-status>incomplete</ac:task-status>", out)
        self.assertIn("<ac:task-status>complete</ac:task-status>", out)
        self.assertIn('<ac:structured-macro ac:name="code">', out)
        self.assertIn("<![CDATA[kubectl get pods]]>", out)

    def test_no_stray_markdown_markers_leak(self):
        out = cp.markdown_to_storage(self.SAMPLE)
        self.assertNotIn("**", out)
        self.assertNotIn("[ ]", out)
        self.assertNotIn("[x]", out)


if __name__ == "__main__":
    unittest.main()
