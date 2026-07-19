#!/usr/bin/env python3

"""
Merge two per-track transcriptions into one labeled transcript.

Dual-track recording captures the microphone (you) and the sink monitor
(remote) as two independent, time-synchronized WAVs. Each track is
transcribed separately by transcribe.py, producing two JSON files with
per-segment start/end/text. This script tags every voice-track segment as
"You" and every system-track segment as "Remote" (labeling by track of
origin, no diarization needed), interleaves them by each track's own start
timestamp, and emits a *_speakers_labeled.json that apply_labels.py consumes
unchanged.

Optionally (issue #11), a pyannote diarization of the *system track only* can
be supplied via --system-diarization. When present, the flat "Remote" label is
split into per-speaker labels ("Remote 1", "Remote 2", ...) so a call with
several people on the far side attributes each remote line to a distinct
speaker. This is confined to the system track: the microphone track stays a
clean "You", so the diarization guesswork never touches the local voice.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# find_speaker_at_time lives in the sibling diarization merger; reuse it so the
# per-speaker matching here behaves identically to the full-diarization path.
# merge_tracks.py runs from SCRIPT_DIR (sys.path[0]) and tests put the repo root
# on sys.path, so this import resolves in both cases.
from merge_diarization import find_speaker_at_time


def load_json(file_path: str) -> dict:
    """Load JSON file"""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def _remote_labels_for_segments(
    sys_segments: list,
    diar_segments: list,
    remote_label: str,
) -> list:
    """Compute a speaker label per system-track segment, aligned to sys_segments.

    Without usable diarization (diar_segments empty), every remote segment gets
    the single flat remote_label — the default You-vs-Remote behavior. With a
    diarization of the remote track, each segment is matched to a pyannote
    speaker by its start time and relabeled to a per-speaker name ("Remote 1",
    "Remote 2", ...) ordered by first appearance. A lone detected speaker keeps
    the plain remote_label (numbering only kicks in when it actually helps).

    Whisper emits segments in chronological order, so iterating sys_segments in
    place gives first-appearance ordering; the returned list is positionally
    aligned to sys_segments for a straight zip() at the call site.
    """
    if not diar_segments:
        return [remote_label] * len(sys_segments)

    raw = [find_speaker_at_time(seg["start"], diar_segments) for seg in sys_segments]

    # First-appearance order of the raw pyannote ids, so Remote 1 is whoever
    # spoke first on the far side.
    order = []
    for rid in raw:
        if rid not in order:
            order.append(rid)

    # 0 or 1 distinct remote speakers → keep the flat label (no "Remote 1" for a
    # single person; matches the non-diarized output).
    if len(order) <= 1:
        return [remote_label] * len(sys_segments)

    mapping = {rid: f"{remote_label} {i}" for i, rid in enumerate(order, start=1)}
    return [mapping[rid] for rid in raw]


def merge_tracks(
    voice: dict,
    system: dict,
    you_label: str = "You",
    remote_label: str = "Remote",
    audio_file: str = None,
    system_diarization: dict = None,
) -> dict:
    """
    Merge voice-track and system-track transcriptions into one labeled result.

    Args:
        voice: Transcription of the microphone track (the local speaker)
        system: Transcription of the sink-monitor track (the remote side)
        you_label: Speaker id/name for the microphone track
        remote_label: Speaker id/name for the system track
        audio_file: Optional canonical audio file name for the result
        system_diarization: Optional pyannote diarization of the system track
            (a diarize.py result dict). When it carries segments, the remote
            side is split into per-speaker labels ("Remote 1", "Remote 2", ...);
            the microphone track is never diarized and stays you_label.

    Returns:
        A dict shaped like the diarization pipeline's *_speakers_labeled.json
        (version, segments, speaker_stats, labels, num_speakers, created_at),
        ready for apply_labels.py.
    """
    print("Merging voice and system tracks...", file=sys.stderr)

    merged_segments = []
    for seg in voice.get("segments", []):
        merged_segments.append({
            "speaker_id": you_label,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        })

    sys_segments = system.get("segments", [])
    diar_segments = (system_diarization or {}).get("segments") or []
    remote_labels = _remote_labels_for_segments(sys_segments, diar_segments, remote_label)
    remote_diarized = any(lbl != remote_label for lbl in remote_labels)
    for seg, speaker in zip(sys_segments, remote_labels):
        merged_segments.append({
            "speaker_id": speaker,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        })

    # Interleave chronologically by each track's own timestamps. Ties put You
    # first; remote speakers keep insertion order among themselves (stable sort),
    # so ordering is fully deterministic.
    merged_segments.sort(
        key=lambda s: (s["start"], s["end"], 0 if s["speaker_id"] == you_label else 1)
    )

    # Per-speaker statistics (mirrors merge_diarization.py).
    speaker_stats = {}
    for seg in merged_segments:
        speaker = seg["speaker_id"]
        if speaker not in speaker_stats:
            speaker_stats[speaker] = {
                "total_time": 0.0,
                "segment_count": 0,
                "word_count": 0,
            }
        speaker_stats[speaker]["total_time"] += (seg["end"] - seg["start"])
        speaker_stats[speaker]["segment_count"] += 1
        speaker_stats[speaker]["word_count"] += len(seg["text"].split())

    # Only label speakers that actually appear (an in-person meeting has no
    # remote audio, so the system track may be empty).
    labeled_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    labels = {}
    for speaker in speaker_stats:
        labels[speaker] = {
            "name": speaker,
            "email": None,
            "role": None,
            "source": "track",
            "labeled_at": labeled_at,
        }

    language = voice.get("language") or system.get("language")

    result = {
        "version": "1.0",
        "audio_file": audio_file,
        "duration": None,
        "language": language,
        "transcription_model": "faster-whisper",
        "num_speakers": len(speaker_stats),
        "created_at": labeled_at,
        "segments": merged_segments,
        "speaker_stats": speaker_stats,
        "labels": labels,
        "source": "dual_track_diarized" if remote_diarized else "dual_track",
    }

    print(f"Merged {len(merged_segments)} segments", file=sys.stderr)
    print(f"Speakers: {', '.join(speaker_stats) or '(none)'}", file=sys.stderr)

    return result


def save_merged(result: dict, output_file: str):
    """Save merged results to JSON file"""
    output_path = Path(output_file)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"\nMerged data saved to: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Merge voice and system track transcriptions into a "
                    "labeled You/Remote transcript"
    )
    parser.add_argument("--voice", required=True,
                        help="Path to the microphone track transcription JSON")
    parser.add_argument("--system", required=True,
                        help="Path to the system (sink monitor) track transcription JSON")
    parser.add_argument("-o", "--output", required=True,
                        help="Output file (_speakers_labeled.json)")
    parser.add_argument("--audio-file",
                        help="Canonical audio file name to record in the output")
    parser.add_argument("--you-label", default="You",
                        help="Label for the microphone track (default: You)")
    parser.add_argument("--remote-label", default="Remote",
                        help="Label for the system track (default: Remote)")
    parser.add_argument("--system-diarization",
                        help="Optional pyannote diarization JSON of the system "
                             "track (from diarize.py). When given, splits the "
                             "single Remote label into per-speaker Remote 1/2/...")

    args = parser.parse_args()

    voice = load_json(args.voice)
    system = load_json(args.system)
    system_diarization = load_json(args.system_diarization) if args.system_diarization else None

    try:
        result = merge_tracks(
            voice,
            system,
            you_label=args.you_label,
            remote_label=args.remote_label,
            audio_file=args.audio_file,
            system_diarization=system_diarization,
        )

        save_merged(result, args.output)

        print("\nNext step:", file=sys.stderr)
        print(f"  ./shepitnote apply-labels {args.output}", file=sys.stderr)

    except Exception as e:
        print(f"Error during merge: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
