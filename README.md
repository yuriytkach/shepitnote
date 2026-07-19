# ShepitNote

**Private, local, multilingual meeting notes for Linux — transcribe, label speakers, summarize, and publish, all on your own machine.**

ShepitNote records a meeting, transcribes it with faster-whisper, labels who said what, and summarizes it with a local LLM (Ollama) — then, at your choice, publishes the full notes to Confluence and a short TL;DR to Slack. Everything runs locally: no cloud services, no data sharing, complete privacy. The name is from Ukrainian *шепіт* ("whisper") — a nod to the quiet, local ethos and to the Whisper model under the hood.

It's built for meetings that mix **Ukrainian, Russian, and English** (with English tech terms), adding dual-track *You/Remote* capture, per-meeting language selection, tech-term accuracy tuning, and a guided review-then-confirm publishing flow on top of the original pipeline.

> A fork of **[peteonrails/hushnote](https://github.com/peteonrails/hushnote)** (MIT, © Peter Jackson), extended for Linux/PipeWire, multilingual meetings, and Confluence/Slack publishing. See [Credits](#credits).

## Features

- **🎙️ Audio Recording**: Capture system audio, microphone, both mixed, or two synchronized You/Remote tracks (dual mode) via PulseAudio/PipeWire
- **📝 Speech-to-Text Transcription**: Convert audio to text using faster-whisper (offline; CPU by default, NVIDIA GPU when available; per-meeting or auto language detection)
- **🔤 Tech-term Accuracy**: Bias decoding with hotwords / an initial prompt and normalize phonetic Cyrillic renderings of English terms (Kubernetes, deploy, ...) with a per-language glossary applied before summarization
- **✂️ Silent Tail Trimming**: Automatically detects and removes silent tails from recordings (e.g. when you forget to stop recording) using binary search — fast regardless of file length
- **👥 Speaker Diarization**: Identify who spoke when with interactive speaker labeling
- **🤖 AI Summarization**: Generate structured meeting notes using Ollama — summary, discussion points, decisions, and action items (only when genuinely present)
- **📋 Status & Catchup**: See which recordings are pending, partially processed, or complete; automatically process any that got missed
- **🔗 Post-Summary Hook**: Run any script after summarization completes — upload to Outline, Notion, a webhook, or anything else
- **🖥️ Guided Terminal Flow**: `shepitnote meeting` walks record → review (language/transcript/summary) → edit title → confirm-gated publish to Confluence/Slack; nothing is sent without an explicit yes, and it works over SSH
- **🔒 100% Private**: All processing happens locally — no internet required after setup
- **⚡ CPU-first, GPU-optional**: runs on CPU by default (fast on modern multi-core CPUs) and uses an NVIDIA GPU automatically when present, with CPU fallback on out-of-memory. faster-whisper has no AMD/ROCm backend, so on AMD systems transcription runs on CPU — GPU acceleration there (whisper.cpp + Vulkan) is on the roadmap

## Installation

### System Requirements

- Linux with PipeWire or PulseAudio
- Python 3.10+
- ffmpeg
- Ollama (for summarization)
- Optional: an NVIDIA GPU (CUDA) for faster transcription/diarization — not required; CPU works well

### Quick Install

```bash
git clone https://github.com/yuriytkach/shepitnote.git
cd shepitnote

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
./shepitnote --help
```

**System dependencies — Debian / Ubuntu / KDE neon:**
```bash
sudo apt install ffmpeg pipewire-pulse python3-venv
```

**Arch / CachyOS:**
```bash
yay -S ffmpeg pipewire-pulse python   # PipeWire
# or
yay -S ffmpeg pulseaudio-utils python  # PulseAudio
```

## Configuration

Copy `.shepitnoterc.example` to `.shepitnoterc` and edit to your needs:

```bash
cp .shepitnoterc.example .shepitnoterc
```

`.shepitnoterc` is sourced at startup and ignored by git. The example file documents every available option with defaults and comments, including audio backend, Whisper model, Ollama model, silent tail trimming thresholds, and the post-summary hook.

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
./shepitnote full -l uk     # force Ukrainian
./shepitnote full -l ru     # force Russian
./shepitnote full -l en     # force English
./shepitnote full -l auto   # auto-detect (same as leaving it unset)
```

Set a permanent default in `.shepitnoterc`:

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
./shepitnote transcribe clip.wav -l auto   # what auto-detect produces
./shepitnote transcribe clip.wav -l uk     # explicit language (uk/ru/en)
```

Check both transcripts against what was actually said. If `-l auto` sometimes
labels Ukrainian audio as Russian while `-l uk` reads correctly, set
`WHISPER_LANGUAGE=uk` as your default. Repeat with a Russian and an English clip
to confirm the explicit codes behave for each.

### English tech-term accuracy (hotwords + glossary)

Meetings that mix Ukrainian/Russian speech with English programming terms hit two
Whisper failure modes: English tech terms (Kubernetes, deploy, Helm chart) get
rendered **phonetically in Cyrillic**, and a single track with both ru and uk
speakers degrades whichever language wasn't chosen. ShepitNote adds two independent,
**opt-in** layers to fix the first problem (and soften the second). With none of
the settings below configured, behavior is identical to before.

#### 1. Decoding bias — hotwords / initial prompt

Seed faster-whisper with the product names, services, and English tech terms your
team uses so decoding is biased toward the correct spellings:

```bash
# One-off:
./shepitnote process meeting.wav --hotwords "Kubernetes deploy Helm chart Jenkins GitHub Postgres Grafana"

# Or a sentence-form bias (takes precedence over hotwords):
./shepitnote process meeting.wav --initial-prompt "We discuss Kubernetes, deploys, Helm charts, Jenkins, GitHub, Postgres and Grafana."
```

Set permanent defaults in `.shepitnoterc`:

```bash
WHISPER_HOTWORDS="Kubernetes deploy Helm chart Jenkins GitHub Postgres Grafana"
# or, mutually exclusive with the above (initial_prompt wins):
WHISPER_INITIAL_PROMPT="We discuss Kubernetes, deploys, Helm charts, Jenkins, GitHub, Postgres and Grafana."
```

faster-whisper applies **hotwords only when no initial prompt is set**, so
ShepitNote passes only one of the two (initial prompt takes precedence) to keep
behavior deterministic. Keep the seed list modest — an overly long or aggressive
bias can cause hallucinated insertions of the seeded terms.

#### 2. Term glossary — per-language find/replace before summarization

Whatever Whisper still renders phonetically is normalized by a glossary applied
to the transcript **before** the summary is generated (so every path — simple,
diarized, and dual — benefits). Glossary files live in `GLOSSARY_DIR` (default:
the shepitnote directory):

| File | Applied to |
|------|------------|
| `glossary.txt` | every language (shared) |
| `glossary.uk.txt` | Ukrainian transcripts |
| `glossary.ru.txt` | Russian transcripts |
| `glossary.<lang>.txt` | any other language |

Format — one rule per line, `#` comments and blank lines ignored; the left side
may list phonetic variants separated by `|`; matching is case-insensitive
(Cyrillic-aware) and whole-word:

```
# glossary.uk.txt
кубернетіс|кубернетес => Kubernetes
задеплоїти|задеплоїв|задеплоїмо => deploy
хелм чарт => helm chart
```

Ship templates live next to `shepitnote` as `glossary*.txt.example`. Copy one and
edit it to activate (real `glossary.*.txt` files are git-ignored, so they stay
private automatically):

```bash
cp glossary.uk.txt.example glossary.uk.txt
cp glossary.txt.example    glossary.txt      # shared, cross-language
```

**Language resolution.** The glossary is per-language, but at summary time only
the `.txt` transcript exists. ShepitNote picks the language in this order, never
crashing: (1) the explicit `-l` / `WHISPER_LANGUAGE`; else (2) the language
recorded in the sibling transcription JSON (`*_speakers_labeled.json`, `*.json`,
or `*.voice.json` — present for diarized and dual meetings, and for any explicit
run); else (3) the **union** of all `glossary.*.txt` files (safe, because uk
entries don't match ru text and the English targets are identical). To preview a
substitution without summarizing: `python3 glossary.py transcript.txt -l uk`.

#### 3. LLM normalization in the summary

When a glossary is active, its canonical target terms are also folded into the
summarization prompt, so the LLM normalizes the remaining phonetic/inflected
renderings the literal find/replace missed — directly in the Confluence/Slack
summary. This is automatic and off when no glossary is present (or with
`summarize.py --no-glossary`).

#### Measuring the improvement (user verification step)

Like language selection, the payoff depends on **your own audio** and can't be
measured for you or in CI. To verify on a real mixed-language clip:

1. Pick one clip with mixed uk/ru speech **and** several English tech terms
   (Kubernetes, deploy, Helm chart, Jenkins).
2. **Baseline (feature off):** ensure `.shepitnoterc` has no `WHISPER_HOTWORDS` /
   `WHISPER_INITIAL_PROMPT` and no real `glossary.*.txt`, then run
   `./shepitnote process clip.wav -l uk`. Save the transcript and summary.
3. **Enable:** set `WHISPER_HOTWORDS="Kubernetes deploy Helm chart Jenkins ..."`
   (tailor to your stack) and `cp glossary.uk.txt.example glossary.uk.txt` (edit
   for your terms; also `glossary.ru.txt` / shared `glossary.txt` as needed).
   Re-run the same command on the same clip.
4. **Compare:** (a) in the transcript, count how many English terms now appear in
   clean Latin form vs phonetic Cyrillic (the hotwords/initial-prompt effect);
   (b) in `*_summary.md`, check that remaining phonetic renderings are normalized
   to the canonical spellings (glossary find/replace + LLM normalization).
   Improvement = more terms rendered correctly in the summary, with no regression
   to the uk/ru wording.
5. Iterate: add any still-mis-rendered term to the glossary and/or
   `WHISPER_HOTWORDS` and re-run. Because everything is opt-in, an empty config
   reproduces the baseline exactly.

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
# Record a meeting, stop with Ctrl+C — automatically compresses, trims, transcribes, summarizes
./shepitnote full

# Check status of all recordings
./shepitnote status

# Process any recordings that were interrupted or missed
./shepitnote catchup

# Process a recording you already have
./shepitnote process recordings/meeting.wav

# Trim a recording manually (remove silent tail)
./shepitnote trim recordings/meeting.mp3
```

### Guided flow with review + confirm-gated publishing

`shepitnote meeting` runs the whole loop from a single command and, unlike `full`,
**never publishes automatically** — every destination is confirmed by you first:

```bash
# Record -> review -> edit title -> confirm each publish target
./shepitnote meeting

# Optional: pre-set the title, auto-stop after 1h, pick a model/language
./shepitnote meeting -t "Sprint planning" -d 3600 -m small -l en
```

What it does, in order:

1. **Records** (stop with Ctrl+C, or `-d SECONDS`), reusing the normal record
   path — dual-track (`AUDIO_SOURCE_TYPE=dual`) meetings work here too.
2. **Transcribes and summarizes** by reusing the `process` pipeline, but with the
   automatic `POST_SUMMARY_HOOK` **suppressed**, so nothing is sent yet.
3. **Shows** the detected language, the full transcript and the generated summary
   with clear section headers (paged with `less` when interactive; plain output
   when piped or non-interactive).
4. Lets you **edit the meeting title**, written back into `<base>_metadata.json`
   so the publishers use the new value.
5. For **each configured target** (Confluence if `CONFLUENCE_BASE_URL` is set,
   Slack if `SLACK_WEBHOOK_URL` / `SLACK_BOT_TOKEN` is set) asks an explicit
   yes/no and only publishes on `yes`. A blank answer, EOF, `n`, or anything that
   is not an explicit yes means **do not publish** (fail-safe). If no target is
   configured it says so and skips publishing. When **both** are configured,
   Confluence is asked first; if you confirm Confluence but its publish fails
   (no page link produced), Slack is **skipped** rather than posting a linkless
   message that could never be back-filled with the link.

It uses plain line prompts (read from `/dev/tty`, like the title prompt during
recording) — **not** a curses TUI — so it works over a bare **SSH** session and
when stdout is a pipe. The one-shot summarization or a failed publish is surfaced
as a clear error rather than silently continuing.

> Once you have made your per-target decision, the guided flow marks the meeting
> handled (writes the `.hook_done` marker), so a later `catchup` will **not**
> re-run the automatic hook on it and override your choices — an explicit "no"
> stays "no". Your decision here is the authority for that meeting. To (re)publish
> a target afterwards, invoke its publisher under `hooks/` directly.

### Dual-track (You/Remote) recording

For calls where you want reliable "who said what" without diarization, set
`AUDIO_SOURCE_TYPE=dual`. ShepitNote records two time-synchronized tracks from a
single command — your microphone (You) and the system sink monitor (Remote):

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote full
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
recordings/                                       # default; override with RECORDINGS_DIR
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

Set `POST_SUMMARY_HOOK` in `.shepitnoterc` to run a script after every summary is created. The script receives the summary file path as `$1`. On success, shepitnote writes a `.hook_done` marker so `catchup` knows not to re-run it.

```bash
# In .shepitnoterc:
POST_SUMMARY_HOOK="${HOME}/.local/bin/my-upload-script"
```

Use this to upload to Outline, Notion, a webhook, or any other destination. See `.shepitnoterc.example` for details.

### Confluence publishing

ShepitNote ships a post-summary hook, `hooks/confluence_publish.py`, that converts each
summary to Confluence storage format and creates — or, on re-run, updates — a page in a
configured space (issue #3). Point `POST_SUMMARY_HOOK` at it to enable:

```bash
# In .shepitnoterc:
POST_SUMMARY_HOOK="${HOME}/path/to/shepitnote/hooks/confluence_publish.py"
```

**Configuration** (all read from the environment; `.shepitnoterc` is sourced before the hook
runs, so set them there — see `.shepitnoterc.example` for the annotated block):

| Variable | Required | Purpose |
| --- | --- | --- |
| `CONFLUENCE_BASE_URL` | yes | Wiki base, no trailing `/rest/api`. Cloud: `https://yourorg.atlassian.net/wiki`; Server/DC: `https://confluence.yourorg.com` |
| `CONFLUENCE_SPACE_KEY` | yes | Target space key (e.g. `ENG`) |
| `CONFLUENCE_API_TOKEN` | yes | Cloud API token or Server/DC Personal Access Token (never hardcoded) |
| `CONFLUENCE_EMAIL` | no | Atlassian account email; its presence selects Cloud Basic auth |
| `CONFLUENCE_PARENT_PAGE_ID` | no | Numeric parent page id; new pages are created under it and updates re-assert it |
| `CONFLUENCE_AUTH_MODE` | no | Force `basic` or `bearer`; otherwise derived from whether `CONFLUENCE_EMAIL` is set |
| `CONFLUENCE_DRY_RUN` | no | `=1` forces dry-run (same as `--dry-run`) |

**Getting a token.** On **Confluence Cloud**, create an API token at
[id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens) and set
`CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` (auth is HTTP Basic `email:token`). On **Server /
Data Center**, create a Personal Access Token in your profile and set `CONFLUENCE_API_TOKEN`
with no email (auth is `Bearer <PAT>`).

**Page title and idempotency.** The page title is `"<meeting title> - YYYY-MM-DD"`, or
`"Meeting HH:MM - YYYY-MM-DD"` when the recording had no title (both derived from the sibling
`<base>_metadata.json`, falling back to the timestamp in the filename). Because that title is
stable for a given meeting, the hook searches the space for it and **updates the existing page**
(version incremented) instead of creating a duplicate — re-running `catchup`/`process` on the
same meeting is safe. The created page id is also cached in a sibling
`<base>.confluence_page_id` marker as a fallback lookup (guards against Cloud search-index lag).

**Dry-run — preview before publishing.** Run the hook with `--dry-run` (needs no credentials)
to resolve the title and print the storage-format XHTML without touching the API:

```bash
hooks/confluence_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```

Inspect the output, then set the `CONFLUENCE_*` config and let the hook publish for real.

**Confirm-gating.** When wired to `POST_SUMMARY_HOOK`, this publisher runs automatically after
every summary — enabling it is opt-in purely by setting `POST_SUMMARY_HOOK`. If you want an
interactive **confirm before each publish** instead, use
[`./shepitnote meeting`](#guided-flow-with-review--confirm-gated-publishing): it runs the same
publisher only after an explicit per-target yes and never publishes on its own. If a publish
fails (missing config, API/network error) the hook exits non-zero, so shepitnote does not write the
`.hook_done` marker and retries it on the next `catchup`/`process`.

### Slack publishing

ShepitNote ships a second post-summary hook, `hooks/slack_publish.py`, that posts a **short**
summary of each meeting to Slack (issue #4). It runs a distinct, terser second Ollama pass over
the summary — a 3-5 bullet TL;DR plus action items, separate from the full notes — renders it as
Slack mrkdwn, appends a link to the Confluence page when one exists, and posts it via an incoming
webhook or a bot token. Point `POST_SUMMARY_HOOK` at it to enable Slack only:

```bash
# In .shepitnoterc:
POST_SUMMARY_HOOK="${HOME}/path/to/shepitnote/hooks/slack_publish.py"
```

The TL;DR pass reuses the same `OLLAMA_MODEL` / `OLLAMA_URL` as the main summary (falling back to
the same `llama3.1:8b` / `http://localhost:11434` defaults), so Ollama must be running.

**Configuration** (all read from the environment; set them in `.shepitnoterc`, which is sourced
before the hook runs — see `.shepitnoterc.example` for the annotated block). Pick **one** of the two
auth styles:

| Variable | Required | Purpose |
| --- | --- | --- |
| `SLACK_WEBHOOK_URL` | webhook mode | [Incoming webhook](https://api.slack.com/messaging/webhooks) URL; the channel is baked into it (a credential, never printed) |
| `SLACK_BOT_TOKEN` | bot mode | Bot token (`xoxb-…`) with `chat:write`; posts via `chat.postMessage` (a credential, never printed) |
| `SLACK_CHANNEL` | bot mode | Target channel for bot mode, e.g. `#meetings` |
| `SLACK_AUTH_MODE` | no | Force `webhook` or `bot`; otherwise derived from which of the above is set (both set -> webhook wins) |
| `SLACK_DRY_RUN` | no | `=1` forces dry-run (same as `--dry-run`) |

**No double-posting.** Slack messages are not idempotent (each POST creates a new message), so on a
confirmed post the hook writes a sibling `<base>.slack_done` marker and, on any later invocation,
**no-ops when that marker exists**. Because the hook is retried whenever it exits non-zero, this is
what keeps a retry from posting the same meeting twice — at most one Slack message per meeting.

**Confluence link when available.** If the Confluence publisher has already run for the meeting, it
leaves a sibling `<base>.confluence_page_id` marker; the Slack hook reads it and (with
`CONFLUENCE_BASE_URL` set) appends a `Full meeting notes on Confluence` link built as
`{CONFLUENCE_BASE_URL}/pages/viewpage.action?pageId=<id>` (works on Cloud and Server/DC). With no
marker or base URL the link is omitted gracefully and the message still posts.

**Dry-run — preview before posting.** Run the hook with `--dry-run` (needs no token/webhook) to
resolve the target and print the short summary and the exact payload without posting. It still
calls the local Ollama to build the real TL;DR:

```bash
hooks/slack_publish.py recordings/<date>/meeting_<ts>/meeting_<ts>_summary.md --dry-run
```

The bot token and webhook URL are never printed (redacted from every error and from the dry-run
target line). As with Confluence, the hook posts whenever it is invoked; for an interactive
**confirm before each post**, use
[`./shepitnote meeting`](#guided-flow-with-review--confirm-gated-publishing), which asks yes/no per
target and never posts on its own.

### Publishing to both

There is only one `POST_SUMMARY_HOOK` slot, so to publish the **full notes to Confluence and the
short TL;DR to Slack** point it at the bundled dispatcher, `hooks/publish.py`:

```bash
# In .shepitnoterc (with the CONFLUENCE_* and SLACK_* blocks both filled in):
POST_SUMMARY_HOOK="${HOME}/path/to/shepitnote/hooks/publish.py"
```

The dispatcher runs each publisher that is configured — Confluence when `CONFLUENCE_BASE_URL` is
set, Slack when `SLACK_WEBHOOK_URL` or `SLACK_BOT_TOKEN` is set — **Confluence first**, so its page
link is available to the Slack message in the same run. Each publisher is independently idempotent
(Confluence updates the same page; Slack skips on its `.slack_done` marker), so a retry after a
partial failure re-runs only what failed and never duplicates. The dispatcher exits non-zero if any
enabled publisher failed (so shepitnote retries), and the standalone publishers remain directly
invokable for one-destination setups.

## Troubleshooting

**No audio captured:**
```bash
pactl list sources short
pactl set-default-source YOUR_SOURCE_NAME
./record_audio.sh -d 5   # test with a 5-second recording
```

**Wrong language detected:** faster-whisper samples only the first 30 seconds and picks one language for the whole file. If your meeting starts with silence or a different language — or if Ukrainian audio comes out transcribed as Russian (a common mislabel) — set the language explicitly with `-l uk|ru|en` or `WHISPER_LANGUAGE` in `.shepitnoterc`. See [Language selection](#language-selection-ukrainian--russian--english) for details.

**Ollama not responding:**
```bash
systemctl status ollama
ollama list
```

**GPU out of memory:** ShepitNote automatically falls back to CPU if CUDA OOM occurs during model load or transcription.

**Recording has a long silent tail:** Run `shepitnote trim FILE` to detect and remove it. The binary search scans ~10 windows to find the content boundary regardless of file length.

## License

MIT — see the [LICENSE](LICENSE) file. The original copyright (© 2025 Peter Jackson) is retained as required by the license.

## Credits

ShepitNote is a fork of **[hushnote](https://github.com/peteonrails/hushnote)** by Peter Jackson ([@peteonrails](https://github.com/peteonrails)), used under the MIT License. The original recording → transcription → summarization pipeline and the post-summary hook design come from that project; this fork adds dual-track You/Remote capture, uk/ru/en language handling, tech-term accuracy (hotwords + glossary), Confluence/Slack publishing with a dispatcher, and the guided `shepitnote meeting` flow.

Built on top of [faster-whisper](https://github.com/guillaumekln/faster-whisper), [Ollama](https://ollama.ai), [pyannote.audio](https://github.com/pyannote/pyannote-audio), and [ffmpeg](https://ffmpeg.org).
