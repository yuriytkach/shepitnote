#!/usr/bin/env python3

"""
Unit tests for transcribe._normalize_language — pure string logic, no audio,
no faster-whisper (the module is import-safe without it installed).
Run with: python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

# Make the repo root importable so we can import transcribe.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import transcribe


class TestNormalizeLanguage(unittest.TestCase):
    def test_none_is_auto(self):
        """None means auto-detect -> None."""
        self.assertIsNone(transcribe._normalize_language(None))

    def test_empty_is_auto(self):
        """Empty string means auto-detect -> None."""
        self.assertIsNone(transcribe._normalize_language(""))

    def test_whitespace_is_auto(self):
        """Whitespace-only string means auto-detect -> None."""
        self.assertIsNone(transcribe._normalize_language("   "))

    def test_auto_literal_is_auto(self):
        """The literal 'auto' is not a whisper code; collapse it to None."""
        self.assertIsNone(transcribe._normalize_language("auto"))

    def test_auto_uppercase_is_auto(self):
        """'auto' is case-insensitive."""
        self.assertIsNone(transcribe._normalize_language("AUTO"))

    def test_auto_padded_is_auto(self):
        """Surrounding whitespace and mixed case around 'auto' still collapse."""
        self.assertIsNone(transcribe._normalize_language(" Auto "))

    def test_uk_passes_through(self):
        self.assertEqual(transcribe._normalize_language("uk"), "uk")

    def test_ru_passes_through(self):
        self.assertEqual(transcribe._normalize_language("ru"), "ru")

    def test_en_passes_through(self):
        self.assertEqual(transcribe._normalize_language("en"), "en")

    def test_other_code_passes_through(self):
        """Any other faster-whisper code passes through unchanged."""
        self.assertEqual(transcribe._normalize_language("nl"), "nl")

    def test_code_is_stripped(self):
        """A real code with surrounding whitespace is stripped but preserved."""
        self.assertEqual(transcribe._normalize_language(" uk "), "uk")

    def test_real_codes_are_lowercased(self):
        """Real codes are lowercased so -l EN / WHISPER_LANGUAGE=UK just work."""
        self.assertEqual(transcribe._normalize_language("EN"), "en")
        self.assertEqual(transcribe._normalize_language("UK"), "uk")
        self.assertEqual(transcribe._normalize_language(" Ru "), "ru")


if __name__ == "__main__":
    unittest.main()
