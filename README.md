# ShepitNote

**A private, local-first meeting-notes workflow for Linux, built for multilingual engineering calls.**

ShepitNote records a meeting, keeps recoverable source audio, transcribes it, attributes who said what, produces structured notes, and optionally publishes them to Confluence and Slack. It is designed around meetings that mix **Ukrainian, Russian, and English**, including English technical vocabulary inside Cyrillic speech.

The default workflow stays on your machine: faster-whisper handles transcription and Ollama handles summarization. An explicit, opt-in [cloud mode](docs/CLOUD.md) is available when privacy requirements allow trading local processing for speed or stronger models.

> ShepitNote is a fork of **[peteonrails/hushnote](https://github.com/peteonrails/hushnote)** (MIT, © Peter Jackson). It has evolved from a simple recorder/transcriber into a recoverable meeting-notes application for Linux/PipeWire, multilingual engineering teams, speaker review, and controlled publishing.

## What ShepitNote is

ShepitNote is not primarily a general dictation tool or a thin wrapper around Whisper. It is an end-to-end workflow for turning a real call into usable team knowledge:

```text
capture recoverable audio
        ↓
transcribe You and Remote tracks
        ↓
review speaker attribution and terminology
        ↓
generate summary, decisions, and action items
        ↓
confirm and publish to Confluence / Slack
```

The source recording remains available for reprocessing. You can retry a meeting with a different language, Whisper model, summary model, glossary, or speaker labeling without recording it again.

### Best fit

ShepitNote is especially useful when:

- you run Linux with PipeWire or PulseAudio;
- calls mix Ukrainian, Russian, English, and English technical terms;
- you want your own microphone separated reliably from the remote call;
- several remote participants may need diarization and human-readable names;
- notes need review before they are published;
- Confluence and Slack are part of the team workflow;
- local processing and recoverability matter more than a polished desktop UI.

It may be more machinery than you need for simple English-only dictation. For that use case, consider upstream [hushnote](https://github.com/peteonrails/hushnote) or a dedicated push-to-talk project such as [Voxtype](https://github.com/peteonrails/voxtype).

## Why it differs from Hushnote and Voxtype

ShepitNote shares its original pipeline with Hushnote and some speech-processing concerns with Voxtype, but it has a different product boundary.

| | Hushnote | Voxtype | ShepitNote |
|---|---|---|---|
| **Primary job** | Local meeting recording, transcription, and summary | Wayland voice-to-text and dictation, with meeting support | Recoverable meeting notes from capture through reviewed publishing |
| **Capture model** | General meeting audio | Push-to-talk plus chunked meeting capture | Single or synchronized **You / Remote** tracks |
| **Speaker model** | Mixed-track diarization | Source attribution and experimental voice clustering | Track-based You/Remote attribution plus optional remote-only diarization and relabeling |
| **Language focus** | General Whisper auto-detection | Configurable engines and constrained language candidates | Tuned workflow for **uk / ru / en** and English engineering terminology |
| **Output workflow** | Transcript and summary hook | Transcript/export/summarize commands | Review, reprocess, speaker naming, structured notes, Confluence and Slack |
| **Recovery model** | Retained recordings | Meeting mode is evolving | Audio-first storage, status/catchup, and whole-meeting reprocessing |

This is not a claim that ShepitNote should reimplement every capability of those projects. The intended direction is to keep the meeting workflow specialized while making transcription components more replaceable. See **[Project direction](docs/PROJECT_DIRECTION.md)**.

## Current capabilities

- **Dual-track meeting capture** — record your microphone as `You` and call audio as `Remote`, then interleave the tracks by timestamp.
- **Real-time echo cancellation** — WebRTC AEC for open-speaker calls where the remote side would otherwise leak back into your mic.
- **Recoverable recordings** — retain meeting audio and reprocess a complete meeting later.
- **Local transcription** — faster-whisper on CPU by default, with per-meeting model and language selection.
- **Multilingual tuning** — first-class Ukrainian, Russian, and English workflow, hotwords, initial prompts, and per-language Cyrillic-to-Latin glossary rules.
- **Speaker workflow** — optional diarization, guided labels, participant roster support, and relabeling of saved meetings.
- **Structured local summaries** — Ollama produces summaries, discussion notes, decisions, and action items.
- **Controlled publishing** — full notes to Confluence and a concise Slack message, either automatically or through a confirm-gated guided flow.
- **Status and catchup** — identify pending, partial, and completed meetings and resume interrupted processing.
- **Optional cloud processing** — explicitly opt in to cloud transcription and/or summarization for non-sensitive meetings.

## Important current limitation: mixed languages

Whisper language detection is performed once near the beginning of a file, so automatic detection effectively chooses one language for the whole track. In a meeting that switches between Ukrainian, Russian, and English, explicit `-l uk`, `-l ru`, or `-l en` may still be more reliable than `auto`, but no single choice is perfect for every section.

Chunk-level constrained language selection is planned and tracked in [#15](https://github.com/yuriytkach/shepitnote/issues/15). Until it is implemented, choose the dominant meeting language and use hotwords/glossary rules for technical vocabulary. See [docs/LANGUAGE.md](docs/LANGUAGE.md).

## Quick start

```bash
git clone https://github.com/yuriytkach/shepitnote.git
cd shepitnote

# System dependencies (names vary by distro)
sudo apt install ffmpeg pipewire-pulse python3-venv     # Debian / Ubuntu / KDE neon
# Arch / CachyOS: yay -S ffmpeg pipewire-pulse python

# Python environment and transcription dependencies
./setup.sh                       # add --model small to pre-download a Whisper model

# Local summarization
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b          # or another instruction-tuned model

# Guided meeting workflow
./shepitnote meeting
```

Full installation notes, first-run tests, and recommended settings: **[docs/SETUP.md](docs/SETUP.md)**.

## Recommended meeting workflow

For calls, configure dual-track capture and enable AEC when using open speakers:

```bash
./shepitnote aec on
./shepitnote meeting
```

The guided flow records the meeting, processes both tracks, lets you review the title and output, and asks before publishing anything.

To record now and process later:

```bash
./shepitnote record
./shepitnote process-last
```

To reprocess an existing complete meeting:

```bash
./shepitnote process-meeting 20260720_190326
./shepitnote process-meeting 20260720_190326 -l uk -o another-model
```

`process-meeting` reads the retained WAV or MP3 tracks, rebuilds the combined transcript and summary, and does not publish unless `--publish` is supplied.

## Configuration

Copy the annotated example:

```bash
cp .shepitnoterc.example .shepitnoterc
```

`.shepitnoterc` is sourced at startup and ignored by Git. It documents audio sources, dual-track mode, Whisper model/language, Ollama, cloud processing, hotwords and glossary rules, diarization, CPU limits, publishing, and other options.

## Command reference

```text
Commands:
    record              Start recording (stop with Ctrl+C)
    transcribe FILE     Transcribe an audio file
    summarize FILE      Summarize a transcription
    trim FILE           Detect and remove silent tail from an audio file
    diarize FILE        Identify speakers in an audio file
    label FILE          Label speakers interactively
    apply-labels FILE   Apply labels to create final transcript
    relabel ID          Revisit speaker names for an existing meeting
    compress FILE       Compress WAV to MP3
    full                Record, compress, trim, transcribe, and summarize
    meeting             Guided record, review, and confirm-publish flow
    process FILE        Process one existing recording
    process-last        Process the most recent recording
    process-meeting ID  Reprocess a complete meeting from retained tracks
    list                List recordings
    status              Show pending, partial, and completed recordings
    catchup             Resume unfinished recordings and hooks
    aec on|off|status   Control real-time echo cancellation

Common options:
    -d, --duration SEC      Recording duration
    -m, --model MODEL       Whisper model (default: large-v3)
    -l, --language LANG     uk, ru, en, or auto
    --initial-prompt TEXT   Decoding-bias sentence for terminology
    --hotwords TERMS        Space-separated terms to bias transcription
    -o, --ollama MODEL      Ollama model for summarization
    --cloud                 Opt in to configured cloud processing
    --no-cloud              Force local processing for this run
    -f, --format FMT        txt, json, srt, vtt, or md
    -s, --speakers NUM      Expected number of speakers
    -t, --title TITLE       Meeting title
    --diarize               Enable diarization
    --no-diarize            Disable diarization for this run
    --no-trim               Skip silent-tail trimming
    --timeout SECS          Processing timeout
```

Run `./shepitnote help` for the authoritative command list for your checkout.

## Data and processing model

A typical single-track pipeline is:

```text
record WAV
  → compress to MP3
  → trim silent tail
  → transcribe
  → summarize
  → optionally publish
```

In dual mode, microphone and system audio are recorded separately, transcribed independently, and merged by timestamp. Remote-only diarization can subdivide the remote track while preserving `You` as a reliable track identity.

Meeting directories retain the artifacts needed for inspection and reprocessing. See [docs/AUDIO.md](docs/AUDIO.md#output-files) for the exact layout.

## Project principles

- **Audio is the source of truth.** A transcript or summary can be regenerated; a lost recording cannot.
- **Local by default, cloud by explicit choice.** Uploads should never be surprising.
- **Reliable attribution before clever inference.** Separate tracks are preferred over guessing when the audio system can provide them.
- **Human review is part of the workflow.** Names, decisions, and published notes should be correct, not merely automatic.
- **Meeting application, replaceable engines.** Capture, recovery, review, and publishing belong to ShepitNote; transcription and diarization engines should become pluggable where practical.
- **Incremental evolution.** The existing working workflow should be refactored and extended without a high-risk rewrite.

The open architecture and evaluation work is described in [docs/PROJECT_DIRECTION.md](docs/PROJECT_DIRECTION.md).

## Troubleshooting

**No audio captured**

```bash
pactl list sources short
pactl set-default-source YOUR_SOURCE_NAME
./record_audio.sh -d 5
```

**Ukrainian is transcribed as Russian** — automatic detection chooses one language for a full file. Set `-l uk` or `WHISPER_LANGUAGE=uk`. See [docs/LANGUAGE.md](docs/LANGUAGE.md#language-selection-uk--ru--en).

**The You track duplicates Remote** — your open speakers are leaking into the mic. Run `./shepitnote aec on` before the call. See [docs/AUDIO.md](docs/AUDIO.md#echo-cancellation-open-speaker-meetings).

**Ollama is unavailable** — check `systemctl status ollama` and `ollama list`, then select an installed model with `-o`.

**The desktop becomes sluggish** — lower `CPU_THREADS` or increase `PROCESSING_NICE`. See [docs/SETUP.md](docs/SETUP.md#keeping-the-desktop-responsive-cpu-limits).

## Documentation

- **[docs/SETUP.md](docs/SETUP.md)** — installation, first-run test, and recommended settings
- **[docs/AUDIO.md](docs/AUDIO.md)** — capture modes, dual tracks, AEC, routing, and output files
- **[docs/LANGUAGE.md](docs/LANGUAGE.md)** — Whisper models, uk/ru/en behavior, hotwords, and glossary rules
- **[docs/DIARIZATION.md](docs/DIARIZATION.md)** — speaker diarization, labeling, and review
- **[docs/PUBLISHING.md](docs/PUBLISHING.md)** — hooks, Confluence, Slack, and confirm-gated publishing
- **[docs/CLOUD.md](docs/CLOUD.md)** — optional providers, configuration, privacy, and cost
- **[docs/PROJECT_DIRECTION.md](docs/PROJECT_DIRECTION.md)** — product boundary, architectural direction, and roadmap
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — development setup and contribution guidelines

## License and credits

MIT — see [LICENSE](LICENSE).

ShepitNote is derived from **[hushnote](https://github.com/peteonrails/hushnote)** by Peter Jackson ([@peteonrails](https://github.com/peteonrails)); the original copyright is retained. The recording → transcription → summarization pipeline and post-summary hook originated there.

ShepitNote adds and continues to develop dual-track You/Remote capture, WebRTC echo cancellation, multilingual engineering-meeting handling, terminology normalization, speaker review and roster workflows, recoverable whole-meeting reprocessing, Confluence/Slack publishing, and the guided meeting flow.

Built with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Ollama](https://ollama.com), [pyannote.audio](https://github.com/pyannote/pyannote-audio), and [ffmpeg](https://ffmpeg.org).