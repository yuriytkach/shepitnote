# Setup

Get the meeting transcription system running in three steps.

## 1. System dependencies

Install these with your package manager (names vary by distro):

- **ffmpeg** — recording + audio conversion
- **pactl** (`pulseaudio-utils`, or `pipewire-pulse` on PipeWire systems) — audio routing
- **python3** (3.9+) with the `venv` module (`python3-venv` on Debian/Ubuntu)
- **[Ollama](https://ollama.com)** — local LLM for summarization

## 2. Python environment (`./setup.sh`)

The worker scripts run inside a virtual environment (`./venv/`). Create it and
install the Python dependencies (faster-whisper, huggingface-hub, requests) with:

```bash
./setup.sh
```

This is idempotent — re-run it any time. To also pre-download a Whisper model so
your first meeting doesn't pause to fetch it (large-v3 is ~3 GB):

```bash
./setup.sh --model small        # or: base | medium | large-v3
```

> Without a working venv, `shepitnote` now fails fast **before** recording with a
> clear message telling you to run `./setup.sh` — so you never lose a meeting to a
> missing dependency.

## 3. A summarization model in Ollama

Summaries use whatever Ollama model you pass with `-o` (or set `OLLAMA_MODEL` in
`.shepitnoterc`). List what you have with `ollama list`, and pull one if needed,
e.g. `ollama pull llama3.1:8b`. Pick a **local** model — larger instruction-tuned
models (9B+) summarize multilingual transcripts best. Avoid Ollama `*:cloud`
models: they send your transcript off-machine, defeating the local-only design.

## Quick Start

### Test with a 10-second recording:
```bash
# Record 10 seconds, transcribe, and summarize
./shepitnote full -d 10 -m tiny -o qwen2.5-coder:14b
```

### For real meetings:
```bash
# Start recording (press Ctrl+C to stop)
./shepitnote full -o qwen2.5-coder:14b
```

### Guided flow (review + confirm before publishing):
```bash
# Record -> review language/transcript/summary -> edit title -> confirm publish
./shepitnote meeting
```
`shepitnote meeting` runs the whole loop but **never publishes automatically**: it
shows the detected language, transcript and summary, lets you edit the title, and
asks yes/no per configured target (Confluence / Slack) before sending. A blank
answer or EOF means "do not publish". It uses plain line prompts, so it works over
**SSH** and when output is piped. See the README ("Guided flow with review +
confirm-gated publishing") for details.

### Available audio sources:
The script records from your **default** PulseAudio/PipeWire source. List the
sources detected on your machine, then switch the default if needed:

```bash
pactl list short sources          # see available sources (name / ID)
pactl get-default-source          # what's currently default
pactl set-default-source <NAME>   # switch to a specific mic
```

### Dual-track capture (You/Remote)

To capture your voice and the remote side as two separate, synchronized tracks
(so the transcript is labeled by origin without diarization), set
`AUDIO_SOURCE_TYPE=dual`. The two tracks map like this:

- **You** ← the default *source* (your microphone): `pactl get-default-source`
- **Remote** ← the monitor of the default *sink* (what plays through your
  speakers/headset): `pactl get-default-sink` (its `.monitor` is captured)

So point your default source at the mic you speak into and your default sink at
the device the call audio plays out of, then run:

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote full -d 10 -m tiny -o mistral:7b
```

> **Tip: use a headset for the cleanest separation.** On open laptop speakers
> the microphone also picks up the remote audio playing aloud, so your **You**
> track carries a faint echo of the **Remote** side. It's harmless, but Whisper
> may transcribe that echo as extra `[You]` text. A headset (nothing plays out
> loud) keeps the two tracks cleanly separated.

For Bluetooth headsets in HSP/HFP mode, ffmpeg's PulseAudio capture can be
silent; use the PipeWire backend instead:

```bash
AUDIO_SOURCE_TYPE=dual RECORD_BACKEND=pw-record ./shepitnote full
```

## Capturing calls: Zoom, Slack huddles, Bluetooth

Capture is **sink-monitor based**, so it is app-agnostic: the remote side of any
call — Zoom (native app or browser), Slack huddles, Google Meet, Discord — plays
through your **default sink**, and shepitnote records that sink's `.monitor`. You do
not configure anything per app; you configure the *default sink*.

Pick the mode with `AUDIO_SOURCE_TYPE`:

| Mode | What you get | Use when |
|------|--------------|----------|
| `dual` | two tracks: **You** (mic) + **Remote** (sink monitor), labeled by origin | recommended for calls — clean You/Remote notes |
| `both` | one track mixing mic + sink monitor | you just want a single blended recording |
| `monitor` | sink monitor only (the remote side) | you only need what the others said |
| `microphone` (default) | mic only | in-person / dictation, no call audio |

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote meeting -o mistral:7b   # recommended for a call
```

### Route the call audio to the default sink

The monitor track is only non-silent if the call app **plays out through the
default sink**. Before a call, check:

1. `pactl get-default-sink` is the device you actually listen on (speakers/headset).
2. The call app is sending audio to that same device.

**Zoom quirk:** Zoom has its *own* speaker selection (Settings → Audio → Speaker),
independent of the system default. If Zoom is set to a different output device, the
default sink's monitor is **silent** even though you hear the call. Fix: set Zoom's
Speaker to *Same as System* (or to whatever your default sink is). **Slack huddles**
and browser-based Meet follow the system default, so they need no special step.

### Bluetooth headsets (A2DP vs HSP/HFP)

A Bluetooth headset runs in one of two profiles:

- **A2DP** — high quality, **output only** (no mic). Great for listening, but the
  headset mic is unavailable.
- **HSP/HFP** — bidirectional (mic + speaker) at lower quality; this is the profile
  that is active during a call so your mic works.

In **HSP/HFP**, `ffmpeg -f pulse` sometimes captures **silence** from the sink
monitor. If that happens, switch the recorder backend to PipeWire's `pw-record`:

```bash
AUDIO_SOURCE_TYPE=dual RECORD_BACKEND=pw-record ./shepitnote meeting
```

Set `RECORD_BACKEND=pw-record` in `.shepitnoterc` if you always record over a BT headset.

### Verify your routing on a real call (do this once)

Join a test call (Zoom has a built-in test meeting; or a Slack huddle with a
colleague) and, **while the other side is talking**, record a short sample:

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote full -d 15 -m tiny -o mistral:7b
```

Then, in the newest `recordings/<date>/meeting_*/` directory, confirm:

- both `*.voice.wav` (your mic) and `*.system.wav` (the remote side) exist and are
  ~15s: `ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 <file>`;
- `*.system.wav` actually contains the **remote** voice (play it back);
- the merged `*.txt` interleaves `[You]` and `[Remote]` lines.

If `*.system.wav` is silent, the call app is not on the default sink (see the Zoom
quirk) or you are on a BT headset in HSP/HFP (use `pw-record`). A `both`/`monitor`
recording that is silent has the same two causes.

## Recommended Settings

For best results:
```bash
# Good balance (fast, decent quality)
./shepitnote full -m base -o mistral:7b

# Better quality (slower)
./shepitnote full -m small -o qwen2.5-coder:14b

# Best quality (much slower)
./shepitnote full -m medium -o mixtral:8x7b
```

## Language & accuracy (uk/ru/en)

`large-v3` is now the default Whisper model — best multilingual accuracy, but
slower on CPU. For known-language meetings, set the language explicitly instead
of relying on auto-detect (which samples only the first ~30s and often mislabels
Ukrainian as Russian):

```bash
./shepitnote full -l uk     # or -l ru / -l en; -l auto to auto-detect
```

Set a permanent default with `WHISPER_LANGUAGE=uk` in `.shepitnoterc`. See the
[Language selection](README.md#language-selection-ukrainian--russian--english)
section in the README for the full guidance — including a user verification step
for measuring accuracy on your own recordings, which needs your own audio and
can't be done for you.

### English tech terms (Kubernetes, deploy, ...)

For meetings that mix Slavic speech with English programming terms, two opt-in
layers improve accuracy (both empty by default — leaving them unset changes
nothing):

- **Hotwords / initial prompt** bias Whisper toward clean English spellings.
  Set `WHISPER_HOTWORDS="Kubernetes deploy Helm chart Jenkins GitHub"` (or the
  sentence-form `WHISPER_INITIAL_PROMPT`, which takes precedence) in
  `.shepitnoterc`.
- **A per-language glossary** normalizes phonetic Cyrillic renderings before the
  summary. Copy a template to activate it, e.g.
  `cp glossary.uk.txt.example glossary.uk.txt`, then edit it for your stack
  (`GLOSSARY_DIR` points at where these files live; default is the shepitnote
  directory). Real `glossary.*.txt` files are git-ignored.

Full format, language-resolution behavior, and a with/without verification
procedure are in the README
[English tech-term accuracy](README.md#english-tech-term-accuracy-hotwords--glossary)
section.

## Common Commands

```bash
# List recordings
./shepitnote list

# Record only (30 minutes)
./shepitnote record -d 1800

# Transcribe existing audio
./shepitnote transcribe path/to/audio.wav -m small

# Summarize existing transcription
./shepitnote summarize path/to/transcript.txt -o qwen2.5-coder:14b

# Guided flow: record, review, confirm-gated publish (SSH-friendly)
./shepitnote meeting
```

## Troubleshooting

If you get "llama3.1:8b not found", either:
1. Use `-o` to specify a model you have (see list above)
2. Or download it: `ollama pull llama3.1:8b`

## Next Steps

Try a test recording to make sure everything works!

```bash
./shepitnote full -d 10 -m tiny -o mistral:7b
```

This will:
1. Record 10 seconds of audio
2. Transcribe it using the tiny Whisper model
3. Generate a summary using Mistral 7B

Check the `recordings/` directory for the output files.

## Publishing summaries to Confluence

To auto-publish each summary to a Confluence space, point `POST_SUMMARY_HOOK` at the
bundled `hooks/confluence_publish.py` and set the `CONFLUENCE_*` variables in
`.shepitnoterc`. Preview the output first, without any credentials:

```bash
hooks/confluence_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```

See the [Confluence publishing](README.md#confluence-publishing) section of the README for
the full setup (getting an API token, the page-title/idempotency behavior). For a per-meeting
**confirm before publishing** instead of the automatic hook, use `./shepitnote meeting`, which
asks yes/no per target and never publishes on its own.

## Publishing summaries to Slack

To post a short TL;DR of each summary to Slack, point `POST_SUMMARY_HOOK` at the bundled
`hooks/slack_publish.py` and set either `SLACK_WEBHOOK_URL` (incoming webhook) or
`SLACK_BOT_TOKEN` + `SLACK_CHANNEL` (bot token) in `.shepitnoterc`. Preview first — no token
needed (it still calls the local Ollama to build the TL;DR):

```bash
hooks/slack_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```

To publish to **both** Confluence and Slack from the single hook slot, point
`POST_SUMMARY_HOOK` at the dispatcher `hooks/publish.py` instead; it runs each publisher you
have configured. See the [Slack publishing](README.md#slack-publishing) and
[Publishing to both](README.md#publishing-to-both) sections of the README for the full setup
(webhook vs bot token, the `.slack_done` de-dup marker, the Confluence-link-when-available
behavior). For a per-meeting **confirm before publishing** instead of the automatic hook, use
`./shepitnote meeting`, which asks yes/no per target and never publishes on its own.
