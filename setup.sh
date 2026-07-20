#!/usr/bin/env bash
# ShepitNote environment setup.
#
# Creates the Python virtual environment (venv/) that the worker scripts run in
# and installs their dependencies (faster-whisper, huggingface-hub, requests).
# Idempotent — safe to re-run; an existing venv is reused.
#
# Usage:
#   ./setup.sh                          # create venv/ and install dependencies
#   ./setup.sh --model small            # ...and pre-download a Whisper model
#   ./setup.sh --diarize                # ...and install the CPU diarization stack
#   PYTHON_BIN=python3.12 ./setup.sh    # use a specific interpreter
#
# The optional --model step downloads a Whisper model once (large-v3 is ~3 GB) so
# your first real meeting doesn't pause to fetch it mid-run.
#
# The optional --diarize step installs pyannote.audio + a CPU build of torch so
# DUAL_REMOTE_DIARIZATION can split the Remote track into per-speaker labels
# (see docs/AUDIO.md). It deliberately uses CPU wheels — the default PyPI torch
# is a ~2.5 GB CUDA build this project doesn't need. GPU users should install the
# CUDA torch/torchcodec builds manually instead (see the 'gpu' extra in pyproject.toml).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="${SCRIPT_DIR}/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PREPULL_MODEL=""
INSTALL_DIARIZE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            PREPULL_MODEL="${2:-}"
            [ -z "$PREPULL_MODEL" ] && { echo "--model needs a value" >&2; exit 1; }
            shift 2
            ;;
        --diarize)
            INSTALL_DIARIZE=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./setup.sh [--model tiny|base|small|medium|large-v3] [--diarize]"
            echo ""
            echo "Creates venv/ and installs faster-whisper + requests (idempotent)."
            echo "With --model, also pre-downloads that Whisper model so the first"
            echo "real meeting doesn't pause to fetch it."
            echo "With --diarize, also installs the CPU diarization stack"
            echo "(pyannote.audio + CPU torch) for DUAL_REMOTE_DIARIZATION."
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

echo "==> Checking prerequisites"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "    ERROR: '$PYTHON_BIN' not found on PATH; python3 is required." >&2
    exit 1
fi
for bin in ffmpeg pactl; do
    command -v "$bin" >/dev/null 2>&1 \
        || echo "    WARNING: '$bin' not found on PATH (needed for recording)." >&2
done

if [ ! -x "${VENV}/bin/python3" ]; then
    echo "==> Creating virtual environment at ${VENV}"
    "$PYTHON_BIN" -m venv "$VENV"
else
    echo "==> Reusing existing virtual environment at ${VENV}"
fi

VPY="${VENV}/bin/python3"

echo "==> Upgrading pip"
"$VPY" -m pip install --upgrade pip >/dev/null

echo "==> Installing dependencies (faster-whisper, huggingface-hub, requests)"
"$VPY" -m pip install "faster-whisper>=1.0" huggingface-hub requests

echo "==> Verifying"
"$VPY" -c "import faster_whisper, requests; \
print('    faster-whisper', faster_whisper.__version__, '+ requests OK')"

if [ "$INSTALL_DIARIZE" = true ]; then
    CPU_INDEX="https://download.pytorch.org/whl/cpu"

    echo "==> Installing diarization stack (CPU build)"
    # CPU-only wheels on purpose: the default PyPI torch is a ~2.5 GB CUDA build
    # this project doesn't need. Install torch from the PyTorch CPU index first
    # so pyannote.audio resolves against it instead of pulling the CUDA torch.
    echo "    - torch + torchaudio (CPU)"
    "$VPY" -m pip install torch torchaudio --index-url "$CPU_INDEX"
    echo "    - pyannote.audio"
    "$VPY" -m pip install "pyannote.audio"

    # torchcodec on PyPI is CUDA-linked and fails to load on a CPU-only machine
    # (OSError: libnvrtc.so.*). pyannote.audio 4.x uses it for audio decoding, so
    # replace it with the CPU build from the PyTorch index. Skip if already CPU.
    # (Read the version into a var first: `grep -q` in a pipe would trip
    # pipefail via SIGPIPE and always look like a miss.)
    tc_version="$("$VPY" -m pip show torchcodec 2>/dev/null | grep -i '^version:' || true)"
    if [[ "$tc_version" != *cpu* ]]; then
        echo "    - torchcodec (CPU, replacing the CUDA-linked PyPI build)"
        "$VPY" -m pip install --force-reinstall --no-deps torchcodec --index-url "$CPU_INDEX"
    else
        echo "    - torchcodec already the CPU build, skipping"
    fi

    echo "==> Verifying diarization stack"
    "$VPY" -c "import torch, pyannote.audio; from pyannote.audio import Pipeline; \
print('    pyannote.audio', pyannote.audio.__version__, '| torch', torch.__version__, \
'| CUDA', torch.cuda.is_available())"
    echo "    Diarization ready. Enable it by setting HF_TOKEN and"
    echo "    DUAL_REMOTE_DIARIZATION=true in .shepitnoterc (see docs/AUDIO.md)."
fi

if [ -n "$PREPULL_MODEL" ]; then
    echo "==> Pre-downloading Whisper model '${PREPULL_MODEL}' (one-time)"
    "$VPY" - "$PREPULL_MODEL" <<'PY'
import sys
from faster_whisper import WhisperModel
size = sys.argv[1]
print(f"    fetching '{size}' from Hugging Face ...", flush=True)
WhisperModel(size, device="cpu", compute_type="int8")
print(f"    model '{size}' cached OK")
PY
fi

echo ""
echo "Setup complete. Quick end-to-end test (records 10s, small model):"
echo "  ./shepitnote full -d 10 -m small -o <your-ollama-model>   # see: ollama list"
