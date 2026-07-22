#!/usr/bin/env python3

"""
Unit tests for summarize.resolve_summary_language and _build_summary_prompt —
pure prompt-building logic, no network and no Ollama. Run with:
    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

# Make the repo root importable so we can import summarize.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import summarize


class TestResolveSummaryLanguage(unittest.TestCase):
    def test_none_means_no_language(self):
        self.assertIsNone(summarize.resolve_summary_language(None))

    def test_empty_means_no_language(self):
        self.assertIsNone(summarize.resolve_summary_language(""))

    def test_auto_means_no_language(self):
        self.assertIsNone(summarize.resolve_summary_language("auto"))
        self.assertIsNone(summarize.resolve_summary_language("AUTO"))

    def test_known_codes_map_to_full_names(self):
        self.assertEqual(summarize.resolve_summary_language("en"), "English")
        self.assertEqual(summarize.resolve_summary_language("uk"), "Ukrainian")
        self.assertEqual(summarize.resolve_summary_language("ru"), "Russian")

    def test_known_codes_are_case_insensitive(self):
        self.assertEqual(summarize.resolve_summary_language("UK"), "Ukrainian")
        self.assertEqual(summarize.resolve_summary_language(" Ru "), "Russian")

    def test_unknown_code_passes_through(self):
        """A code with no mapping (e.g. 'pl') is passed through as given."""
        self.assertEqual(summarize.resolve_summary_language("pl"), "pl")

    def test_already_spelled_out_name_passes_through(self):
        """A full language name is passed through with its original casing."""
        self.assertEqual(summarize.resolve_summary_language("Polish"), "Polish")


class TestBuildSummaryPromptLanguage(unittest.TestCase):
    def test_no_language_reproduces_prompt_unchanged(self):
        """With summary_language=None the {language_instruction} slot is empty,
        so the prompt is byte-for-byte identical to before this option existed."""
        prompt = summarize._build_summary_prompt("hello transcript")
        self.assertIn("transcripts.\n\nProduce the following sections", prompt)
        self.assertNotIn("Write your ENTIRE response", prompt)

    def test_language_instruction_included_when_set(self):
        prompt = summarize._build_summary_prompt("hello transcript", summary_language="Ukrainian")
        self.assertIn("Write your ENTIRE response in Ukrainian", prompt)
        self.assertIn("translate each one into Ukrainian", prompt)

    def test_language_instruction_composes_with_glossary_and_roster(self):
        prompt = summarize._build_summary_prompt(
            "hello transcript",
            known_terms=["Kubernetes"],
            roster_block="Known participants: Alice\n",
            summary_language="Russian",
        )
        self.assertIn("Write your ENTIRE response in Russian", prompt)
        self.assertIn("Kubernetes", prompt)
        self.assertIn("Known participants: Alice", prompt)


if __name__ == "__main__":
    unittest.main()
