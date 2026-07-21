# Cloud mode (optional)

ShepitNote runs **fully local by default** — audio and transcript never leave
your machine. When a meeting is not sensitive and you'd rather trade privacy for
speed and a stronger model, **cloud mode** offloads the two heavy steps:

- **Summarization** → an [Ollama Cloud](https://ollama.com/cloud) model (bigger
  and smarter than what fits locally, with no RAM/CPU cost on your box).
- **Transcription** → a cloud Whisper API (near-instant instead of ~real-time on
  CPU) — *only if you configure an API key*; otherwise it stays local.

Cloud mode is **off unless you turn it on**, and when on it prints a clear
warning and (in the guided `meeting` flow) asks you to confirm before anything
is uploaded.

- [Turning it on](#turning-it-on)
- [What gets uploaded (and what doesn't)](#what-gets-uploaded-and-what-doesnt)
- [Summarization on the cloud](#summarization-on-the-cloud)
- [Transcription on the cloud](#transcription-on-the-cloud)
- [Choosing a transcription provider](#choosing-a-transcription-provider)
- [Cost & free tiers](#cost--free-tiers)

## Turning it on

Per run (recommended — nothing changes permanently):

```bash
./shepitnote --cloud meeting          # guided flow, cloud this once
./shepitnote --cloud process-last     # re-process the last recording in the cloud
```

Or make it the default in `.shepitnoterc` (then `--no-cloud` forces local for a
single run):

```bash
CLOUD=true
```

The switch is off by default, so an unset config behaves exactly as before this
feature existed.

## What gets uploaded (and what doesn't)

| Step | Local mode | Cloud mode |
|------|-----------|------------|
| Recording | on your machine | on your machine (never uploaded) |
| Transcription | local Whisper (CPU) | **audio uploaded** to the Whisper API — *only with a key set*, else local |
| Summarization | local Ollama | **transcript uploaded** to Ollama Cloud |

Two independent privacy levels fall out of this:

- **Cloud summary, local audio** (the safe middle ground): set `CLOUD=true` but
  leave the transcription key unset (or set `CLOUD_TRANSCRIBE=false`). Audio
  stays on your machine; only the text transcript is uploaded for summarizing.
- **Cloud transcription, local summary** (fast transcription, your preferred
  local notes): set `CLOUD=true` and `CLOUD_SUMMARIZE=false`, or pass
  `--local-summary` for a single run. Audio is uploaded to the Whisper API for
  speed, but the transcript is summarized on your local Ollama model and never
  leaves — handy when the local model writes better notes than the cloud one.
- **Full cloud**: add a transcription API key so audio is uploaded too.

In the guided `meeting` flow, cloud mode prints exactly which of these will
happen and asks you to confirm **before recording**. Declining processes the run
locally.

## Summarization on the cloud

You must be signed in to Ollama Cloud once:

```bash
ollama signin
ollama pull gpt-oss:120b-cloud   # instant — cloud tags download nothing
```

In cloud mode the summary model is `CLOUD_SUMMARY_MODEL` (default
`gpt-oss:120b-cloud`). Everything else about summarization — glossary
normalization, translate-first, the prompt — is unchanged; only the model
differs.

**Free tier vs. paid.** Not every cloud model is on Ollama's free tier. The
free-tier picks that work well here:

| Model | Tier | Notes |
|-------|------|-------|
| **gpt-oss:120b-cloud** (default) | free | Most accurate Russian-meeting notes in testing here; ~20 s/summary |
| gemma4:31b-cloud | free | Lighter/faster (~8 s); slightly less accurate |
| qwen3.5:cloud / glm-5.2:cloud | **paid** (Ollama Pro) | Rank highest for ru/uk; use these if you have a subscription |

The default was chosen by A/B-ing the free-tier models on a real Russian meeting:
`gpt-oss:120b-cloud` transcribed technical detail more faithfully and kept
speaker labels honest, where `gemma4:31b-cloud` muddled some names and terms.
Swap the model any time — it's just a config value; if you upgrade to Ollama Pro,
`qwen3.5:cloud` is the strongest multilingual choice.

## Transcription on the cloud

**Ollama Cloud does not do speech-to-text** (it serves text LLMs only), so cloud
transcription uses a separate provider. ShepitNote speaks the **OpenAI
`/audio/transcriptions`** shape, which every major host implements, so switching
providers is three settings and no code:

```bash
CLOUD_TRANSCRIBE_BASE_URL=https://api.groq.com/openai/v1   # provider endpoint
CLOUD_TRANSCRIBE_MODEL=whisper-large-v3                    # model name
GROQ_API_KEY=gsk_...                                       # or CLOUD_TRANSCRIBE_API_KEY
```

Notes:

- **No key → local Whisper.** If no key is set, transcription silently falls back
  to the local model even in cloud mode. So you can enable cloud summaries today
  and add a transcription key later.
- **Resilient.** Any cloud transcription failure (network, rate limit, bad key)
  logs a clear message and falls back to local Whisper — a meeting is never lost
  to a transient cloud hiccup.
- **Small uploads.** Audio is transcoded to 16 kHz mono before upload (what
  Whisper uses internally — no accuracy loss), which keeps files tiny and under
  provider size caps (Groq's free tier caps uploads at 25 MB).
- **Same output.** The cloud path returns the identical transcript JSON as the
  local path, so diarization, You/Remote merging, and summarization all work
  unchanged.

## Choosing a transcription provider

All of these expose the OpenAI-compatible endpoint — set the three variables
above and you're done.

| Provider | Model | Price / audio-hr | Free tier | Notes |
|----------|-------|------------------|-----------|-------|
| **Groq** (default) | whisper-large-v3 / -turbo | ~$0.11 / ~$0.04 | ~8 h/day free | Fastest (~190–216× realtime); same Whisper as local |
| Fireworks | whisper-large-v3 | ~$0.06 | ~$1 credit | Cheapest paid |
| Together | whisper-large-v3 | ~$0.06 | ~$1 credit | |
| OpenAI | whisper-1 / gpt-4o-transcribe | ~$0.36 | none | The reference API |

Groq is the default because it runs the *same* Whisper large-v3 as the local
path, is the fastest, and its free tier already covers normal meeting use. To
use another, change `CLOUD_TRANSCRIBE_BASE_URL` / `CLOUD_TRANSCRIBE_MODEL` and
set that provider's key.

## Cost & free tiers

- **Groq (transcription):** free tier ≈ 8 h of audio/day, 2 h/hr — more than
  enough for meetings. Paid is a few cents per audio-hour if you ever exceed it.
- **Ollama Cloud (summaries):** a free tier with 5-hour-session and weekly caps
  (usage is metered by GPU time, so bigger models draw it down faster); Pro is
  ~$20/mo if you summarize heavily.

Both are billed/limited independently, so you can mix a free Groq key with a free
Ollama Cloud tier and stay at $0 for typical use.
