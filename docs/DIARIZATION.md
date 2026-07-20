# Speaker Diarization Guide

**ShepitNote** now supports speaker diarization - identifying "who spoke when" in your meeting recordings.

## Overview

Speaker diarization adds speaker labels to transcriptions, making it easy to see who said what. This is particularly useful for:

- Multi-person meetings and interviews
- Panel discussions and group conversations
- Podcasts with multiple hosts/guests
- Customer calls and consultations

## Features

✅ **Automatic Speaker Detection** - Uses AI to identify different speakers
✅ **Interactive Labeling** - Shows quotes to help you identify each speaker
✅ **Privacy-First** - All processing happens locally on your machine
✅ **Future-Ready** - Designed for upcoming Zoom/Teams API integration
✅ **Multiple Formats** - Export with speaker labels in TXT, MD, JSON, SRT, VTT

## Quick Start

### Full Workflow with Diarization

```bash
# Record, diarize, transcribe, label, and summarize
./shepitnote full --diarize --speakers 3 -m small -o mistral:7b

# The workflow will:
# 1. Record audio
# 2. Identify 3 speakers
# 3. Transcribe the audio
# 4. Show you quotes and ask "Who is SPEAKER_00?"
# 5. You type names: "Alice", "Bob", "Charlie"
# 6. Create final transcript with [Alice], [Bob], [Charlie] labels
# 7. Generate AI summary with speaker context
```

### Step-by-Step Workflow

```bash
# 1. Record a meeting
./shepitnote record -d 1800  # 30 minutes

# 2. Identify speakers (diarization)
./shepitnote diarize recordings/meeting_20251005_143022.wav --speakers 3

# 3. Transcribe the audio
./shepitnote transcribe recordings/meeting_20251005_143022.wav -m small

# 4. Merge diarization + transcription (done automatically by shepitnote)
./merge_diarization.py recordings/meeting_20251005_143022_speakers.json \
                       recordings/meeting_20251005_143022.json

# 5. Label speakers interactively
./shepitnote label recordings/meeting_20251005_143022_diarized.json

# 6. Apply labels to create final transcript
./shepitnote apply-labels recordings/meeting_20251005_143022_speakers_labeled.json

# 7. Summarize (optional)
./shepitnote summarize recordings/meeting_20251005_143022.txt
```

## Setup

### 1. Install Dependencies

```bash
# Install pyannote.audio and dependencies
./venv/bin/pip install pyannote.audio torch huggingface-hub

# Or use requirements.txt
./venv/bin/pip install -r requirements.txt
```

### 2. Get HuggingFace Token

Pyannote models require a free HuggingFace account:

1. **Create account**: https://huggingface.co/join
2. **Accept conditions**: https://huggingface.co/pyannote/speaker-diarization-community-1
3. **Create token**: https://huggingface.co/settings/tokens
4. **Set environment variable**:

```bash
export HF_TOKEN="your_token_here"

# Or add to ~/.bashrc for persistence
echo 'export HF_TOKEN="your_token_here"' >> ~/.bashrc
```

**Note**: Token is only needed for first-time model download. Models are cached locally at `~/.cache/huggingface/` and work offline afterward.

## Usage Examples

### Example 1: Two-Person Interview

```bash
# Record interview
./shepitnote record -d 3600

# Diarize with 2 speakers
./shepitnote full --diarize --speakers 2 -m medium

# Interactive labeling shows:
# SPEAKER_00: "Thanks for joining me today..."
# → You type: "Host"
#
# SPEAKER_01: "Happy to be here..."
# → You type: "Guest"

# Output: transcript with [Host] and [Guest] labels
```

### Example 2: Multi-Person Meeting

```bash
# Record team meeting
./shepitnote record

# Auto-detect number of speakers
./shepitnote full --diarize -m small

# Label each speaker:
# SPEAKER_00 → "Alice" (Product Manager)
# SPEAKER_01 → "Bob" (Engineer)
# SPEAKER_02 → "Charlie" (Designer)
# SPEAKER_03 → "Dana" (QA Lead)
```

### Example 3: Existing Recording

```bash
# You already have a recording
./shepitnote diarize old_meeting.wav --speakers 4
./shepitnote transcribe old_meeting.wav -m base
./merge_diarization.py old_meeting_speakers.json old_meeting.json
./shepitnote label old_meeting_diarized.json
./shepitnote apply-labels old_meeting_speakers_labeled.json -f md
```

## Interactive Labeling

When you run `./shepitnote label`, you'll see:

```
ShepitNote Speaker Labeling
══════════════════════════════════════════════════════════════════

Found 3 speakers in meeting_20251005_143022.wav

──────────────────────────────────────────────────────────────────
SPEAKER_00 (7:30, 45 segments)

Sample quotes:
  [00:12] "Good morning everyone, let's get started."
  [03:45] "I think we need to prioritize the backend."
  [12:30] "Let me summarize the action items."

Who is SPEAKER_00? Alice Johnson
✓ Labeled as "Alice Johnson"

──────────────────────────────────────────────────────────────────
SPEAKER_01 (11:20, 67 segments)

Sample quotes:
  [01:15] "Thanks Alice. I wanted to discuss the API timeline."
  [05:22] "We should allocate more resources to frontend."
  [15:40] "I'll take ownership of the deployment pipeline."

Who is SPEAKER_01? Bob Smith
✓ Labeled as "Bob Smith"

──────────────────────────────────────────────────────────────────
✓ All speakers labeled!
```

## Output Formats

### Text Format (TXT)

```
[Alice Johnson] Good morning everyone, let's get started with today's meeting.

[Bob Smith] Thanks Alice. I wanted to discuss the timeline for the API release.

[Charlie Davis] I agree with Bob's approach on the architecture.
```

### Markdown Format (MD)

```markdown
**Alice Johnson**: Good morning everyone, let's get started.

**Bob Smith**: Thanks Alice. I wanted to discuss the API timeline.

**Charlie Davis**: I agree with Bob's approach.
```

### JSON Format

```json
{
  "segments": [
    {
      "speaker": "Alice Johnson",
      "speaker_id": "SPEAKER_00",
      "start": 0.5,
      "end": 5.2,
      "text": "Good morning everyone..."
    }
  ],
  "labels": {
    "SPEAKER_00": {
      "name": "Alice Johnson",
      "source": "manual"
    }
  }
}
```

### SRT Format (Subtitles)

```
1
00:00:00,500 --> 00:00:05,200
[Alice Johnson] Good morning everyone, let's get started.

2
00:00:05,300 --> 00:00:12,100
[Bob Smith] Thanks Alice. I wanted to discuss the timeline.
```

## File Organization

After running `./shepitnote full --diarize`, you'll have:

```
recordings/
├── meeting_20251005_143022.wav                    # Original audio
├── meeting_20251005_143022_speakers.json          # Raw diarization
├── meeting_20251005_143022.json                   # Raw transcription
├── meeting_20251005_143022_diarized.json          # Merged data
├── meeting_20251005_143022_speakers_labeled.json  # After labeling
├── meeting_20251005_143022.txt                    # Final transcript
└── meeting_20251005_143022_summary.md             # AI summary
```

## Commands Reference

### `./shepitnote diarize FILE [OPTIONS]`

Identify speakers in an audio file.

**Options:**
- `-s, --speakers NUM` - Expected number of speakers
- `--min-speakers NUM` - Minimum speakers (auto-detect)
- `--max-speakers NUM` - Maximum speakers (auto-detect)
- `--hf-token TOKEN` - HuggingFace API token

**Examples:**
```bash
# Auto-detect speakers
./shepitnote diarize meeting.wav

# Expect 3 speakers
./shepitnote diarize meeting.wav --speakers 3

# Detect 2-5 speakers
./shepitnote diarize meeting.wav --min-speakers 2 --max-speakers 5
```

### `./shepitnote label FILE`

Interactively label speakers with their names.

**Examples:**
```bash
./shepitnote label recordings/meeting_20251005_143022_diarized.json
```

### `./shepitnote apply-labels FILE [OPTIONS]`

Apply speaker labels to create final transcript.

**Options:**
- `-f, --format FORMAT` - Output format (txt, md, json, srt, vtt)
- `-o, --output FILE` - Output file path

**Examples:**
```bash
# Create text transcript
./shepitnote apply-labels meeting_speakers_labeled.json

# Create markdown
./shepitnote apply-labels meeting_speakers_labeled.json -f md

# Create SRT subtitles
./shepitnote apply-labels meeting_speakers_labeled.json -f srt
```

### `./shepitnote full --diarize [OPTIONS]`

Complete workflow with speaker diarization.

**Options:**
- `--diarize` - Enable speaker diarization
- `-s, --speakers NUM` - Number of speakers
- `-m, --model MODEL` - Whisper model (tiny, base, small, medium, large-v3)
- `-o, --ollama MODEL` - Ollama summarization model
- `-d, --duration SEC` - Recording duration

**Examples:**
```bash
# Full workflow with diarization
./shepitnote full --diarize --speakers 3 -m small -o mistral:7b

# Auto-detect speakers
./shepitnote full --diarize -m base

# 1-hour recording with diarization
./shepitnote full --diarize -d 3600 -m medium
```

## Performance

Diarization adds processing time:

| Task | Without Diarization | With Diarization |
|------|---------------------|------------------|
| 1 hour audio (CPU) | ~10-15 min | ~20-30 min |
| 1 hour audio (GPU) | ~3-5 min | ~8-12 min |

GPU acceleration recommended for faster processing:

```bash
# Install GPU support (NVIDIA/AMD)
./venv/bin/pip install torch torchvision torchaudio

# Diarization automatically uses GPU if available
```

## Future API Integration

The speaker label format is designed for future integration with meeting platforms:

### Planned: Zoom Integration

```bash
# Future feature (not yet implemented)
./shepitnote full --diarize --zoom-meeting-id 123456789

# Will automatically:
# - Fetch participant names from Zoom API
# - Match voices to participants
# - Label speakers automatically (no manual labeling needed)
```

### Planned: Teams Integration

```bash
# Future feature (not yet implemented)
./shepitnote full --diarize --teams-meeting-url "https://..."

# Will automatically label speakers from Teams participant list
```

### Speaker Label Format (Future-Ready)

The JSON format includes fields for API integration:

```json
{
  "labels": {
    "SPEAKER_00": {
      "name": "Alice Johnson",
      "email": "alice@company.com",    // Future: from Zoom/Teams
      "role": "Product Manager",       // Future: from meeting metadata
      "source": "zoom_api",             // Future: "zoom_api", "teams_api"
      "zoom_participant_id": "abc123"  // Future: platform-specific ID
    }
  }
}
```

## Troubleshooting

### "Error loading model" or "HuggingFace token required"

**Solution:**
1. Get a free HuggingFace account: https://huggingface.co/join
2. Accept pyannote conditions: https://huggingface.co/pyannote/speaker-diarization-community-1
3. Create access token: https://huggingface.co/settings/tokens
4. Set environment variable: `export HF_TOKEN="your_token"`

### "pyannote.audio not installed"

**Solution:**
```bash
./venv/bin/pip install pyannote.audio torch huggingface-hub
```

### Poor speaker separation

**Tips:**
- Use higher quality audio (good microphone)
- Reduce background noise
- Specify expected number of speakers with `--speakers`
- Try different speaker count ranges with `--min-speakers` and `--max-speakers`

### Speakers merged or split incorrectly

**Solution:**
- Adjust `--speakers` parameter
- For 2 people, use `--speakers 2` (don't let it auto-detect)
- For uncertain count, use `--min-speakers 2 --max-speakers 5`

### GPU out of memory

**Solution:**
```bash
# Use CPU instead
# (GPU is automatically used if available, no flag needed)
# To force CPU, you can uninstall GPU PyTorch or set device manually in code
```

## Privacy & Security

✅ **No Cloud Services** - All diarization happens locally
✅ **No Audio Upload** - Audio never leaves your machine
✅ **Local Model Cache** - Models stored at `~/.cache/huggingface/`
✅ **Offline Capable** - Works without internet after first model download
✅ **Open Source** - Fully auditable code

The HuggingFace token is only used to download models once. After that, everything runs offline.

## Technical Details

### How It Works

1. **Diarization (pyannote.audio)**
   - Analyzes audio waveform
   - Detects voice activity
   - Identifies speaker changes
   - Outputs segments: "SPEAKER_00 spoke from 0:05 to 0:12"

2. **Transcription (faster-whisper)**
   - Converts speech to text
   - Outputs segments with timestamps
   - Independent of speaker info

3. **Merging**
   - Matches transcription timestamps to speaker segments
   - Combines: "At 0:05, SPEAKER_00 said 'Hello'"

4. **Labeling**
   - Shows user sample quotes from each speaker
   - User identifies speakers by voice/content
   - Maps SPEAKER_00 → "Alice Johnson"

5. **Final Output**
   - Replaces speaker IDs with names
   - Formats as readable transcript

### Models Used

- **Diarization**: `pyannote/speaker-diarization-community-1` (pyannote.audio 4.x;
  override with `PYANNOTE_PIPELINE`)
  - Size: ~40MB (community-1 + segmentation-3.0), cached after first download
  - License: MIT

- **Transcription**: `faster-whisper` (OpenAI Whisper)
  - Models: tiny (75MB) to large-v3 (3GB)
  - See main README for Whisper details

## Contributing

Interested in improving diarization? Areas for contribution:

- Speaker voice profiling (remember voices across meetings)
- Real-time diarization for streaming
- Zoom/Teams API integration
- Improved speaker labeling UX
- Multi-language speaker detection

See [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/yuriytkach/shepitnote/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yuriytkach/shepitnote/discussions)

---

**ShepitNote** - Privacy-first meeting transcription with speaker diarization. 🤫
