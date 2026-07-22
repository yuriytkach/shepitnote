# Transcription, language & tech-term accuracy

ShepitNote is tuned for meetings that mix **Ukrainian, Russian, and English**
(with English tech terms). This guide covers Whisper model choice, per-meeting
language selection, and the two opt-in layers that keep English tech vocabulary
spelled correctly.

- [Whisper models](#whisper-models)
- [Language selection (uk / ru / en)](#language-selection-uk--ru--en)
- [English tech-term accuracy (hotwords + glossary)](#english-tech-term-accuracy-hotwords--glossary)
- [Summary output language](#summary-output-language)

## Whisper models

| Model | Size | Speed | Use Case |
|-------|------|-------|----------|
| `tiny` | 75 MB | ~10-20x realtime | Testing |
| `base` | 150 MB | ~5-10x realtime | Balanced |
| `small` | 500 MB | ~2-5x realtime | Better accuracy |
| `medium` | 1.5 GB | ~1-2x realtime | Professional |
| `large-v3` | 3 GB | ~0.5-1x realtime | Maximum accuracy (default) |

Models download automatically on first use (pre-fetch one with
`./setup.sh --model small`). `large-v3` is the default because multilingual
(Ukrainian/Russian/English) accuracy matters more here than speed; this project
targets an AMD APU with no usable CUDA, so it runs on CPU at roughly real-time
(~0.5-1x), materially slower than `base`. Override per run with `-m base` /
`-m small` or set `WHISPER_MODEL=base` when speed matters.

## Removing hallucinated text (VAD + repetition control)

Whisper (every size, `large-v3` included) **invents text on near-silent
stretches** — most visibly on dual-track recordings, where one track is quiet
while the other side talks. Symptoms in the transcript: a word or phrase repeated
many times (`Спасибо. Спасибо. Спасибо. …`, `shepard shepard shepard`) or short
bursts of an unrelated script (Korean/Japanese/Chinese). This garbage then
pollutes the summary — in one real meeting a hallucinated `shepard` became a
fictional "Shepard System" topic *and* an action item.

Two settings, **on by default**, prevent it (no config needed):

| Setting | Default | Effect |
|---------|---------|--------|
| `WHISPER_VAD` | `true` | Voice-activity detection skips non-speech before decoding, so silent stretches can't be turned into words. Usually also *speeds up* CPU transcription. |
| `WHISPER_CONDITION_ON_PREVIOUS_TEXT` | `false` | Stops feeding each window the previous window's text — the mechanism behind runaway repetition loops. |

To tune per run, set the env var (it propagates to the transcriber on every path):

```bash
WHISPER_VAD=false ./shepitnote transcribe clip.wav                 # disable VAD
WHISPER_CONDITION_ON_PREVIOUS_TEXT=true ./shepitnote process meeting.wav
```

For stubborn cases, also skip long silent gaps explicitly (slower — it enables
word timestamps):

```bash
WHISPER_HALLUCINATION_SILENCE=2.0 ./shepitnote process meeting.wav
```

Calling the worker directly also exposes `--vad` / `--no-vad`,
`--condition-on-previous` / `--no-condition-on-previous`, and
`--hallucination-silence-threshold` on `transcribe.py`.

## Language selection (uk / ru / en)

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

### Measuring accuracy on your own recordings (user verification step)

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

## English tech-term accuracy (hotwords + glossary)

Meetings that mix Ukrainian/Russian speech with English programming terms hit two
Whisper failure modes: English tech terms (Kubernetes, deploy, Helm chart) get
rendered **phonetically in Cyrillic**, and a single track with both ru and uk
speakers degrades whichever language wasn't chosen. ShepitNote adds two independent,
**opt-in** layers to fix the first problem (and soften the second). With none of
the settings below configured, behavior is identical to before.

### 1. Decoding bias — hotwords / initial prompt

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

### 2. Term glossary — per-language find/replace before summarization

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

### 3. LLM normalization in the summary

When a glossary is active, its canonical target terms are also folded into the
summarization prompt, so the LLM normalizes the remaining phonetic/inflected
renderings the literal find/replace missed — directly in the Confluence/Slack
summary. This is automatic and off when no glossary is present (or with
`summarize.py --no-glossary`).

### Measuring the improvement (user verification step)

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

## Summarization model & translate-first (non-English meetings)

A summary is only as good as the model that writes it. On this CPU/APU box the
sweet spot is a **Mixture-of-Experts (MoE)** model — large in total size but with
few *active* parameters per token, so it stays fast:

- **Recommended:** `qwen3:30b-a3b-instruct-2507-q4_K_M` (~18 GB; 30B total, ~3.3B
  active/token). On a real Russian meeting it produced a better summary in **~90 s**
  vs **~5 min** for the dense `gemma4:latest` — more accurate speaker attribution
  and no invented topics. Install and select it with:

  ```bash
  ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M
  # then in .shepitnoterc:
  OLLAMA_MODEL=qwen3:30b-a3b-instruct-2507-q4_K_M
  ```

- Avoid **dense** models much above ~9B (e.g. `qwen3.6:27b`): quality is fine, but
  they activate every parameter and run slowly on the APU.
- Never use `*:cloud` models — they send the transcript off-machine, defeating the
  local-only design.

### Translate-first (opt-in)

For non-English meetings you can translate the transcript to English **before**
summarizing, on the theory that models summarize best in English:

```bash
SUMMARY_TRANSLATE=true ./shepitnote process meeting.wav     # env
python3 summarize.py transcript.txt --translate             # worker flag
# optional separate translate model:
SUMMARY_TRANSLATE_MODEL=qwen3:30b-a3b-instruct-2507-q4_K_M
```

In testing on a Russian meeting this was **roughly a wash** with the multilingual
MoE model above — and because the translation is faithful, it can carry
transcription errors into English (`врачи` → "doctors", garbled numbers) rather
than smoothing over them, which a direct multilingual summary sometimes does.
Treat it as a per-meeting experiment, not a default. It runs two model passes
(translate, then summarize), so expect roughly double the summarization time
(~4 min with the MoE model on a ~13-minute meeting).

## Summary output language

By default the summary comes out in whatever language the model picks on its
own — in practice usually English, regardless of the meeting's language. Set
`--summary-lang` / `SUMMARY_LANGUAGE` to get notes in the meeting's own
language instead (e.g. a Ukrainian-only meeting, Ukrainian notes):

```bash
./shepitnote meeting --summary-lang uk       # this run only
python3 summarize.py transcript.txt --summary-lang uk   # worker flag
```

Set a permanent default in `.shepitnoterc`:

```bash
SUMMARY_LANGUAGE=uk       # or ru / en / any language name; unset = model's own choice
```

Recognized short codes `en`/`uk`/`ru` are expanded to a full name in the prompt
(the model follows "Ukrainian" more reliably than a bare code); any other code
or an already-spelled-out name (e.g. `pl`, `Polish`) is passed through as-is.

This is **independent of `-l`/`WHISPER_LANGUAGE`** (the transcription language)
and composes with translate-first: `--translate` can still run the transcript
through English for a better summarization pass, while `--summary-lang`
controls what language the *output* comes back in. On a real Ukrainian and a
real Russian meeting with the recommended MoE model
(`qwen3:30b-a3b-instruct-2507-q4_K_M`), the body content reliably came back in
the requested language; the markdown section headings (`## Summary`,
`## Discussion`, ...) were translated too on some runs but stayed in English on
others — that part is best-effort and depends on the model's sampling, while
the actual notes content is not.
