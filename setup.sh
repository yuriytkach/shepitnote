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
#   PYTHON_BIN=python3.12 ./setup.sh    # use a specific interpreter
#
# The optional --model step downloads a Whisper model once (large-v3 is ~3 GB) so
# your first real meeting doesn't pause to fetch it mid-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="${SCRIPT_DIR}/venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PREPULL_MODEL=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            PREPULL_MODEL="${2:-}"
            [ -z "$PREPULL_MODEL" ] && { echo "--model needs a value" >&2; exit 1; }
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./setup.sh [--model tiny|base|small|medium|large-v3]"
            echo ""
            echo "Creates venv/ and installs faster-whisper + requests (idempotent)."
            echo "With --model, also pre-downloads that Whisper model so the first"
            echo "real meeting doesn't pause to fetch it."
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
