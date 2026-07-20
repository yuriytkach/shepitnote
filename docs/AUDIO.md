# Audio capture

How ShepitNote records meetings — choosing a capture mode, getting clean
"who said what" without diarization, cancelling speaker echo on headset-free
calls, routing call audio from Zoom/Slack/Meet, and the files each mode produces.

- [Capture modes](#capture-modes)
- [Dual-track (You/Remote) recording](#dual-track-youremote-recording)
- [Splitting Remote into per-speaker labels](#splitting-remote-into-per-speaker-labels)
- [Echo cancellation (open-speaker meetings)](#echo-cancellation-open-speaker-meetings)
- [Routing call audio (Zoom, Slack, Meet, Bluetooth)](#routing-call-audio-zoom-slack-meet-bluetooth)
- [Verify your routing on a real call](#verify-your-routing-on-a-real-call)
- [Output files](#output-files)

## Capture modes

Capture is **sink-monitor based**, so it is app-agnostic: the remote side of any
call — Zoom (native app or browser), Slack huddles, Google Meet, Discord — plays
through your **default sink**, and ShepitNote records that sink's `.monitor`. You
do not configure anything per app; you configure the *default sink*.

Pick the mode with `AUDIO_SOURCE_TYPE` (set it per run, or permanently in
`.shepitnoterc`):

| Mode | What you get | Use when |
|------|--------------|----------|
| `dual` | two tracks: **You** (mic) + **Remote** (sink monitor), labeled by origin | recommended for calls — clean You/Remote notes |
| `both` | one track mixing mic + sink monitor | you just want a single blended recording |
| `monitor` | sink monitor only (the remote side) | you only need what the others said |
| `microphone` (default) | mic only | in-person / dictation, no call audio |

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote meeting -o llama3.1:8b   # recommended for a call
```

List the sources detected on your machine, then switch the default if needed:

```bash
pactl list short sources          # see available sources (name / ID)
pactl get-default-source          # what's currently default
pactl set-default-source <NAME>   # switch to a specific mic
```

## Dual-track (You/Remote) recording

For calls where you want reliable "who said what" without diarization, set
`AUDIO_SOURCE_TYPE=dual`. ShepitNote records two time-synchronized tracks from a
single command — your microphone (You) and the system sink monitor (Remote):

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote full
```

The two tracks map like this:

- **You** ← the default *source* (your microphone): `pactl get-default-source`
- **Remote** ← the monitor of the default *sink* (what plays through your
  speakers/headset): `pactl get-default-sink` (its `.monitor` is captured)

This produces `meeting_TS.voice.wav` (You) and `meeting_TS.system.wav` (Remote).
Each track is transcribed separately, every segment is tagged by its track of
origin, and the two are interleaved by timestamp into one transcript with
`[You]` / `[Remote]` labels — no diarization guessing over a blended track.

By default, attribution is **You vs. Remote** only: your microphone is always
`[You]`, and everyone on the far side shares one `[Remote]` label. To tell the
far-side people apart — `[Remote 1]`, `[Remote 2]`, … — enable the opt-in
[remote-track diarization](#splitting-remote-into-per-speaker-labels) described
below. Either way, `[You]` is never diarized, so your own voice is always
cleanly separated by track of origin.

> **On open speakers without a headset,** your mic records the remote audio
> playing aloud, so the You track becomes an echo of Remote. Run
> **`./shepitnote aec on`** before the call to cancel it in real time — see
> [Echo cancellation](#echo-cancellation-open-speaker-meetings) below. With a
> headset you don't need it.

Notes:

- Local vs remote is decided by track of origin, so labeling is reliable even
  when both sides overlap. To split the far side into individual people, turn on
  [remote-track diarization](#splitting-remote-into-per-speaker-labels) — it runs
  pyannote on the system track only, never on your mic.
- Silent-tail trimming is **skipped** in dual mode, because per-track trimming
  would desync turn ordering.
- Dual honors `RECORD_BACKEND`; use `RECORD_BACKEND=pw-record` for Bluetooth
  HSP/HFP headsets (see [Bluetooth](#routing-call-audio-zoom-slack-meet-bluetooth)).
- The existing mixed `AUDIO_SOURCE_TYPE=both` mode (one blended WAV) remains
  available as a fallback.

## Splitting Remote into per-speaker labels

By default every far-side voice shares one `[Remote]` label. When a call has
several remote people and you want to know which of them said what, turn on
**remote-track diarization**: ShepitNote runs pyannote on the *system track
only* and splits `[Remote]` into `[Remote 1]`, `[Remote 2]`, … ordered by who
spoke first. Your microphone track is **never** diarized, so `[You]` stays a
clean, guess-free split by track of origin — the diarization only ever runs on
the far side.

Enable it per run or in `.shepitnoterc`:

```bash
DUAL_REMOTE_DIARIZATION=true AUDIO_SOURCE_TYPE=dual ./shepitnote meeting
```

It is **opt-in and best-effort**:

- Requires an `HF_TOKEN` (the same HuggingFace token used elsewhere for pyannote
  — see [Diarization setup](DIARIZATION.md)) and `pyannote.audio` installed
  (`pip install pyannote.audio`).
- If the token is missing, pyannote is not installed, or diarization fails for
  any reason, the meeting still completes with a single `[Remote]` label — the
  base dual-track flow never gains a hard dependency.
- If only one far-side speaker is detected, the plain `[Remote]` label is kept
  (numbering appears only when 2+ are found).
- Telling pyannote how many people are on the far side matters: auto-detect
  **over-splits on compressed VoIP audio** (a real 6-person call was detected as
  8, inflating the speaker list). The guided **`meeting`** flow now asks *"How
  many people were on the call, not counting you?"* after recording and passes
  your answer through — a blank answer falls back to auto-detect. For non-guided
  runs, set it yourself: `DUAL_REMOTE_SPEAKERS=N` fixes the far-side count, or
  `DUAL_REMOTE_MIN_SPEAKERS` / `DUAL_REMOTE_MAX_SPEAKERS` bound it. When set in the
  environment, the prompt is skipped.

The split adds a diarization pass over the system track, so processing a dual
meeting takes longer with it on. Speaker labels are still `[Remote N]`, not real
names — run [`./shepitnote label`](DIARIZATION.md) afterwards if you want to
rename them.

## Echo cancellation (open-speaker meetings)

If you take calls on laptop speakers without a headset, the mic records the
remote audio playing aloud and the You track becomes a duplicate of Remote.
ShepitNote wraps PipeWire's WebRTC echo canceller behind a simple toggle:

```bash
./shepitnote aec on       # cancel the remote bleed from your mic (real time)
./shepitnote aec status   # is it active?
./shepitnote aec off      # restore your original devices and unload it
```

- **Off by default and fully reversible** (also reverts on reboot). Turn it on
  before a speaker meeting, off afterwards.
- **Enable before joining** for the cleanest result; enabling mid-call also works
  (it pulls the in-progress call's audio into the canceller) after a moment to
  adapt.
- **Also cleans your mic for Zoom/Meet/Slack**, since it switches your default
  input to the cancelled mic.
- **Double-talk is fine:** Remote is captured separately from the system audio
  (never touched by AEC) and the canceller preserves your voice, so both sides
  land on their own track.
- **Streaming with an external mic (OBS)?** Leave it off — it only affects
  capture while enabled. It pins to whichever mic/speaker was default at `aec on`
  time, so after switching devices, run `aec off` then `aec on` again.

## Routing call audio (Zoom, Slack, Meet, Bluetooth)

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

## Verify your routing on a real call

Do this once. Join a test call (Zoom has a built-in test meeting; or a Slack
huddle with a colleague) and, **while the other side is talking**, record a short
sample:

```bash
AUDIO_SOURCE_TYPE=dual ./shepitnote full -d 15 -m tiny -o llama3.1:8b
```

Then, in the newest `recordings/<date>/meeting_*/` directory, confirm:

- both `*.voice.wav` (your mic) and `*.system.wav` (the remote side) exist and are
  ~15s: `ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 <file>`;
- `*.system.wav` actually contains the **remote** voice (play it back);
- the merged `*.txt` interleaves `[You]` and `[Remote]` lines.

If `*.system.wav` is silent, the call app is not on the default sink (see the Zoom
quirk) or you are on a BT headset in HSP/HFP (use `pw-record`). A `both`/`monitor`
recording that is silent has the same two causes.

## Output files

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
