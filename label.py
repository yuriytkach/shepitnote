#!/usr/bin/env python3

"""
Interactive speaker labeling
Shows actual quotes from each speaker and prompts user to identify them
"""

import argparse
import json
import os
import sys
import random
from pathlib import Path
from datetime import datetime, timezone

import roster as roster_mod
import speaker_guess


def guess_speaker_names(data, people, model, ollama_url, self_label="You"):
    """Best-effort LLM guess of {speaker_id: name} using quotes + roster.

    Returns {} (no guesses) on any failure — a missing requests module, an
    unreachable Ollama, a timeout, or an unparseable reply — so labeling always
    falls back cleanly to fully-manual entry. The network call is isolated here;
    the prompt/parse logic lives in the pure speaker_guess module.
    """
    if not people:
        return {}
    try:
        import requests
    except ImportError:
        return {}

    prompt = speaker_guess.build_guess_prompt(data, people, self_label=self_label)
    try:
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=300,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
    except Exception as exc:  # network/HTTP/JSON — never fatal for labeling
        print(f"(name-guess unavailable: {exc})", file=sys.stderr)
        return {}

    valid = speaker_guess._ordered_speaker_ids(data)
    return speaker_guess.parse_guess_response(text, valid_ids=valid)


def load_diarized_json(file_path: str) -> dict:
    """Load diarized JSON file"""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text())

    if "segments" not in data or not data["segments"]:
        print("Error: No segments found in file", file=sys.stderr)
        print("Make sure you've run diarization and transcription first", file=sys.stderr)
        sys.exit(1)

    # Check if segments have text
    if "text" not in data["segments"][0]:
        print("Error: Segments don't contain transcribed text", file=sys.stderr)
        print("Make sure you've merged diarization with transcription", file=sys.stderr)
        sys.exit(1)

    return data


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS"""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def get_speaker_samples(data: dict, speaker_id: str, num_samples: int = 3, random_samples: bool = False) -> list:
    """
    Get sample quotes from a speaker

    Args:
        data: Diarized data with segments
        speaker_id: Speaker to get samples for
        num_samples: Number of sample quotes to return
        random_samples: If True, get random samples instead of beginning/middle/end

    Returns:
        List of sample segments with text
    """
    speaker_segments = [
        seg for seg in data["segments"]
        if seg["speaker_id"] == speaker_id and seg["text"].strip()
    ]

    if not speaker_segments:
        return []

    if random_samples:
        # Get random samples
        if len(speaker_segments) <= num_samples:
            return speaker_segments
        return random.sample(speaker_segments, num_samples)
    else:
        # Get samples from beginning, middle, and end
        samples = []
        if len(speaker_segments) >= num_samples:
            # First quote
            samples.append(speaker_segments[0])
            # Middle quote
            samples.append(speaker_segments[len(speaker_segments) // 2])
            # Last quote (or near end)
            samples.append(speaker_segments[-1])
        else:
            # Just return what we have
            samples = speaker_segments[:num_samples]

        return samples


def display_quotes(samples: list, max_length: int = 100):
    """Display quote samples with timestamps"""
    if not samples:
        print("  (No quotes available)")
        return

    print("Sample quotes:")
    for sample in samples:
        timestamp = format_time(sample["start"])
        text = sample["text"].strip()
        # Truncate long quotes
        if len(text) > max_length:
            text = text[:max_length] + "..."
        print(f"  [{timestamp}] \"{text}\"")


def _current_speaker_ids(data):
    """Speaker ids present in the segments right now (recomputed after merges)."""
    seen = []
    for seg in data["segments"]:
        sid = seg["speaker_id"]
        if sid not in seen:
            seen.append(sid)
    return seen


def _drop_speaker(data, speaker_id):
    """Remove a speaker's segments entirely (spurious cluster / echo bleed)."""
    data["segments"] = [s for s in data["segments"] if s["speaker_id"] != speaker_id]
    data.get("speaker_stats", {}).pop(speaker_id, None)
    data.get("labels", {}).pop(speaker_id, None)


def _resolve_merge_target(token, exclude_id, data):
    """Resolve a merge-target token to an existing speaker id.

    Accepts either a raw speaker id ("Remote 1") or a name already assigned to a
    speaker ("Roman"). Returns the speaker id, or None if it can't be resolved
    (or resolves to the speaker being merged).
    """
    token = token.strip()
    current = _current_speaker_ids(data)
    if token in current and token != exclude_id:
        return token
    labels = data.get("labels", {})
    for sid in current:
        if sid == exclude_id:
            continue
        if labels.get(sid, {}).get("name", "").lower() == token.lower():
            return sid
    return None


def _label_entry(name, people, source):
    """Build a label dict, attaching a roster role when the name matches."""
    return {
        "name": name,
        "email": None,
        "role": speaker_guess.role_for(name, people or []),
        "source": source,
        "labeled_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }


def interactive_label_speakers(data: dict, suggestions=None, people=None) -> dict:
    """
    Interactively prompt the user to confirm/correct each speaker.

    Args:
        data: Diarized/merged data with segments (and optional labels/stats)
        suggestions: optional {speaker_id: guessed_name} to pre-fill (from the LLM)
        people: optional roster.Person list, used to attach roles to chosen names

    Returns:
        Updated data with confirmed labels (segments/stats updated by any merges).
    """
    suggestions = suggestions or {}
    people = people or []
    labels = data.setdefault("labels", {})

    speakers = _current_speaker_ids(data)
    if not speakers:
        print("Error: No speakers found in data", file=sys.stderr)
        sys.exit(1)

    print("\nShepitNote Speaker Labeling")
    print("═" * 70)
    print(f"\nFound {len(speakers)} speaker(s) in {data.get('audio_file', 'audio')}")
    print("Enter = accept the [guess] (or keep the label if none) · type a name to set it")
    print("m = more quotes · d = drop this speaker · merge <id|name> = same person as another")
    print()

    handled = set()
    for speaker_id in speakers:
        if speaker_id in handled:
            continue
        # Skip a speaker merged away by an earlier decision.
        if speaker_id not in _current_speaker_ids(data):
            continue

        print("─" * 70)
        stats = data.get("speaker_stats", {}).get(speaker_id, {})
        print(f"{speaker_id} ({format_time(stats.get('total_time', 0))}, "
              f"{stats.get('segment_count', 0)} segments)")
        print()

        samples = get_speaker_samples(data, speaker_id, num_samples=3)
        display_quotes(samples)
        print()

        suggestion = suggestions.get(speaker_id)
        while True:
            try:
                if suggestion:
                    prompt = f"Who is {speaker_id}? [{suggestion}] "
                else:
                    prompt = f"Who is {speaker_id}? "
                response = input(prompt).strip()

                if response.lower() == 'm':
                    print()
                    samples = get_speaker_samples(data, speaker_id, num_samples=5, random_samples=True)
                    display_quotes(samples)
                    print()
                    continue

                if response.lower() == 'd':
                    _drop_speaker(data, speaker_id)
                    handled.add(speaker_id)
                    print(f"🗑  Dropped {speaker_id} (segments removed)")
                    break

                if response.lower().startswith('merge'):
                    target_token = response[len('merge'):].strip()
                    target = _resolve_merge_target(target_token, speaker_id, data)
                    if not target:
                        print(f"  ? Can't find speaker '{target_token}' to merge into. "
                              "Use a speaker id or an already-assigned name.")
                        continue
                    speaker_guess.merge_speakers(data, speaker_id, target)
                    handled.add(speaker_id)
                    tgt_name = labels.get(target, {}).get("name", target)
                    print(f"🔗 Merged {speaker_id} into {target} ({tgt_name})")
                    break

                if not response and suggestion:
                    labels[speaker_id] = _label_entry(suggestion, people, "guess-confirmed")
                    print(f"✓ Labeled as \"{suggestion}\"")
                    break

                if response:
                    labels[speaker_id] = _label_entry(response, people, "manual")
                    print(f"✓ Labeled as \"{response}\"")
                    break

                # Empty with no suggestion: keep the raw id.
                labels[speaker_id] = _label_entry(speaker_id, people, "skipped")
                print(f"⊘ Kept as {speaker_id}")
                break

            except (KeyboardInterrupt, EOFError):
                print("\n\nLabeling interrupted", file=sys.stderr)
                sys.exit(1)

        print()

    data["num_speakers"] = len(_current_speaker_ids(data))
    print("─" * 70)
    print("✓ All speakers labeled!")
    print()
    return data


def auto_label_speakers(data: dict) -> dict:
    """Label detected speakers as Speaker 1, Speaker 2, and so on."""
    speakers = sorted(set(seg["speaker_id"] for seg in data["segments"]))
    labeled_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    data["labels"] = {
        speaker_id: {
            "name": f"Speaker {index}",
            "email": None,
            "role": None,
            "source": "auto",
            "labeled_at": labeled_at,
        }
        for index, speaker_id in enumerate(speakers, start=1)
    }
    return data


def save_labeled(data: dict, output_file: str):
    """Save labeled results to JSON file"""
    output_path = Path(output_file)
    output_path.write_text(json.dumps(data, indent=2))
    print(f"Saved to: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Interactively label speakers with their names"
    )
    parser.add_argument("diarized_file",
                       help="Path to diarized JSON file (_diarized.json)")
    parser.add_argument("-o", "--output",
                       help="Output file (default: input_file_labeled.json)")
    parser.add_argument("--non-interactive", action="store_true",
                       help="Automatically label speakers as Speaker 1, Speaker 2, and so on")
    parser.add_argument("--roster-dir", default=str(Path(__file__).resolve().parent),
                       help="Directory holding roster.txt (known participants) used "
                            "to pre-fill name guesses (default: this script's dir)")
    parser.add_argument("--roster", default=None,
                       help="Named roster roster.<NAME>.txt (default: roster.txt); "
                            "falls back to MEETING_ROSTER env")
    parser.add_argument("--self-name", default=None,
                       help="Name of the local ('You') speaker (roster ground truth)")
    parser.add_argument("--self-role", default=None, help="Role of the local speaker")
    parser.add_argument("--guess", dest="guess", action=argparse.BooleanOptionalAction,
                       default=True,
                       help="Pre-fill each speaker with an LLM name guess from the "
                            "roster + quotes (default: on; --no-guess to disable)")
    parser.add_argument("--auto-guess", action="store_true",
                       help="Apply the LLM guesses non-interactively (no prompts). "
                            "Review the result — guesses can be wrong")
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
                       help="Ollama model for name guessing (default: OLLAMA_MODEL env)")
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://localhost:11434"),
                       help="Ollama API URL for name guessing")

    args = parser.parse_args()

    # Load diarized data
    data = load_diarized_json(args.diarized_file)

    # Determine output file
    if args.output:
        output_file = args.output
    else:
        input_path = Path(args.diarized_file)
        # Replace _diarized.json with _speakers_labeled.json
        if input_path.stem.endswith("_diarized"):
            base_name = input_path.stem.replace("_diarized", "")
            output_file = input_path.parent / f"{base_name}_speakers_labeled.json"
        else:
            output_file = input_path.parent / f"{input_path.stem}_labeled.json"

    # Load the roster (known people + roles) so guesses can be roster-constrained
    # and confirmed names pick up roles. Self identity: CLI overrides env.
    roster_name = args.roster or os.getenv("MEETING_ROSTER")
    people = roster_mod.load_roster(args.roster_dir, roster_name)
    self_name = args.self_name or os.getenv("MEETING_SELF_NAME")
    self_role = args.self_role or os.getenv("MEETING_SELF_ROLE")
    if self_name:
        # Represent an explicit self as a roster person so the guess prompt and
        # role lookup see it even without a '*' line in roster.txt.
        if not any(getattr(p, "is_self", False) for p in people):
            people = people + [roster_mod.Person(self_name, self_role, [], True)]

    # Pre-fill LLM name guesses (best-effort; empty when disabled or unavailable).
    suggestions = {}
    if (args.guess or args.auto_guess) and people:
        print("Guessing speaker names from roster + quotes...", file=sys.stderr)
        suggestions = guess_speaker_names(data, people, args.ollama_model, args.ollama_url)
        if suggestions:
            print(f"Guesses: {suggestions}", file=sys.stderr)

    # Label speakers
    try:
        if args.non_interactive:
            print("Non-interactive mode: auto-labeling speakers", file=sys.stderr)
            data = auto_label_speakers(data)
        elif args.auto_guess:
            print("Auto-guess mode: applying LLM guesses without prompting "
                  "(review the result)", file=sys.stderr)
            data = speaker_guess.apply_names(data, suggestions, people, source="guess")
        else:
            data = interactive_label_speakers(data, suggestions=suggestions, people=people)

        # Save results
        save_labeled(data, output_file)

        print("\nNext step:", file=sys.stderr)
        print(f"  ./shepitnote apply-labels {output_file}", file=sys.stderr)

    except Exception as e:
        print(f"Error during labeling: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
