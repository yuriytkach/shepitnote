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


def _diar(segments):
    """Build a minimal diarize.py-style result dict (pyannote output)."""
    return {"version": "1.0", "segments": segments, "num_speakers": len(
        {s["speaker_id"] for s in segments})}


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


class TestRemoteDiarization(unittest.TestCase):
    """Optional per-speaker labeling of the system (Remote) track — issue #11."""

    def test_splits_remote_into_numbered_speakers(self):
        """Two far-side speakers become Remote 1 / Remote 2; You is untouched."""
        voice = _track([
            {"start": 0.0, "end": 2.0, "text": "hi team"},
            {"start": 12.0, "end": 13.0, "text": "sounds good"},
        ])
        system = _track([
            {"start": 3.0, "end": 5.0, "text": "glad to be here"},
            {"start": 6.0, "end": 8.0, "text": "likewise"},
            {"start": 9.0, "end": 11.0, "text": "one question first"},
        ])
        diar = _diar([
            {"speaker_id": "SPEAKER_01", "start": 3.0, "end": 5.0},
            {"speaker_id": "SPEAKER_00", "start": 5.9, "end": 8.2},
            {"speaker_id": "SPEAKER_01", "start": 8.9, "end": 11.2},
        ])

        result = merge_tracks.merge_tracks(voice, system, system_diarization=diar)
        speakers = [s["speaker_id"] for s in result["segments"]]
        # First far-side speaker (SPEAKER_01 at t=3) is Remote 1, next is Remote 2.
        self.assertEqual(
            speakers, ["You", "Remote 1", "Remote 2", "Remote 1", "You"]
        )
        self.assertEqual(result["num_speakers"], 3)
        self.assertEqual(result["source"], "dual_track_diarized")
        self.assertEqual(set(result["labels"]), {"You", "Remote 1", "Remote 2"})

    def test_numbering_follows_first_appearance_not_pyannote_index(self):
        """Remote N is ordered by who spoke first, not pyannote's SPEAKER_NN."""
        voice = _track([])
        system = _track([
            {"start": 1.0, "end": 2.0, "text": "first speaker"},
            {"start": 3.0, "end": 4.0, "text": "second speaker"},
        ])
        # pyannote labels the first talker SPEAKER_05 and the second SPEAKER_02.
        diar = _diar([
            {"speaker_id": "SPEAKER_05", "start": 1.0, "end": 2.0},
            {"speaker_id": "SPEAKER_02", "start": 3.0, "end": 4.0},
        ])
        result = merge_tracks.merge_tracks(voice, system, system_diarization=diar)
        by_text = {s["text"]: s["speaker_id"] for s in result["segments"]}
        self.assertEqual(by_text["first speaker"], "Remote 1")
        self.assertEqual(by_text["second speaker"], "Remote 2")

    def test_single_detected_speaker_keeps_flat_label(self):
        """One detected far-side speaker stays plain Remote (no 'Remote 1')."""
        voice = _track([{"start": 0.0, "end": 1.0, "text": "hi"}])
        system = _track([
            {"start": 2.0, "end": 3.0, "text": "hello"},
            {"start": 4.0, "end": 5.0, "text": "still me"},
        ])
        diar = _diar([
            {"speaker_id": "SPEAKER_00", "start": 2.0, "end": 3.0},
            {"speaker_id": "SPEAKER_00", "start": 4.0, "end": 5.0},
        ])
        result = merge_tracks.merge_tracks(voice, system, system_diarization=diar)
        remote_ids = {s["speaker_id"] for s in result["segments"]
                      if s["speaker_id"] != "You"}
        self.assertEqual(remote_ids, {"Remote"})
        # No numbering ⇒ treated as the plain dual-track case.
        self.assertEqual(result["source"], "dual_track")

    def test_empty_diarization_falls_back_to_flat(self):
        """A diarization with no segments degrades to the single Remote label."""
        voice = _track([{"start": 0.0, "end": 1.0, "text": "hi"}])
        system = _track([{"start": 2.0, "end": 3.0, "text": "hello"}])
        result = merge_tracks.merge_tracks(
            voice, system, system_diarization=_diar([])
        )
        self.assertEqual(
            [s["speaker_id"] for s in result["segments"]], ["You", "Remote"]
        )
        self.assertEqual(result["source"], "dual_track")

    def test_you_is_never_diarized(self):
        """Even with a diarization present, the mic track stays a clean You."""
        voice = _track([
            {"start": 0.0, "end": 2.0, "text": "me talking"},
            {"start": 6.0, "end": 8.0, "text": "me again"},
        ])
        system = _track([
            {"start": 3.0, "end": 4.0, "text": "them"},
            {"start": 9.0, "end": 10.0, "text": "them two"},
        ])
        diar = _diar([
            {"speaker_id": "SPEAKER_00", "start": 3.0, "end": 4.0},
            {"speaker_id": "SPEAKER_01", "start": 9.0, "end": 10.0},
        ])
        result = merge_tracks.merge_tracks(voice, system, system_diarization=diar)
        you_texts = {s["text"] for s in result["segments"]
                     if s["speaker_id"] == "You"}
        self.assertEqual(you_texts, {"me talking", "me again"})

    def test_per_speaker_stats_and_apply_labels(self):
        """Stats aggregate per remote speaker and render as [Remote N]."""
        voice = _track([{"start": 0.0, "end": 1.0, "text": "hi"}])
        system = _track([
            {"start": 2.0, "end": 4.0, "text": "one two three"},   # R1: 2.0s, 3w
            {"start": 5.0, "end": 6.0, "text": "four"},            # R2: 1.0s, 1w
            {"start": 7.0, "end": 8.0, "text": "five"},            # R1: 1.0s, 1w
        ])
        diar = _diar([
            {"speaker_id": "A", "start": 2.0, "end": 4.0},
            {"speaker_id": "B", "start": 5.0, "end": 6.0},
            {"speaker_id": "A", "start": 7.0, "end": 8.0},
        ])
        result = merge_tracks.merge_tracks(voice, system, system_diarization=diar)
        stats = result["speaker_stats"]
        self.assertAlmostEqual(stats["Remote 1"]["total_time"], 3.0)
        self.assertEqual(stats["Remote 1"]["segment_count"], 2)
        self.assertEqual(stats["Remote 1"]["word_count"], 4)
        self.assertAlmostEqual(stats["Remote 2"]["total_time"], 1.0)

        transcript = apply_labels.apply_labels_to_transcript(result, "txt")
        self.assertIn("[Remote 1]", transcript)
        self.assertIn("[Remote 2]", transcript)
        self.assertNotIn("[Remote]", transcript.replace("[Remote 1]", "").replace("[Remote 2]", ""))

    def test_custom_remote_label_is_respected(self):
        """A custom remote_label carries through to the numbered labels."""
        voice = _track([])
        system = _track([
            {"start": 1.0, "end": 2.0, "text": "a"},
            {"start": 3.0, "end": 4.0, "text": "b"},
        ])
        diar = _diar([
            {"speaker_id": "SPEAKER_00", "start": 1.0, "end": 2.0},
            {"speaker_id": "SPEAKER_01", "start": 3.0, "end": 4.0},
        ])
        result = merge_tracks.merge_tracks(
            voice, system, remote_label="Guest", system_diarization=diar
        )
        self.assertEqual(set(result["labels"]), {"Guest 1", "Guest 2"})


if __name__ == "__main__":
    unittest.main()
