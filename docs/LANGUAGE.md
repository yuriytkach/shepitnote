# Transcription, language & tech-term accuracy

ShepitNote is tuned for meetings that mix **Ukrainian, Russian, and English**
(with English tech terms). This guide covers Whisper model choice, per-meeting
language selection, and the two opt-in layers that keep English tech vocabulary
spelled correctly.

- [Whisper models](#whisper-models)
- [Language selection (uk / ru / en)](#language-selection-uk--ru--en)
- [English tech-term accuracy (hotwords + glossary)](#english-tech-term-accuracy-hotwords--glossary)

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
