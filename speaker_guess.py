#!/usr/bin/env python3

"""
LLM-assisted speaker-name guessing for ShepitNote (interactive confirm step).

Diarization labels far-side speakers "Remote 1", "Remote 2", ... but cannot know
their real names. This module builds the prompt that asks the summary model to
map each diarized speaker to a real person — using that speaker's own quotes,
how others address them, and the configured roster — and parses the model's
answer. The user then confirms or corrects each guess in label.py.

Stdlib-only by design (same contract as glossary.py / roster.py): the pure logic
here — prompt building, tolerant response parsing, and the segment-level merge —
is imported by label.py and the unit tests and must NOT import requests. The
actual Ollama call lives in label.py (a worker), so this module stays testable
without a network or a model.
"""

import json
import re


def speaker_quotes(data, speaker_id, max_quotes=6, min_words=4):
    """Return up to max_quotes content-bearing quotes for a speaker.

    Prefers the longest segments (they carry the most identifying content) and
    returns them in chronological order. Segments shorter than min_words are
    skipped unless the speaker has nothing longer.
    """
    segs = [s for s in data.get("segments", []) if s.get("speaker_id") == speaker_id]
    texts = [(s["start"], " ".join((s.get("text") or "").split())) for s in segs]
    texts = [(start, t) for start, t in texts if t]
    substantial = [(start, t) for start, t in texts if len(t.split()) >= min_words]
    pool = substantial or texts
    # Longest first to pick the most informative, then restore time order.
    picked = sorted(pool, key=lambda p: len(p[1].split()), reverse=True)[:max_quotes]
    return [t for _start, t in sorted(picked, key=lambda p: p[0])]


def build_guess_prompt(data, people, self_label="You"):
    """Build the prompt asking the model to map speaker ids to roster names.

    people is a list of roster.Person; the model is told to choose only from
    those names (or answer "unknown"). Each speaker is presented with a few of
    their quotes so the model can use both self-reference and how others address
    them. Returns a prompt string that requests a strict JSON object.
    """
    speaker_ids = _ordered_speaker_ids(data)

    roster_lines = []
    for p in people:
        detail = p.name
        if p.role:
            detail += f" ({p.role})"
        if p.aliases:
            detail += f" — also called {', '.join(p.aliases)}"
        if getattr(p, "is_self", False):
            detail += f' [the local speaker, labelled "{self_label}"]'
        roster_lines.append(f"- {detail}")
    roster_text = "\n".join(roster_lines) if roster_lines else "(no roster provided)"

    blocks = []
    for sid in speaker_ids:
        quotes = speaker_quotes(data, sid)
        quoted = "\n".join(f'    "{q}"' for q in quotes) or "    (no quotes)"
        blocks.append(f'Speaker "{sid}" said:\n{quoted}')
    speakers_text = "\n\n".join(blocks)

    return f"""You are matching diarized meeting speakers to real people.

Known people who may be in this meeting:
{roster_text}

Below are the diarized speakers and samples of what each said. Speakers may
address each other by name, so use both what a speaker says about themselves and
how others refer to them.

{speakers_text}

For EACH speaker id, decide which known person they most likely are. Rules:
- Choose a name ONLY from the known people list above. Use the canonical name (not an alias).
- A speaker who addresses several other people by name is usually the facilitator running the call — they are probably NOT any of the people they name.
- If you cannot tell, use "unknown". A confident "unknown" is better than a wrong name.
- Never map two different speaker ids to the same person.

Respond with ONLY a JSON object mapping each speaker id to a name, e.g.:
{{"Remote 1": "Roman", "Remote 2": "unknown"}}
No prose, no code fence."""


def _ordered_speaker_ids(data):
    """Speaker ids in first-appearance order over the segments (stable, testable)."""
    order = []
    for s in data.get("segments", []):
        sid = s.get("speaker_id")
        if sid is not None and sid not in order:
            order.append(sid)
    return order


def parse_guess_response(text, valid_ids=None):
    """Parse the model's JSON reply into a {speaker_id: name} dict.

    Tolerant of surrounding prose / code fences: extracts the first {...} block.
    "unknown"/""/None values are dropped. When valid_ids is given, only those ids
    are kept. Returns {} on any parse failure rather than raising.
    """
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        raw = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    result = {}
    for sid, name in raw.items():
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or name.lower() == "unknown":
            continue
        if valid_ids is not None and sid not in valid_ids:
            continue
        result[sid] = name
    return result


def role_for(name, people):
    """Return the roster role for a name (case-insensitive), or None."""
    for p in people:
        if p.name.lower() == name.lower():
            return p.role
    return None


def apply_names(data, mapping, people=None, source="guess"):
    """Set label names (and roster roles) for the given {speaker_id: name} map.

    Mutates and returns data. Only touches speaker ids present in the mapping;
    unmapped speakers keep their existing label. When people is given, a matching
    roster role is attached.
    """
    labels = data.setdefault("labels", {})
    people = people or []
    for sid, name in mapping.items():
        entry = labels.setdefault(sid, {})
        entry["name"] = name
        entry["role"] = role_for(name, people)
        entry["source"] = source
    return data


def merge_speakers(data, src_id, dst_id):
    """Merge speaker src_id into dst_id (same physical person split by diarization).

    Reassigns every src segment to dst, folds src's stats into dst, drops src's
    label, and updates num_speakers. Mutates and returns data. A no-op if src and
    dst are equal or src is absent.
    """
    if src_id == dst_id:
        return data

    for seg in data.get("segments", []):
        if seg.get("speaker_id") == src_id:
            seg["speaker_id"] = dst_id

    stats = data.get("speaker_stats")
    if isinstance(stats, dict) and src_id in stats:
        src = stats.pop(src_id)
        dst = stats.setdefault(dst_id, {"total_time": 0.0, "segment_count": 0, "word_count": 0})
        for k in ("total_time", "segment_count", "word_count"):
            if k in src:
                dst[k] = dst.get(k, 0) + src[k]

    labels = data.get("labels")
    if isinstance(labels, dict) and src_id in labels:
        labels.pop(src_id)

    remaining = {s.get("speaker_id") for s in data.get("segments", [])}
    data["num_speakers"] = len(remaining)
    return data
