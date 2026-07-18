#!/usr/bin/env python3

"""
Unit tests for merge_tracks.py — pure dict logic, no audio, no faster-whisper.
Run with: python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

# Make the repo root importable so we can import merge_tracks / apply_labels.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge_tracks
import apply_labels


def _track(segments, language="en"):
    """Build a minimal transcribe.py-style track dict."""
    return {
        "language": language,
        "segments": segments,
        "text": " ".join(s["text"] for s in segments),
    }


class TestMergeTracks(unittest.TestCase):
    def test_interleaving_order(self):
        """Segments interleave chronologically across the two tracks."""
        voice = _track([
            {"start": 0.0, "end": 2.0, "text": "hello there"},
            {"start": 6.0, "end": 8.0, "text": "sounds good"},
        ])
        system = _track([
            {"start": 2.5, "end": 5.0, "text": "hi how are you"},
        ])

        result = merge_tracks.merge_tracks(voice, system)
        speakers = [s["speaker_id"] for s in result["segments"]]
        self.assertEqual(speakers, ["You", "Remote", "You"])
        starts = [s["start"] for s in result["segments"]]
        self.assertEqual(starts, sorted(starts))

    def test_origin_tagging(self):
        """Every voice segment is You; every system segment is Remote."""
        voice = _track([
            {"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 10.0, "end": 11.0, "text": "b"},
        ])
        system = _track([
            {"start": 3.0, "end": 4.0, "text": "c"},
            {"start": 5.0, "end": 6.0, "text": "d"},
        ])

        result = merge_tracks.merge_tracks(voice, system)
        you_texts = {s["text"] for s in result["segments"] if s["speaker_id"] == "You"}
        remote_texts = {s["text"] for s in result["segments"] if s["speaker_id"] == "Remote"}
        self.assertEqual(you_texts, {"a", "b"})
        self.assertEqual(remote_texts, {"c", "d"})

    def test_deterministic_tiebreak(self):
        """Identical timestamps put You before Remote."""
        voice = _track([{"start": 1.0, "end": 2.0, "text": "mine"}])
        system = _track([{"start": 1.0, "end": 2.0, "text": "theirs"}])

        result = merge_tracks.merge_tracks(voice, system)
        speakers = [s["speaker_id"] for s in result["segments"]]
        self.assertEqual(speakers, ["You", "Remote"])

    def test_speaker_stats(self):
        """total_time, segment_count, word_count are computed per speaker."""
        voice = _track([
            {"start": 0.0, "end": 2.0, "text": "one two three"},   # 3 words, 2.0s
            {"start": 4.0, "end": 5.0, "text": "four"},            # 1 word, 1.0s
        ])
        system = _track([
            {"start": 2.0, "end": 3.5, "text": "five six"},        # 2 words, 1.5s
        ])

        result = merge_tracks.merge_tracks(voice, system)
        stats = result["speaker_stats"]
        self.assertAlmostEqual(stats["You"]["total_time"], 3.0)
        self.assertEqual(stats["You"]["segment_count"], 2)
        self.assertEqual(stats["You"]["word_count"], 4)
        self.assertAlmostEqual(stats["Remote"]["total_time"], 1.5)
        self.assertEqual(stats["Remote"]["segment_count"], 1)
        self.assertEqual(stats["Remote"]["word_count"], 2)
        self.assertEqual(result["num_speakers"], 2)

    def test_labels_present(self):
        """Labels dict contains both You and Remote with name fields."""
        voice = _track([{"start": 0.0, "end": 1.0, "text": "hi"}])
        system = _track([{"start": 1.0, "end": 2.0, "text": "yo"}])

        result = merge_tracks.merge_tracks(voice, system)
        self.assertIn("You", result["labels"])
        self.assertIn("Remote", result["labels"])
        self.assertEqual(result["labels"]["You"]["name"], "You")
        self.assertEqual(result["labels"]["Remote"]["name"], "Remote")

    def test_empty_system_track(self):
        """In-person meeting: empty system track yields only You segments."""
        voice = _track([
            {"start": 0.0, "end": 1.0, "text": "just me"},
        ])
        system = _track([])

        result = merge_tracks.merge_tracks(voice, system)
        self.assertEqual(len(result["segments"]), 1)
        self.assertTrue(all(s["speaker_id"] == "You" for s in result["segments"]))
        self.assertNotIn("Remote", result["labels"])
        self.assertEqual(result["num_speakers"], 1)
        # language falls back correctly (voice had a language)
        self.assertEqual(result["language"], "en")

    def test_empty_voice_track(self):
        """Symmetric case: empty voice track yields only Remote segments."""
        voice = _track([], language=None)
        system = _track([
            {"start": 0.0, "end": 1.0, "text": "remote only"},
        ], language="nl")

        result = merge_tracks.merge_tracks(voice, system)
        self.assertEqual(len(result["segments"]), 1)
        self.assertTrue(all(s["speaker_id"] == "Remote" for s in result["segments"]))
        self.assertNotIn("You", result["labels"])
        # language falls back to system when voice has none
        self.assertEqual(result["language"], "nl")

    def test_both_empty(self):
        """Both tracks empty: no crash, no segments, no labels."""
        result = merge_tracks.merge_tracks(_track([]), _track([]))
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["labels"], {})
        self.assertEqual(result["num_speakers"], 0)

    def test_schema_feeds_apply_labels(self):
        """Output schema flows through apply_labels.py to a [You]/[Remote] transcript."""
        voice = _track([
            {"start": 0.0, "end": 2.0, "text": "hello team"},
            {"start": 6.0, "end": 8.0, "text": "agreed"},
        ])
        system = _track([
            {"start": 2.5, "end": 5.0, "text": "thanks for joining"},
        ])

        result = merge_tracks.merge_tracks(voice, system)
        transcript = apply_labels.apply_labels_to_transcript(result, "txt")
        self.assertIsInstance(transcript, str)
        self.assertIn("[You]", transcript)
        self.assertIn("[Remote]", transcript)
        # You speaks first, then Remote, then You again.
        self.assertLess(transcript.index("[You]"), transcript.index("[Remote]"))


if __name__ == "__main__":
    unittest.main()
