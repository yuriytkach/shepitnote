#!/bin/bash

# Audio recording script for meetings
# Records system audio and microphone to a WAV file

set -euo pipefail

# Check for dependencies
if ! command -v pactl &> /dev/null; then
    echo "Error: pactl not found. Install pulseaudio-utils or pipewire-pulse"
    exit 1
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "Error: ffmpeg not found. Install ffmpeg"
    exit 1
fi

# Configuration
OUTPUT_DIR="${RECORDINGS_DIR:-./recordings}"
DATE=$(date +%Y%m%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MEETING_DIR="${OUTPUT_DIR}/${DATE}/meeting_${TIMESTAMP}"
OUTPUT_FILE="${MEETING_DIR}/meeting_${TIMESTAMP}.wav"

# Parse arguments
DURATION=""
TITLE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--duration)
            DURATION="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -t|--title)
            TITLE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-d DURATION] [-o OUTPUT_FILE] [-t TITLE]"
            echo "  -d, --duration    Recording duration (e.g., 3600 for 1 hour)"
            echo "  -o, --output      Output file path (default: ./recordings/meeting_TIMESTAMP.wav)"
            echo "  -t, --title       Meeting title"
            echo ""
            echo "Environment variables:"
            echo "  RECORDINGS_DIR    Directory for recordings (default: ./recordings)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create output directory
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Determine audio source.
# AUDIO_SOURCE env var overrides everything.
# AUDIO_SOURCE_TYPE controls what to capture:
#   "microphone" (default) - default PulseAudio/PipeWire source (mic)
#   "monitor"              - monitor of default sink (captures output audio,
#                            needed for meeting audio on BT headsets)
#   "both"                 - mix microphone + sink monitor into one recording
#                            (captures both sides of a call)
#   "dual"                 - record two synchronized tracks: microphone -> voice
#                            (You) and sink monitor -> system (Remote), so
#                            local vs remote is known by track of origin
if [ -n "${AUDIO_SOURCE:-}" ]; then
    RECORD_SOURCE="$AUDIO_SOURCE"
    AUDIO_SOURCE_TYPE="microphone"  # treat explicit source as single source
elif [ "${AUDIO_SOURCE_TYPE:-microphone}" = "monitor" ]; then
    RECORD_SOURCE="$(pactl get-default-sink).monitor"
elif [ "${AUDIO_SOURCE_TYPE:-microphone}" = "both" ]; then
    RECORD_SOURCE=""  # handled separately below
elif [ "${AUDIO_SOURCE_TYPE:-microphone}" = "dual" ]; then
    RECORD_SOURCE=""  # handled separately below (two tracks)
else
    RECORD_SOURCE="$(pactl get-default-source)"
fi

echo "Recording audio..." >&2
echo "Output file: $OUTPUT_FILE" >&2
if [ -n "$RECORD_SOURCE" ]; then
    echo "Audio source: $RECORD_SOURCE" >&2
elif [ "${AUDIO_SOURCE_TYPE:-microphone}" = "dual" ]; then
    echo "Audio source: dual tracks (mic -> voice/You, monitor -> system/Remote)" >&2
else
    echo "Audio source: mic + output mix" >&2
fi
if [ -n "$DURATION" ]; then
    echo "Duration: ${DURATION}s" >&2
fi
echo "" >&2
echo "Press Ctrl+C to stop recording" >&2

# RECORD_BACKEND controls the recording tool:
#   "ffmpeg" (default) - ffmpeg with PulseAudio compat layer
#   "pw-record"        - pw-record, talks directly to PipeWire graph;
#                        required for BT headsets in HSP/HFP mode where
#                        ffmpeg -f pulse captures silence
RECORD_BACKEND="${RECORD_BACKEND:-ffmpeg}"

set +e
ffmpeg_exit_code=0

# Forward a WAV-finalizing signal to both dual recorders on Ctrl+C / TERM.
# At the TTY, Ctrl+C already reaches both children directly via the foreground
# process group; this trap additionally covers the duration/timeout path.
stop_dual() {
    [ -n "${voice_pid:-}" ] && kill -INT "$voice_pid" 2>/dev/null || true
    [ -n "${system_pid:-}" ] && kill -INT "$system_pid" 2>/dev/null || true
}

if [ "${AUDIO_SOURCE_TYPE:-microphone}" = "dual" ]; then
    # Record two independent, concurrently-started tracks:
    #   voice track  = default source (microphone)  -> You
    #   system track = default sink monitor          -> Remote
    # Sample-accurate cross-track sync is NOT required: the merge step orders
    # turns by each track's own timestamps and never cross-aligns samples, so
    # tens of ms of start skew between the two recorders is irrelevant.
    MIC_SOURCE="$(pactl get-default-source)"
    MONITOR_SOURCE="$(pactl get-default-sink).monitor"
    base="${OUTPUT_FILE%.wav}"
    VOICE_FILE="${base}.voice.wav"
    SYSTEM_FILE="${base}.system.wav"
    echo "Dual tracks: voice ($MIC_SOURCE) + system ($MONITOR_SOURCE)" >&2

    voice_pid=""
    system_pid=""
    trap 'stop_dual' INT TERM

    if [ "$RECORD_BACKEND" = "pw-record" ]; then
        PW_COMMON=(--rate 16000 --channels 1 --format s16)
        if [ -n "$DURATION" ]; then
            timeout "$DURATION" pw-record --target "$MIC_SOURCE" "${PW_COMMON[@]}" "$VOICE_FILE" >&2 &
            voice_pid=$!
            timeout "$DURATION" pw-record --target "$MONITOR_SOURCE" "${PW_COMMON[@]}" "$SYSTEM_FILE" >&2 &
            system_pid=$!
        else
            pw-record --target "$MIC_SOURCE" "${PW_COMMON[@]}" "$VOICE_FILE" >&2 &
            voice_pid=$!
            pw-record --target "$MONITOR_SOURCE" "${PW_COMMON[@]}" "$SYSTEM_FILE" >&2 &
            system_pid=$!
        fi
    else
        # ffmpeg backend. -nostdin is mandatory: without it the two concurrent
        # ffmpeg processes fight over the terminal stdin and hang.
        VOICE_ARGS=(-nostdin -f pulse -i "$MIC_SOURCE")
        [ -n "$DURATION" ] && VOICE_ARGS+=(-t "$DURATION")
        VOICE_ARGS+=(-ar 16000 -ac 1 -c:a pcm_s16le "$VOICE_FILE")
        ffmpeg "${VOICE_ARGS[@]}" >&2 &
        voice_pid=$!

        SYSTEM_ARGS=(-nostdin -f pulse -i "$MONITOR_SOURCE")
        [ -n "$DURATION" ] && SYSTEM_ARGS+=(-t "$DURATION")
        SYSTEM_ARGS+=(-ar 16000 -ac 1 -c:a pcm_s16le "$SYSTEM_FILE")
        ffmpeg "${SYSTEM_ARGS[@]}" >&2 &
        system_pid=$!
    fi

    # Reap both recorders. A trapped signal interrupts the first wait (return
    # >128); the while/kill -0 loop then re-waits until each child has actually
    # exited and flushed its WAV header.
    for _p in "$voice_pid" "$system_pid"; do
        while kill -0 "$_p" 2>/dev/null; do
            wait "$_p" 2>/dev/null || true
        done
    done

    trap - INT TERM
    ffmpeg_exit_code=0

elif [ "${AUDIO_SOURCE_TYPE:-microphone}" = "both" ]; then
    # Mix microphone and sink monitor into a single recording using ffmpeg.
    # Two inputs: the default source (mic) and the default sink monitor.
    MIC_SOURCE="$(pactl get-default-source)"
    MONITOR_SOURCE="$(pactl get-default-sink).monitor"
    echo "Mixing mic ($MIC_SOURCE) + monitor ($MONITOR_SOURCE)" >&2

    FFMPEG_ARGS=(
        -f pulse -i "$MIC_SOURCE"
        -f pulse -i "$MONITOR_SOURCE"
        -filter_complex amix=inputs=2:duration=longest
        -ar 16000 -ac 1 -c:a pcm_s16le
    )
    [ -n "$DURATION" ] && FFMPEG_ARGS+=(-t "$DURATION")
    FFMPEG_ARGS+=("$OUTPUT_FILE")

    ffmpeg "${FFMPEG_ARGS[@]}" >&2
    ffmpeg_exit_code=$?

elif [ "$RECORD_BACKEND" = "pw-record" ]; then
    PW_ARGS=(--target "$RECORD_SOURCE" --rate 16000 --channels 1 --format s16)
    if [ -n "$DURATION" ]; then
        timeout "$DURATION" pw-record "${PW_ARGS[@]}" "$OUTPUT_FILE" >&2
    else
        pw-record "${PW_ARGS[@]}" "$OUTPUT_FILE" >&2
    fi
    ffmpeg_exit_code=$?

else
    FFMPEG_ARGS=(-f pulse -i "$RECORD_SOURCE")
    [ -n "$DURATION" ] && FFMPEG_ARGS+=(-t "$DURATION")
    FFMPEG_ARGS+=(-ar 16000 -ac 1 -c:a pcm_s16le "$OUTPUT_FILE")

    ffmpeg "${FFMPEG_ARGS[@]}" >&2
    ffmpeg_exit_code=$?
fi

set -e

# Always output filename if file was created, even if interrupted
if [ "${AUDIO_SOURCE_TYPE:-microphone}" = "dual" ]; then
    # Dual mode writes two tracks; the canonical mixed OUTPUT_FILE is never
    # created. Verify both tracks exist before writing metadata.
    if [ ! -f "$VOICE_FILE" ] || [ ! -f "$SYSTEM_FILE" ]; then
        echo "" >&2
        echo "Error: Dual recording incomplete" >&2
        [ ! -f "$VOICE_FILE" ] && echo "  Missing voice track: $VOICE_FILE" >&2
        [ ! -f "$SYSTEM_FILE" ] && echo "  Missing system track: $SYSTEM_FILE" >&2
        exit 1
    fi

    echo "" >&2
    echo "Recording saved to two tracks:" >&2
    echo "  Voice (You):     $VOICE_FILE" >&2
    echo "  System (Remote): $SYSTEM_FILE" >&2

    # Prompt for title if not provided and a terminal is available
    if [ -z "$TITLE" ]; then
        if read -p "Meeting title (optional): " TITLE </dev/tty 2>/dev/null; then
            : # title captured
        else
            TITLE=""
        fi
    fi

    # Create metadata file, keyed to the canonical meeting base name.
    meeting_dir=$(dirname "$OUTPUT_FILE")
    base_name=$(basename "$OUTPUT_FILE" .wav)
    metadata_file="${meeting_dir}/${base_name}_metadata.json"

    # audio_file points at the voice track for compatibility with tools that
    # expect a single audio_file field.
    cat > "$metadata_file" << EOF
{
  "title": "${TITLE}",
  "timestamp": "${TIMESTAMP}",
  "date": "${DATE}",
  "mode": "dual",
  "audio_file": "$(basename "$VOICE_FILE")",
  "voice_file": "$(basename "$VOICE_FILE")",
  "system_file": "$(basename "$SYSTEM_FILE")",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source": "local_recording"
}
EOF

    if [ -n "$TITLE" ]; then
        echo "Title: $TITLE" >&2
    fi

    # Output the voice track path to stdout; the orchestrator resolves the
    # track pair from it via detect_dual_tracks.
    echo "$VOICE_FILE"

elif [ -f "$OUTPUT_FILE" ]; then
    echo "" >&2
    echo "Recording saved to: $OUTPUT_FILE" >&2

    # Prompt for title if not provided and a terminal is available
    if [ -z "$TITLE" ]; then
        if read -p "Meeting title (optional): " TITLE </dev/tty 2>/dev/null; then
            : # title captured
        else
            TITLE=""
        fi
    fi

    # Create metadata file
    meeting_dir=$(dirname "$OUTPUT_FILE")
    base_name=$(basename "$OUTPUT_FILE" .wav)
    metadata_file="${meeting_dir}/${base_name}_metadata.json"

    # Generate metadata JSON
    cat > "$metadata_file" << EOF
{
  "title": "${TITLE}",
  "timestamp": "${TIMESTAMP}",
  "date": "${DATE}",
  "audio_file": "$(basename "$OUTPUT_FILE")",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source": "local_recording"
}
EOF

    if [ -n "$TITLE" ]; then
        echo "Title: $TITLE" >&2
    fi

    # Output only the filename to stdout (for script capture)
    echo "$OUTPUT_FILE"
else
    echo "" >&2
    echo "Error: Recording file was not created" >&2
    exit 1
fi
