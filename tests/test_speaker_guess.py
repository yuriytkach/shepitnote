#!/usr/bin/env python3

"""
Unit tests for speaker_guess.py — pure stdlib logic, no requests/ollama.
Run with: python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import speaker_guess
import roster


def _data():
    return {
        "segments": [
            {"speaker_id": "Remote 1", "start": 0.0, "end": 2.0, "text": "Эдуард есть причина почему ты здесь сегодня"},
            {"speaker_id": "You", "start": 2.0, "end": 3.0, "text": "да"},
            {"speaker_id": "Remote 1", "start": 3.0, "end": 4.0, "text": "ок"},
            {"speaker_id": "Remote 2", "start": 4.0, "end": 8.0, "text": "я закончил рефакторинг формы регистрации на этой неделе"},
        ],
        "speaker_stats": {
            "Remote 1": {"total_time": 3.0, "segment_count": 2, "word_count": 8},
            "You": {"total_time": 1.0, "segment_count": 1, "word_count": 1},
            "Remote 2": {"total_time": 4.0, "segment_count": 1, "word_count": 7},
        },
        "labels": {
            "Remote 1": {"name": "Remote 1"},
            "You": {"name": "You"},
            "Remote 2": {"name": "Remote 2"},
        },
        "num_speakers": 3,
    }


class TestSpeakerQuotes(unittest.TestCase):
    def test_prefers_substantial_and_chronological(self):
        q = speaker_guess.speaker_quotes(_data(), "Remote 1", min_words=4)
        # Only the >=4-word segment qualifies; "ок" is dropped.
        self.assertEqual(len(q), 1)
        self.assertIn("Эдуард", q[0])

    def test_falls_back_when_all_short(self):
        data = {"segments": [
            {"speaker_id": "X", "start": 0, "end": 1, "text": "да"},
            {"speaker_id": "X", "start": 1, "end": 2, "text": "нет"},
        ]}
        q = speaker_guess.speaker_quotes(data, "X", min_words=4)
        self.assertEqual(set(q), {"да", "нет"})


class TestBuildGuessPrompt(unittest.TestCase):
    def setUp(self):
        self.people = roster.parse_roster(
            "* Yuriy | CTO | Юрий\nEduard | dev lead | Эдуард\nViktor | frontend | Витя"
        )

    def test_contains_ids_roster_and_json_instruction(self):
        p = speaker_guess.build_guess_prompt(_data(), self.people)
        for sid in ("Remote 1", "Remote 2", "You"):
            self.assertIn(sid, p)
        self.assertIn("Eduard", p)
        self.assertIn("Витя", p)           # alias surfaced
        self.assertIn('labelled "You"', p)  # self annotated
        self.assertIn("JSON", p)
        self.assertIn("facilitator", p.lower())  # heuristic present

    def test_no_roster_still_builds(self):
        p = speaker_guess.build_guess_prompt(_data(), [])
        self.assertIn("no roster provided", p)


class TestParseGuessResponse(unittest.TestCase):
    def test_plain_json(self):
        m = speaker_guess.parse_guess_response('{"Remote 1": "Roman", "Remote 2": "unknown"}')
        self.assertEqual(m, {"Remote 1": "Roman"})  # unknown dropped

    def test_with_code_fence_and_prose(self):
        text = 'Here is the mapping:\n```json\n{"Remote 1": "Viktor"}\n```\nDone.'
        self.assertEqual(speaker_guess.parse_guess_response(text), {"Remote 1": "Viktor"})

    def test_filters_invalid_ids(self):
        m = speaker_guess.parse_guess_response(
            '{"Remote 1": "Roman", "Ghost": "Bob"}', valid_ids=["Remote 1"]
        )
        self.assertEqual(m, {"Remote 1": "Roman"})

    def test_garbage_and_nondict(self):
        self.assertEqual(speaker_guess.parse_guess_response("no json here"), {})
        self.assertEqual(speaker_guess.parse_guess_response("[1,2,3]"), {})
        self.assertEqual(speaker_guess.parse_guess_response(""), {})

    def test_empty_and_whitespace_names_dropped(self):
        m = speaker_guess.parse_guess_response('{"A": "", "B": "   ", "C": "Roman"}')
        self.assertEqual(m, {"C": "Roman"})


class TestApplyNames(unittest.TestCase):
    def test_sets_name_role_source(self):
        people = roster.parse_roster("Viktor | frontend developer")
        data = speaker_guess.apply_names(_data(), {"Remote 2": "Viktor"}, people)
        lab = data["labels"]["Remote 2"]
        self.assertEqual(lab["name"], "Viktor")
        self.assertEqual(lab["role"], "frontend developer")
        self.assertEqual(lab["source"], "guess")
        # Unmapped speaker untouched.
        self.assertEqual(data["labels"]["Remote 1"]["name"], "Remote 1")

    def test_role_none_when_not_in_roster(self):
        data = speaker_guess.apply_names(_data(), {"Remote 2": "Stranger"}, [])
        self.assertIsNone(data["labels"]["Remote 2"]["role"])


class TestMergeSpeakers(unittest.TestCase):
    def test_reassigns_segments_and_folds_stats(self):
        data = speaker_guess.merge_speakers(_data(), "Remote 2", "Remote 1")
        # No segment references the merged-away id.
        self.assertNotIn("Remote 2", {s["speaker_id"] for s in data["segments"]})
        # Stats folded into destination.
        st = data["speaker_stats"]["Remote 1"]
        self.assertEqual(st["segment_count"], 3)   # 2 + 1
        self.assertEqual(st["word_count"], 15)      # 8 + 7
        self.assertAlmostEqual(st["total_time"], 7.0)
        self.assertNotIn("Remote 2", data["speaker_stats"])
        self.assertNotIn("Remote 2", data["labels"])
        self.assertEqual(data["num_speakers"], 2)

    def test_noop_on_equal(self):
        before = _data()
        after = speaker_guess.merge_speakers(_data(), "Remote 1", "Remote 1")
        self.assertEqual(after["num_speakers"], before["num_speakers"])


if __name__ == "__main__":
    unittest.main()
