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

> Without a working venv, `shepitnote` fails fast **before** recording with a
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
./shepitnote full -d 10 -m tiny -o llama3.1:8b
```

### For real meetings:
```bash
# Start recording (press Ctrl+C to stop)
./shepitnote full -o llama3.1:8b
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
**SSH** and when output is piped. See
[PUBLISHING.md](PUBLISHING.md#guided-flow-review-then-confirm-gated-publishing)
for details.

### Available audio sources:
The script records from your **default** PulseAudio/PipeWire source. List the
sources detected on your machine, then switch the default if needed:

```bash
pactl list short sources          # see available sources (name / ID)
pactl get-default-source          # what's currently default
pactl set-default-source <NAME>   # switch to a specific mic
```

## Recording calls (dual-track, echo cancellation, routing)

For call recording — dual-track You/Remote capture, real-time echo cancellation
on open speakers, routing Zoom/Slack/Meet audio, Bluetooth quirks, and how to
verify your routing once — see **[AUDIO.md](AUDIO.md)**. The short version:

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote meeting     # two labeled tracks (You / Remote)
./shepitnote aec on                             # cancel speaker echo (headset-free); aec off to restore
```

## Recommended Settings

For best results:
```bash
# Good balance (fast, decent quality)
./shepitnote full -m base -o llama3.1:8b

# Better quality (slower)
./shepitnote full -m small -o qwen2.5-coder:14b

# Best quality (much slower)
./shepitnote full -m medium -o mixtral:8x7b
```

## Keeping the desktop responsive (CPU limits)

Post-meeting processing — faster-whisper transcription, pyannote diarization, and
Ollama summarization — is CPU-heavy on a machine without a usable GPU. Left
unbounded it can grab every core and make the system feel frozen. Two settings in
`.shepitnoterc` keep it in check (both applied automatically):

| Setting | Default | Effect |
|---------|---------|--------|
| `CPU_THREADS` | half the logical CPUs | Caps the worker thread pools (faster-whisper, pyannote, Ollama) so cores stay free for other apps. `0` = uncapped. |
| `PROCESSING_NICE` | `10` | Runs the CPU-heavy workers under `nice`, so interactive apps (browser, editor) always preempt them. `0` = disabled. |

The defaults favour a responsive desktop over raw speed — processing just takes a
bit longer. Recording itself is never throttled.

```bash
# Gentler: leave lots of cores free and run at lowest priority
CPU_THREADS=8 PROCESSING_NICE=19 ./shepitnote full

# Faster: use all cores at normal priority (e.g. when you're away from the machine)
CPU_THREADS=0 PROCESSING_NICE=0 ./shepitnote full
```

If memory (not CPU) is the pinch — `large-v3` + pyannote + a large Ollama model all
resident — set `UNLOAD_OLLAMA=1` to free the LLM before transcription.

## Language & accuracy (uk/ru/en)

`large-v3` is the default Whisper model — best multilingual accuracy, but slower
on CPU. For known-language meetings, set the language explicitly instead of
relying on auto-detect (which samples only the first ~30s and often mislabels
Ukrainian as Russian):

```bash
./shepitnote full -l uk     # or -l ru / -l en; -l auto to auto-detect
```

Set a permanent default with `WHISPER_LANGUAGE=uk` in `.shepitnoterc`. For the
full guidance — the model table, the uk/ru/en verification step, and English
tech-term accuracy (hotwords + glossary) — see **[LANGUAGE.md](LANGUAGE.md)**.

## Common Commands

```bash
# List recordings
./shepitnote list

# Record only (30 minutes)
./shepitnote record -d 1800

# Transcribe existing audio
./shepitnote transcribe path/to/audio.wav -m small

# Summarize existing transcription
./shepitnote summarize path/to/transcript.txt -o llama3.1:8b

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
./shepitnote full -d 10 -m tiny -o llama3.1:8b
```

This will:
1. Record 10 seconds of audio
2. Transcribe it using the tiny Whisper model
3. Generate a summary with your chosen Ollama model

Check the `recordings/` directory for the output files.

## Publishing summaries

To auto-publish each summary to a Confluence space and/or a short TL;DR to Slack —
or to review and confirm each target before anything is sent — see
**[PUBLISHING.md](PUBLISHING.md)**. You can preview either publisher without any
credentials:

```bash
hooks/confluence_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
hooks/slack_publish.py      recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```
