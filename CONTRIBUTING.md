# Contributing to ShepitNote

Thank you for your interest in contributing to ShepitNote! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Respect differing viewpoints and experiences

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- **Clear title and description**
- **Steps to reproduce** the issue
- **Expected behavior** vs actual behavior
- **Environment details**: OS/distro, Python version, audio backend (PipeWire/PulseAudio), GPU (if any)
- **Logs or error messages** (run with `DEBUG=true` for detailed output)

### Suggesting Enhancements

Enhancement suggestions are welcome! Please:

- Use a clear and descriptive title
- Provide a detailed description of the proposed feature
- Explain why this enhancement would be useful
- Include examples of how it would work

### Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test thoroughly (see [Testing](#testing))
5. Commit with a clear message (`git commit -m 'feat: add amazing feature'` — see [Commit Messages](#commit-messages))
6. Push to your fork (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

ShepitNote is a bash orchestrator (`shepitnote`) that shells out to small Python workers running
in a local virtualenv (`venv/`). See [CLAUDE.md](CLAUDE.md) for the architecture and a file-by-file
map, and [docs/SETUP.md](docs/SETUP.md) for the full install guide.

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/shepitnote.git
cd shepitnote

# System dependencies (names vary by distro)
sudo apt install ffmpeg pipewire-pulse python3-venv      # Debian / Ubuntu / KDE neon
# Arch / CachyOS:  yay -S ffmpeg pipewire-pulse python

# Create venv/ and install the worker dependencies (faster-whisper,
# huggingface-hub, requests). Idempotent — safe to re-run.
./setup.sh
# Optional: pre-download a Whisper model, and install the CPU diarization stack
./setup.sh --model small --diarize

# A local summarization model in Ollama (any instruction-tuned model)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b
```

Python dependencies are declared in `pyproject.toml` (optional extras: `diarize`, `gpu`) and
installed by `./setup.sh`; there is **no** `requirements.txt`. The scripts are already executable
in the repo, so no `chmod` step is needed. Local config lives in `.shepitnoterc` (git-ignored);
copy the annotated template to start: `cp .shepitnoterc.example .shepitnoterc`.

## Testing

```bash
# Unit tests — pure logic only (no mic, Ollama, or network); fast.
venv/bin/python -m unittest discover -s tests

# Smoke-test the real pipeline end to end with tiny models (needs a mic + Ollama)
./shepitnote full -d 5 -m tiny -o llama3.2:1b

# Exercise individual steps
./shepitnote record -d 2
./shepitnote transcribe recordings/<date>/meeting_<ts>/meeting_<ts>.wav -m tiny
./shepitnote summarize recordings/<date>/meeting_<ts>/meeting_<ts>.txt -o llama3.2:1b

# Verbose output for any command
DEBUG=true ./shepitnote full -d 5 -m tiny
```

The unit tests import the modules directly and cover the pure, side-effect-free logic
(`glossary.py`, `meeting_ui.py`, the publishers, track merging, language normalization). When you
add or change such logic, add or update a test in `tests/`. Keep network/mic/Ollama code thin so
the testable core stays pure. Recordings are organized as
`recordings/<YYYYMMDD>/meeting_<YYYYMMDD_HHMMSS>/`.

## Code Style

### Bash scripts
- Use `set -euo pipefail` at the top
- Meaningful names (UPPER_CASE for config/constants, lower_case for locals)
- Comment non-obvious logic
- Log messages go to **stderr** (`>&2`); only real result data goes to **stdout**
- Use functions for reusable code

### Python workers
- Follow PEP 8; use type hints where they help
- Docstrings for modules and non-trivial functions
- Handle errors gracefully with clear messages
- **Data to stdout, status/errors to stderr** — bash captures a worker's stdout as its result
- Keep pure logic importable and dependency-light so it stays unit-testable

### General
- Keep lines under 100 characters when practical
- 4-space indentation (Python and bash)
- Update documentation when you change behavior

## Project Structure

```
shepitnote/
├── shepitnote                 # Main CLI / orchestrator (bash): commands, config, guided flow
├── record_audio.sh            # Audio capture (ffmpeg / pw-record; mic/monitor/both/dual)
├── compress.sh                # WAV → MP3
├── setup.sh                   # Create venv/ and install worker deps (--model, --diarize)
├── transcribe.py              # Transcription (faster-whisper)
├── cloud_transcribe.py        # Optional cloud transcription (OpenAI-compatible; Groq preset)
├── summarize.py               # Summarization (Ollama)
├── glossary.py                # Per-language tech-term normalization (pure, stdlib-only)
├── diarize.py                 # Speaker diarization (pyannote.audio 4.x)
├── merge_tracks.py            # Interleave dual You/Remote tracks
├── merge_diarization.py       # Merge single-track diarization + transcript
├── label.py, apply_labels.py  # Interactive speaker labeling → final transcript
├── meeting_ui.py              # Pure helpers for the guided `meeting` flow
├── hooks/                     # Post-summary publishers (publish.py, confluence_publish.py, slack_publish.py)
├── tests/                     # Unit tests (unittest)
├── docs/                      # Topic guides: SETUP, AUDIO, LANGUAGE, DIARIZATION, PUBLISHING, CLOUD
├── pyproject.toml             # Package metadata + Python deps (extras: diarize, gpu)
├── .shepitnoterc.example      # Annotated config template (copy → .shepitnoterc, git-ignored)
├── CLAUDE.md                  # Developer map / architecture notes
├── README.md, CONTRIBUTING.md, LICENSE
└── recordings/                # Output (git-ignored): recordings/<date>/meeting_<ts>/
```

For the full file-by-file map, the data flow, and where to change things, see **[CLAUDE.md](CLAUDE.md)**.

## Roadmap & Ideas

Planned work and open ideas live in the [Issues](https://github.com/yuriytkach/shepitnote/issues)
tracker. If you'd like to work on something, open or comment on an issue first so we can align on
the approach before you invest time.

## Commit Messages

This repo uses [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short summary

Longer body explaining the *why* of the change, wrapped at ~72 characters.
Closes #123
```

- **Types:** `feat`, `fix`, `docs`, `refactor`, `chore`, `test`
- **Scope** is optional but encouraged (the affected area)
- Reference issues with `Closes #123` / `Fixes #456`

Examples from the history: `feat(diarize): add --no-diarize flag per run`,
`fix(meeting): stop guided flow hanging after a successful run`, `docs: restructure into a lean
README + topical docs/ guides`.

## Updating Documentation

When you change behavior:

- Update `README.md` and the relevant guide in `docs/`
- Update the `--help` text in `shepitnote` (`print_usage`) and document any new option in `.shepitnoterc.example`
- Add or update unit tests in `tests/` for any pure logic you touch

## Questions?

- Open a [Discussion](https://github.com/yuriytkach/shepitnote/discussions)
- Check existing [Issues](https://github.com/yuriytkach/shepitnote/issues)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to ShepitNote! 🎙️
