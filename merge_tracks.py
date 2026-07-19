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
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone


def load_json(file_path: str) -> dict:
    """Load JSON file"""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def merge_tracks(
    voice: dict,
    system: dict,
    you_label: str = "You",
    remote_label: str = "Remote",
    audio_file: str = None,
) -> dict:
    """
    Merge voice-track and system-track transcriptions into one labeled result.

    Args:
        voice: Transcription of the microphone track (the local speaker)
        system: Transcription of the sink-monitor track (the remote side)
        you_label: Speaker id/name for the microphone track
        remote_label: Speaker id/name for the system track
        audio_file: Optional canonical audio file name for the result

    Returns:
        A dict shaped like the diarization pipeline's *_speakers_labeled.json
        (version, segments, speaker_stats, labels, num_speakers, created_at),
        ready for apply_labels.py.
    """
    print("Merging voice and system tracks...", file=sys.stderr)

    # Rank used to break ties deterministically: You before Remote.
    rank = {you_label: 0, remote_label: 1}

    merged_segments = []
    for seg in voice.get("segments", []):
        merged_segments.append({
            "speaker_id": you_label,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        })
    for seg in system.get("segments", []):
        merged_segments.append({
            "speaker_id": remote_label,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        })

    # Interleave chronologically by each track's own timestamps. Ties are
    # broken by (end, speaker rank) so ordering is fully deterministic.
    merged_segments.sort(
        key=lambda s: (s["start"], s["end"], rank.get(s["speaker_id"], 99))
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
        "source": "dual_track",
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

    args = parser.parse_args()

    voice = load_json(args.voice)
    system = load_json(args.system)

    try:
        result = merge_tracks(
            voice,
            system,
            you_label=args.you_label,
            remote_label=args.remote_label,
            audio_file=args.audio_file,
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
