#!/usr/bin/env python3

"""
Helpers + tiny CLI for the guided `hushnote meeting` terminal flow (issue #5).

The interactive record -> review -> confirm -> publish loop itself lives in the
bash `meeting_ui()` function in `hushnote` (plain line prompts, works over SSH).
This module holds the small pure pieces that loop shells out to, so they can be
unit-tested without a mic, Ollama or the network:

  * configured_targets(env)   -> which publishers are configured. Delegates to the
    dispatcher's enabled_publishers so the guided UI and the automatic
    POST_SUMMARY_HOOK agree on "configured" exactly.
  * parse_yes_no(answer)      -> the fail-safe confirm gate: True ONLY for an
    explicit yes; empty / EOF / anything-else is False, so a stray Enter, a piped
    blank line or a closed stdin never publishes.
  * update_metadata_title()   -> rewrite the human title in <base>_metadata.json,
    tolerant of a missing or corrupt file, so the publishers pick up the edit.
  * read_metadata_title()     -> current human title (for the edit prompt).
  * detect_language()         -> detected language from the sibling transcription
    JSON(s) (transcribe.py records it), for the review screen.

CLI (stdout only, stdlib only, no network):
  meeting_ui.py targets                 print configured targets, one per line
  meeting_ui.py confirm [ANSWER]        exit 0 iff yes (ANSWER, else one stdin line)
  meeting_ui.py get-title METAFILE      print current human title (may be empty)
  meeting_ui.py set-title METAFILE T    set human title; print the stored value
  meeting_ui.py language BASE_DIR BASE  print detected language, or 'unknown'

Run the tests with: python3 -m unittest discover -s tests
"""

import json
import os
import sys
from pathlib import Path

# Reuse the dispatcher's env-presence check so "configured targets" in the guided
# UI and in the automatic POST_SUMMARY_HOOK never diverge. hooks/ is importable
# with no network and without `requests` installed (both publishers guard it).
_HOOKS_DIR = Path(__file__).resolve().parent / "hooks"
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))
from publish import enabled_publishers  # noqa: E402


# Only an explicit yes counts. Kept deliberately tight (no "ok"/"sure") so the
# gate is predictable and hard to trip by accident.
_YES = {"y", "yes"}

# Sibling transcription JSONs that may carry a top-level "language", most specific
# meeting-name first. Single track writes <base>.json (or <base>_trimmed.json when
# the tail was trimmed); dual track writes <base>.voice.json / <base>.system.json.
_LANG_JSON_SUFFIXES = (
    ".json",
    "_trimmed.json",
    ".voice.json",
    ".system.json",
    "_speakers_labeled.json",
)


def parse_yes_no(answer):
    """Fail-safe yes/no. True ONLY for an explicit yes ('y' or 'yes', any case,
    surrounding whitespace ignored). None (EOF / closed stdin), an empty or blank
    string, 'n', 'maybe' and anything else are all False, so a default, blank or
    EOF answer can never trigger a publish."""
    if answer is None:
        return False
    return answer.strip().lower() in _YES


def configured_targets(env):
    """Ordered list of publish targets configured in `env` (a mapping such as
    os.environ): 'confluence' when CONFLUENCE_BASE_URL is set, then 'slack' when
    SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN is set. Delegates to the dispatcher's
    enabled_publishers so the guided UI and the auto-hook stay in lock-step; the
    confluence-before-slack order also lets a Slack post link the Confluence page."""
    return enabled_publishers(env)


def read_metadata_title(path):
    """Current human title from the metadata JSON at `path`. Returns '' when the
    file is missing, unreadable, not a JSON object, or has no (or a null) title."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("title") or "")


def update_metadata_title(path, new_title):
    """Set metadata['title'] = new_title in the JSON file at `path`, preserving
    every other field, and write it back (2-space indent + trailing newline, the
    shape record_audio.sh writes). Tolerant: a missing file, or unparsable / non
    -object JSON, is replaced by a fresh {"title": ...} object rather than raising.
    Returns the dict that was written. Only a failing write raises (OSError)."""
    p = Path(path)
    data = {}
    try:
        loaded = json.loads(p.read_text())
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    data["title"] = "" if new_title is None else str(new_title)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data


def detect_language(base_dir, base):
    """Detected language for a meeting, read from the first sibling transcription
    JSON in base_dir that carries a non-empty top-level 'language'. Tries, in
    order: <base>.json, <base>_trimmed.json, <base>.voice.json, <base>.system.json,
    <base>_speakers_labeled.json. Returns the code (e.g. 'en') or None when none is
    found or readable."""
    d = Path(base_dir)
    for suffix in _LANG_JSON_SUFFIXES:
        try:
            data = json.loads((d / f"{base}{suffix}").read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            lang = data.get("language")
            if lang:
                return str(lang)
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    cmd, rest = argv[0], argv[1:]

    if cmd == "targets":
        for name in configured_targets(os.environ):
            print(name)
        return 0

    if cmd == "confirm":
        # An explicit ANSWER wins (even an empty one -> NO); otherwise read a single
        # line from stdin. EOF / closed stdin -> None -> NO. Exit 0 iff yes.
        if rest:
            answer = rest[0]
        else:
            line = sys.stdin.readline()
            answer = line if line != "" else None
        return 0 if parse_yes_no(answer) else 1

    if cmd == "get-title":
        if not rest:
            print("usage: meeting_ui.py get-title METAFILE", file=sys.stderr)
            return 2
        print(read_metadata_title(rest[0]))
        return 0

    if cmd == "set-title":
        if len(rest) < 2:
            print("usage: meeting_ui.py set-title METAFILE TITLE", file=sys.stderr)
            return 2
        try:
            data = update_metadata_title(rest[0], rest[1])
        except OSError as e:
            print(f"error: could not write metadata: {e}", file=sys.stderr)
            return 1
        print(data.get("title", ""))
        return 0

    if cmd == "language":
        if len(rest) < 2:
            print("usage: meeting_ui.py language BASE_DIR BASE", file=sys.stderr)
            return 2
        lang = detect_language(rest[0], rest[1])
        print(lang if lang else "unknown")
        return 0

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
