# HushNote

**Privacy-first meeting transcription and voice-to-text tool for Linux**

HushNote is a local-only, offline-capable voice transcription and meeting summarization tool. All processing happens on your machine using local AI models — no cloud services, no data sharing, complete privacy.

## Features

- **🎙️ Audio Recording**: Capture system audio, microphone, both mixed, or two synchronized You/Remote tracks (dual mode) via PulseAudio/PipeWire
- **📝 Speech-to-Text Transcription**: Convert audio to text using faster-whisper (offline, GPU-accelerated, auto language detection)
- **✂️ Silent Tail Trimming**: Automatically detects and removes silent tails from recordings (e.g. when you forget to stop recording) using binary search — fast regardless of file length
- **👥 Speaker Diarization**: Identify who spoke when with interactive speaker labeling
- **🤖 AI Summarization**: Generate structured meeting notes using Ollama — summary, discussion points, decisions, and action items (only when genuinely present)
- **📋 Status & Catchup**: See which recordings are pending, partially processed, or complete; automatically process any that got missed
- **🔗 Post-Summary Hook**: Run any script after summarization completes — upload to Outline, Notion, a webhook, or anything else
- **🔒 100% Private**: All processing happens locally — no internet required after setup
- **⚡ GPU Acceleration**: AMD ROCm and NVIDIA CUDA supported, with automatic CPU fallback

## Installation

### System Requirements

- Linux (tested on CachyOS/Arch)
- Python 3.10+
- ffmpeg
- PulseAudio or PipeWire
- Ollama (for summarization)
- Optional: GPU with ROCm or CUDA

### Quick Install

```bash
git clone https://github.com/peteonrails/hushnote.git
cd hushnote

# Create a virtual environment
python -m venv venv

# Install core dependencies
./venv/bin/pip install -e .

# Install with speaker diarization support
./venv/bin/pip install -e '.[diarize]'

# For GPU-accelerated PyTorch (CUDA):
./venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu121

# Install and start Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b

# Test installation
./hushnote --help
```

**Arch/CachyOS system dependencies:**
```bash
yay -S ffmpeg pipewire-pulse python   # PipeWire
# or
yay -S ffmpeg pulseaudio-utils python  # PulseAudio
```

## Configuration

Copy `.hushnoterc.example` to `.hushnoterc` and edit to your needs:

```bash
cp .hushnoterc.example .hushnoterc
```

`.hushnoterc` is sourced at startup and ignored by git. The example file documents every available option with defaults and comments, including audio backend, Whisper model, Ollama model, silent tail trimming thresholds, and the post-summary hook.

### Whisper Models

| Model | Size | Speed | Use Case |
|-------|------|-------|----------|
| `tiny` | 75 MB | ~10-20x realtime | Testing |
| `base` | 150 MB | ~5-10x realtime | Balanced |
| `small` | 500 MB | ~2-5x realtime | Better accuracy |
| `medium` | 1.5 GB | ~1-2x realtime | Professional |
| `large-v3` | 3 GB | ~0.5-1x realtime | Maximum accuracy (default) |

Models download automatically on first use. `large-v3` is the default because
multilingual (Ukrainian/Russian/English) accuracy matters more here than speed;
this project targets an AMD APU with no usable CUDA, so it runs on CPU at
roughly real-time (~0.5-1x), materially slower than `base`. Override per run
with `-m base` / `-m small` or set `WHISPER_MODEL=base` when speed matters.

Language is auto-detected by default — but for Ukrainian/Russian/English
meetings you usually want to set it explicitly; see
[Language selection](#language-selection-ukrainian--russian--english) below.

### Language selection (Ukrainian / Russian / English)

faster-whisper's auto-detect samples only the **first ~30 seconds** of a file
and picks **one language for the whole recording** — there is no mid-file
switching, so code-switching is forced through that single chosen model. In
practice **Ukrainian is frequently mislabeled as Russian** (the two are close),
and when that happens the entire meeting is transcribed as Russian.

For a known-language meeting, set the language explicitly rather than relying on
auto-detect:

```bash
./hushnote full -l uk     # force Ukrainian
./hushnote full -l ru     # force Russian
./hushnote full -l en     # force English
./hushnote full -l auto   # auto-detect (same as leaving it unset)
```

Set a permanent default in `.hushnoterc`:

```bash
WHISPER_LANGUAGE=uk       # or ru / en / auto (auto or empty = auto-detect)
```

`auto` (any case) and an empty value both mean auto-detect. Any other
faster-whisper language code works too (`nl`, `de`, `fr`, ...); `uk`, `ru`,
`en`, and `auto` are simply the recommended set for this project.

`large-v3` (the default model) reduces uk/ru confusion and improves accented
English, but does **not** eliminate mislabeling — for a meeting you know is in
one language, an explicit `-l` is still the reliable choice.

#### Measuring accuracy on your own recordings (user verification step)

The uk/ru/en guidance above is **qualitative**. Whisper accuracy depends on your
microphone, accents, and how much the speakers code-switch, so the right default
for you can only be found on **your own audio** — it cannot be measured for you
or in CI. To pick your defaults, take 2-3 representative clips of your meetings
and compare, for each:

```bash
./hushnote transcribe clip.wav -l auto   # what auto-detect produces
./hushnote transcribe clip.wav -l uk     # explicit language (uk/ru/en)
```

Check both transcripts against what was actually said. If `-l auto` sometimes
labels Ukrainian audio as Russian while `-l uk` reads correctly, set
`WHISPER_LANGUAGE=uk` as your default. Repeat with a Russian and an English clip
to confirm the explicit codes behave for each.

## Usage

```
Commands:
    record              Start recording (stop with Ctrl+C)
    transcribe FILE     Transcribe an audio file
    summarize FILE      Summarize a transcription
    trim FILE           Detect and remove silent tail from an audio file
    diarize FILE        Identify speakers in an audio file
    label FILE          Label speakers interactively
    apply-labels FILE   Apply labels to create final transcript
    compress FILE       Compress WAV to MP3
    full                Complete workflow: record, compress, trim, transcribe, summarize
    process FILE        Process an existing recording (compress, trim, transcribe, summarize)
    process-last        Process the most recent recording
    list                List all recordings
    status              Show status of all recordings
    catchup             Process any unfinished recordings and run post-summary hook

Options:
    -d, --duration SEC      Recording duration (default: manual stop with Ctrl+C)
    -m, --model MODEL       Whisper model (tiny|base|small|medium|large-v3) (default: large-v3)
    -l, --language LANG     Language code, e.g. uk, ru, en, or auto (default: auto-detect)
    -o, --ollama MODEL      Ollama model for summarization
    -f, --format FMT        Output format (txt|json|srt|vtt|md)
    -s, --speakers NUM      Number of speakers (for diarization)
    -t, --title TITLE       Meeting title (prompted if not provided)
    --diarize               Enable speaker diarization in full workflow
    --no-trim               Skip silent tail trimming
    --keep-untrimmed        Keep full MP3 alongside trimmed version (default: delete)
    --keep-trimmed          Keep trimmed MP3 after transcription (default: keep)
    --timeout SECS          Kill processing after SECS seconds (default: 7200)
```

### Common workflows

```bash
# Record a meeting, stop with Ctrl+C — automatically compresses, trims, transcribes, summarizes
./hushnote full

# Check status of all recordings
./hushnote status

# Process any recordings that were interrupted or missed
./hushnote catchup

# Process a recording you already have
./hushnote process recordings/meeting.wav

# Trim a recording manually (remove silent tail)
./hushnote trim recordings/meeting.mp3
```

### Dual-track (You/Remote) recording

For calls where you want reliable "who said what" without diarization, set
`AUDIO_SOURCE_TYPE=dual`. HushNote records two time-synchronized tracks from a
single command — your microphone (You) and the system sink monitor (Remote):

```bash
AUDIO_SOURCE_TYPE=dual ./hushnote full
```

This produces `meeting_TS.voice.wav` (You) and `meeting_TS.system.wav` (Remote).
Each track is transcribed separately, every segment is tagged by its track of
origin, and the two are interleaved by timestamp into one transcript with
`[You]` / `[Remote]` labels — no diarization guessing over a blended track.

Notes:

- Local vs remote is decided by track of origin, so labeling is reliable even
  when both sides overlap. pyannote diarization is **reserved** only for the
  optional future case of splitting multiple remote speakers on the system
  track (deferred — dual mode ships with a single `Remote` label).
- Silent-tail trimming is **skipped** in dual mode, because per-track trimming
  would desync turn ordering.
- Dual honors `RECORD_BACKEND`; use `RECORD_BACKEND=pw-record` for Bluetooth
  HSP/HFP headsets.
- The existing mixed `AUDIO_SOURCE_TYPE=both` mode (one blended WAV) remains
  available as a fallback.

See [DIARIZATION.md](DIARIZATION.md) for the full speaker diarization guide.

## Pipeline

The full recording workflow:

```
record → WAV
       → compress to MP3, delete WAV
       → trim silent tail → meeting_trimmed.mp3
       → transcribe trimmed MP3 → meeting.txt
       → summarize → meeting_summary.md
       → run POST_SUMMARY_HOOK (if set)
       → delete untrimmed MP3 (keep with --keep-untrimmed)
```

## Output

Recordings are organized by date and meeting:

```
~/meeting-notes/
└── 20260310/
    └── meeting_20260310_090012/
        ├── meeting_20260310_090012.mp3           # trimmed audio (kept by default)
        ├── meeting_20260310_090012.txt           # transcription
        ├── meeting_20260310_090012_summary.md    # meeting summary
        ├── meeting_20260310_090012_metadata.json # title, timestamp
        └── meeting_20260310_090012.hook_done     # written after hook runs
```

For **dual** meetings (`AUDIO_SOURCE_TYPE=dual`) the single audio file is
replaced by a voice/system pair (trimming is skipped, so both are compressed as
they were recorded):

```
    meeting_20260310_090012/
    ├── meeting_20260310_090012.voice.mp3          # your mic track (You)
    ├── meeting_20260310_090012.system.mp3         # system audio track (Remote)
    ├── meeting_20260310_090012_speakers_labeled.json  # merged, You/Remote tagged
    ├── meeting_20260310_090012.txt                # transcript with [You]/[Remote]
    ├── meeting_20260310_090012_summary.md         # meeting summary
    └── meeting_20260310_090012_metadata.json      # title, timestamp, mode: dual
```

## Post-Summary Hook

Set `POST_SUMMARY_HOOK` in `.hushnoterc` to run a script after every summary is created. The script receives the summary file path as `$1`. On success, hushnote writes a `.hook_done` marker so `catchup` knows not to re-run it.

```bash
# In .hushnoterc:
POST_SUMMARY_HOOK="${HOME}/.local/bin/my-upload-script"
```

Use this to upload to Outline, Notion, a webhook, or any other destination. See `.hushnoterc.example` for details.

## Troubleshooting

**No audio captured:**
```bash
pactl list sources short
pactl set-default-source YOUR_SOURCE_NAME
./record_audio.sh -d 5   # test with a 5-second recording
```

**Wrong language detected:** faster-whisper samples only the first 30 seconds and picks one language for the whole file. If your meeting starts with silence or a different language — or if Ukrainian audio comes out transcribed as Russian (a common mislabel) — set the language explicitly with `-l uk|ru|en` or `WHISPER_LANGUAGE` in `.hushnoterc`. See [Language selection](#language-selection-ukrainian--russian--english) for details.

**Ollama not responding:**
```bash
systemctl status ollama
ollama list
```

**GPU out of memory:** HushNote automatically falls back to CPU if CUDA OOM occurs during model load or transcription.

**Recording has a long silent tail:** Run `hushnote trim FILE` to detect and remove it. The binary search scans ~10 windows to find the content boundary regardless of file length.

## License

MIT. See LICENSE file.

## Credits

Built on top of [faster-whisper](https://github.com/guillaumekln/faster-whisper), [Ollama](https://ollama.ai), [pyannote.audio](https://github.com/pyannote/pyannote-audio), and [ffmpeg](https://ffmpeg.org).
