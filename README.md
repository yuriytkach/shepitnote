# ShepitNote

**Private, local, multilingual meeting notes for Linux — record, transcribe, label who said what, summarize, and publish, all on your own machine.**

ShepitNote records a meeting, transcribes it with faster-whisper, labels who said what, and summarizes it with a local LLM (Ollama) — then, at your choice, publishes the full notes to Confluence and a short TL;DR to Slack. Everything runs locally: no cloud services, nothing leaves your machine. The name is from Ukrainian *шепіт* ("whisper") — a nod to the quiet, local ethos and to the Whisper model under the hood.

It's built for meetings that mix **Ukrainian, Russian, and English** (with English tech terms), adding dual-track *You/Remote* capture, real-time echo cancellation for open-speaker calls, per-meeting language selection, tech-term accuracy tuning, and a guided review-then-confirm publishing flow on top of the original pipeline.

> A fork of **[peteonrails/hushnote](https://github.com/peteonrails/hushnote)** (MIT, © Peter Jackson), extended for Linux/PipeWire, multilingual meetings, and Confluence/Slack publishing. See [Credits](#credits).

## How ShepitNote differs from hushnote

Upstream **[hushnote](https://github.com/peteonrails/hushnote)** is an excellent general-purpose, privacy-first meeting recorder → transcriber → summarizer for Linux. ShepitNote keeps all of that and specializes it for one audience: **multilingual (Ukrainian / Russian / English) engineering teams** who want clean, attributed notes pushed into the tools they already live in — with nothing leaving the machine unless they say so.

**What this fork adds on top of hushnote:**

- **🎧 Dual-track You/Remote capture** — records your mic and the call audio as two synchronized tracks and labels every line by its origin (You vs. Remote), so your own voice is always cleanly separated — no diarization guessing. Several people on the far side share one `Remote` label by default; flip on opt-in remote-track diarization to split them into `Remote 1`/`Remote 2`/… while `You` stays untouched. → [docs/AUDIO.md](docs/AUDIO.md#dual-track-youremote-recording)
- **🔊 Real-time echo cancellation** — a one-command WebRTC toggle (`aec on`/`off`) so meetings on open laptop speakers (no headset) don't record the remote side back through your mic. → [docs/AUDIO.md](docs/AUDIO.md#echo-cancellation-open-speaker-meetings)
- **🌐 First-class uk / ru / en** — explicit per-meeting language choice that fixes Ukrainian being mislabeled as Russian, `large-v3` by default, plus English tech-term accuracy via hotwords + a per-language glossary. → [docs/LANGUAGE.md](docs/LANGUAGE.md)
- **📤 Confluence + Slack publishing** — full notes to a Confluence page (created/updated idempotently) and a short TL;DR to Slack, with a dispatcher to do both. → [docs/PUBLISHING.md](docs/PUBLISHING.md)
- **✅ Guided, confirm-gated flow** — `shepitnote meeting` walks record → review → edit title → confirm each publish target; nothing is sent without an explicit yes, and it works over SSH. → [docs/PUBLISHING.md](docs/PUBLISHING.md#guided-flow-review-then-confirm-gated-publishing)

| | hushnote (upstream) | ShepitNote (this fork) |
|---|---|---|
| **Language** | auto-detect, one language per file | first-class **uk / ru / en**, explicit per-meeting choice, `large-v3` default, English tech-term accuracy |
| **Who said what** | one mixed track (diarization guesses) | **dual-track You/Remote**, labeled by track of origin |
| **Open-speaker calls** | mic records the remote echo | **real-time WebRTC echo cancellation** (`aec on`/`off`) |
| **Publishing** | one generic post-summary hook | first-class **Confluence** + **Slack** publishers, and a dispatcher |
| **Control** | the hook fires automatically | a guided **review → per-target confirm** flow |
| **Privacy** | 100% local | 100% local (unchanged) |

Rule of thumb: if your meetings are English-only and you just want a local transcript + summary, upstream hushnote is a great fit. If they mix Ukrainian/Russian with English tech vocabulary and you publish notes to Confluence and Slack, that's exactly what ShepitNote is tuned for.

## Features

- **🎙️ Flexible capture** — system audio, mic, both mixed, or two synchronized You/Remote tracks via PulseAudio/PipeWire
- **🔊 Echo cancellation** — real-time WebRTC canceller for headset-free, open-speaker calls
- **📝 Offline transcription** — faster-whisper; CPU by default, NVIDIA GPU when available; per-meeting or auto language
- **🔤 Tech-term accuracy** — hotwords/initial-prompt bias + a per-language Cyrillic→Latin glossary applied before summarization
- **✂️ Silent-tail trimming** — binary-search detection removes silent tails fast, regardless of file length
- **👥 Speaker diarization** — optional "who spoke when" with interactive labeling
- **🤖 Local summarization** — structured notes via Ollama: summary, discussion, decisions, action items
- **📤 Publishing** — Confluence (full notes) + Slack (TL;DR), automatic or confirm-gated
- **📋 Status & catchup** — see what's pending / partial / done; reprocess anything missed
- **🔒 100% private** — all processing is local; no internet required after setup

## Quick start

```bash
git clone https://github.com/yuriytkach/shepitnote.git
cd shepitnote

# 1. System dependencies (names vary by distro)
sudo apt install ffmpeg pipewire-pulse python3-venv     # Debian / Ubuntu / KDE neon
# Arch / CachyOS:  yay -S ffmpeg pipewire-pulse python

# 2. Python environment (creates ./venv and installs faster-whisper etc.)
./setup.sh                       # add --model small to pre-download a Whisper model

# 3. A local summarization model in Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b          # or any local instruction-tuned model

# Record a meeting (Ctrl+C to stop) → transcribe → summarize
./shepitnote full
```

Full install notes, first-run test, and recommended settings: **[docs/SETUP.md](docs/SETUP.md)**.

## Configuration

Copy the annotated example and edit to taste:

```bash
cp .shepitnoterc.example .shepitnoterc
```

`.shepitnoterc` is sourced at startup and git-ignored. It documents every option — audio backend, Whisper model/language, Ollama model, tech-term hotwords/glossary, silent-tail thresholds, CPU limits (`CPU_THREADS` / `PROCESSING_NICE`, so processing doesn't hog the machine — see [Troubleshooting](#troubleshooting)), the post-summary hook, and the Confluence/Slack blocks.

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
    meeting             Guided flow: record, review, edit title, confirm-publish
    process FILE        Process an existing recording (compress, trim, transcribe, summarize)
    process-last        Process the most recent recording
    list                List all recordings
    status              Show status of all recordings
    catchup             Process any unfinished recordings and run post-summary hook
    aec on|off|status   Toggle real-time echo cancellation (open-speaker calls)

Options:
    -d, --duration SEC      Recording duration (default: manual stop with Ctrl+C)
    -m, --model MODEL       Whisper model (tiny|base|small|medium|large-v3) (default: large-v3)
    -l, --language LANG     Language code, e.g. uk, ru, en, or auto (default: auto-detect)
    --initial-prompt TEXT   Decoding-bias sentence for tech-term spelling (overrides --hotwords)
    --hotwords TERMS        Space-separated tech terms to bias transcription spelling
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
./shepitnote full           # record → compress → trim → transcribe → summarize
./shepitnote meeting        # guided: record → review → confirm-gated publish
./shepitnote record         # record ONLY — no transcription (Ctrl+C to stop; -d SEC for fixed length)
./shepitnote process-last   # …then transcribe + summarize the most recent recording
./shepitnote status         # what's pending / partial / done
./shepitnote catchup        # process anything interrupted or missed
./shepitnote process recordings/<date>/meeting_*/meeting_*.wav   # process a specific file
```

Record now, process later: `record` captures audio and stops without doing any
CPU-heavy work, so you can run the transcription/summarization afterwards with
`process-last` (newest), `process <file>` (a specific one), or `catchup` (all
pending at once). Each processing step now prints a `Step N/total` header and how
long it took, plus a total when the run finishes.

## Highlights

A short intro to each headline capability — follow the link for the full guide.

### Dual-track You/Remote + echo cancellation
For calls, set `AUDIO_SOURCE_TYPE=dual` to record your mic (**You**) and the call audio (**Remote**) as two synchronized tracks, interleaved into one `[You]`/`[Remote]` transcript — no diarization guessing. Attribution is **You vs. Remote** by track of origin, so your voice is never mixed up with the call. Several people on the far side share a single `[Remote]` label by default; set `DUAL_REMOTE_DIARIZATION=true` to diarize the remote track only and split them into `[Remote 1]`/`[Remote 2]`/… (`[You]` is never diarized). On open speakers without a headset, run `./shepitnote aec on` first so your mic doesn't record the remote side back as an echo (`aec off` restores everything). → **[docs/AUDIO.md](docs/AUDIO.md)**

### Multilingual (uk / ru / en) + tech terms
Set the language per meeting (`-l uk|ru|en`) to avoid Ukrainian being transcribed as Russian, and bias English tech terms with hotwords + a per-language glossary applied before summarization. → **[docs/LANGUAGE.md](docs/LANGUAGE.md)**

### Publishing to Confluence & Slack
Point `POST_SUMMARY_HOOK` at the bundled publishers for automatic publishing, or use `./shepitnote meeting` to review and confirm each target before anything is sent. Confluence pages are updated idempotently; Slack posts a short TL;DR with a link to the notes. → **[docs/PUBLISHING.md](docs/PUBLISHING.md)**

### Speaker diarization
Optional "who spoke when" with interactive labeling, for multi-person recordings captured on a single track. → **[docs/DIARIZATION.md](docs/DIARIZATION.md)**

## Pipeline

```
record → WAV
       → compress to MP3, delete WAV
       → trim silent tail → meeting_trimmed.mp3
       → transcribe → meeting.txt
       → summarize → meeting_summary.md
       → run POST_SUMMARY_HOOK (if set)
```

In `dual` mode, trimming is skipped and the two tracks are transcribed and interleaved by timestamp. See [docs/AUDIO.md](docs/AUDIO.md#output-files) for the file layout of each mode.

## Troubleshooting

**No audio captured** — check your default source and test with a short clip:
```bash
pactl list sources short
pactl set-default-source YOUR_SOURCE_NAME
./record_audio.sh -d 5
```

**Ukrainian transcribed as Russian** — auto-detect samples only the first ~30s and picks one language for the whole file. Set it explicitly with `-l uk` or `WHISPER_LANGUAGE=uk`. See [docs/LANGUAGE.md](docs/LANGUAGE.md#language-selection-uk--ru--en).

**The You track is a duplicate of Remote** — you're on open speakers and the mic is recording the remote audio. Run `./shepitnote aec on` before the call. See [docs/AUDIO.md](docs/AUDIO.md#echo-cancellation-open-speaker-meetings).

**Ollama not responding** — `systemctl status ollama`, `ollama list`, and pass a model you have with `-o`.

**System sluggish while a meeting processes** — transcription, diarization, and summarization run on the CPU. By default they're capped to half your cores (`CPU_THREADS`) and run at low priority (`PROCESSING_NICE`) so the desktop stays responsive; lower `CPU_THREADS` / raise `PROCESSING_NICE` to free up more. See [docs/SETUP.md](docs/SETUP.md#keeping-the-desktop-responsive-cpu-limits).

More fixes live in [docs/SETUP.md](docs/SETUP.md#troubleshooting) and each topic guide below.

## Documentation

- **[docs/SETUP.md](docs/SETUP.md)** — install, first-run test, recommended settings
- **[docs/AUDIO.md](docs/AUDIO.md)** — capture modes, dual-track, echo cancellation, call routing, output files
- **[docs/LANGUAGE.md](docs/LANGUAGE.md)** — Whisper models, uk/ru/en selection, tech-term accuracy
- **[docs/PUBLISHING.md](docs/PUBLISHING.md)** — post-summary hook, Confluence, Slack, the guided flow
- **[docs/DIARIZATION.md](docs/DIARIZATION.md)** — speaker diarization guide
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — development setup and guidelines

## License

MIT — see the [LICENSE](LICENSE) file. The original copyright (© 2025 Peter Jackson) is retained as required by the license.

## Credits

ShepitNote is a fork of **[hushnote](https://github.com/peteonrails/hushnote)** by Peter Jackson ([@peteonrails](https://github.com/peteonrails)), used under the MIT License. The original recording → transcription → summarization pipeline and the post-summary hook design come from that project; this fork adds dual-track You/Remote capture, real-time echo cancellation, uk/ru/en language handling, tech-term accuracy (hotwords + glossary), Confluence/Slack publishing with a dispatcher, and the guided `shepitnote meeting` flow.

Built on top of [faster-whisper](https://github.com/guillaumekln/faster-whisper), [Ollama](https://ollama.ai), [pyannote.audio](https://github.com/pyannote/pyannote-audio), and [ffmpeg](https://ffmpeg.org).
