#!/usr/bin/env python3

"""
Transcription script using faster-whisper
Transcribes audio files to text with timestamps
"""

import argparse
import json
import os
import sys
from pathlib import Path

# libcublas is bundled with Ollama on some systems and not on the system path
_CUDA_LIBS = os.environ.get("CUDA_LIBS", "")
if _CUDA_LIBS and _CUDA_LIBS not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.environ["LD_LIBRARY_PATH"] = _CUDA_LIBS + ":" + os.environ.get("LD_LIBRARY_PATH", "")

try:
    from faster_whisper import WhisperModel
except ImportError:
    # Deferred so the module stays importable (e.g. for unit tests / helper
    # reuse) even when faster-whisper is not installed. The CLI still errors
    # clearly at model-load time (see _load_model).
    WhisperModel = None


def _unload_ollama():
    """Unload Ollama models to free VRAM. Only called when UNLOAD_OLLAMA=1."""
    import urllib.request
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        req = urllib.request.Request(f"{url}/api/ps")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        for m in data.get("models", []):
            payload = json.dumps({"model": m["name"], "keep_alive": 0}).encode()
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{url}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=10,
            )
            print(f"Unloaded Ollama model: {m['name']}", file=sys.stderr)
    except Exception:
        pass


def _normalize_language(language):
    """Normalize a language code to a faster-whisper value or None (auto-detect).

    None, empty/whitespace-only, and "auto" (case-insensitive) all mean
    auto-detect and collapse to None, so no language is passed to
    faster-whisper. Any other code is returned stripped and lowercased
    (uk, ru, en, nl, ...) — faster-whisper codes are lowercase ISO codes, so
    this makes -l EN / WHISPER_LANGUAGE=UK just work — letting faster-whisper
    validate it and raise a clear error on a genuine typo.
    """
    if language is None:
        return None
    language = language.strip()
    if not language:
        return None
    if language.lower() == "auto":
        return None
    return language.lower()


def _build_transcribe_kwargs(language=None, initial_prompt=None, hotwords=None, beam_size=5,
                             vad_filter=None, condition_on_previous_text=None,
                             hallucination_silence_threshold=None):
    """Build the keyword arguments for WhisperModel.transcribe().

    Kept as a pure, faster-whisper-free helper so the decoding-bias logic can be
    unit-tested without the model installed.

    - beam_size is always present (preserves today's exact default call).
    - language is added only when non-empty (after stripping).
    - initial_prompt is added only when non-empty (after stripping).
    - hotwords is added only when non-empty AND initial_prompt is empty.

    faster-whisper applies hotwords only when initial_prompt is falsy, so
    dropping hotwords when initial_prompt is set makes behavior deterministic and
    documented: initial_prompt takes precedence. Empty/whitespace-only values are
    treated as absent, so an all-empty call reproduces the pre-#8 kwargs exactly.

    Anti-hallucination controls (vad_filter, condition_on_previous_text,
    hallucination_silence_threshold) address a distinct failure: on near-silent
    stretches — e.g. one dual-track mic while the other side is talking — Whisper
    invents repeated tokens ("shepard shepard ...", "Спасибо. Спасибо. ...") and
    even foreign-script text. VAD skips the non-speech regions; turning off
    condition_on_previous_text breaks the repetition loops. Each is added to the
    kwargs ONLY when its argument is not None, so the all-None call still
    reproduces the historical kwargs exactly (the caller supplies the live
    defaults). hallucination_silence_threshold requires word-level timestamps in
    faster-whisper, so it implicitly enables word_timestamps.
    """
    kwargs = {"beam_size": beam_size}
    if language and language.strip():
        kwargs["language"] = language.strip()
    prompt = initial_prompt.strip() if initial_prompt else ""
    words = hotwords.strip() if hotwords else ""
    if prompt:
        kwargs["initial_prompt"] = prompt
    elif words:
        kwargs["hotwords"] = words
    if vad_filter is not None:
        kwargs["vad_filter"] = bool(vad_filter)
    if condition_on_previous_text is not None:
        kwargs["condition_on_previous_text"] = bool(condition_on_previous_text)
    if hallucination_silence_threshold is not None:
        kwargs["hallucination_silence_threshold"] = float(hallucination_silence_threshold)
        kwargs["word_timestamps"] = True
    return kwargs


def _model_is_cached(model_size: str) -> bool:
    """Best-effort check whether a Whisper model is already available locally.

    Used only to tailor the load message (download-first vs. already-cached), so a
    wrong guess is cosmetic. A local directory/path is obviously present; the
    standard size names map to the `Systran/faster-whisper-<size>` Hugging Face
    repo, cached under HF_HOME (or ~/.cache/huggingface)/hub.
    """
    try:
        if Path(model_size).exists():
            return True
        hf_home = os.environ.get("HF_HOME")
        cache_root = Path(hf_home) if hf_home else Path.home() / ".cache" / "huggingface"
        repo_dir = cache_root / "hub" / f"models--Systran--faster-whisper-{model_size}"
        return repo_dir.is_dir()
    except OSError:
        return False


def transcribe_audio(
    audio_file: str,
    model_size: str = "large-v3",
    device: str = "auto",
    language: str = None,
    output_format: str = "txt",
    initial_prompt: str = None,
    hotwords: str = None,
    cpu_threads: int = 0,
    vad_filter: bool = True,
    condition_on_previous_text: bool = False,
    hallucination_silence_threshold: float = None
) -> dict:
    """
    Transcribe an audio file using faster-whisper

    Args:
        audio_file: Path to audio file
        model_size: Whisper model size (tiny, base, small, medium, large-v3)
        device: Device to use (cpu, cuda, auto)
        language: Language code (None for auto-detect)
        output_format: Output format (txt, json, srt, vtt)
        initial_prompt: Optional text to bias decoding toward correct spellings
            of product/tech terms (str or None). Passed straight to
            faster-whisper; takes precedence over hotwords.
        hotwords: Optional space-separated terms to bias decoding (str or None).
            Only applied when initial_prompt is empty (faster-whisper ignores
            hotwords when initial_prompt is set).
        vad_filter: Skip non-speech regions with VAD before decoding (default
            True). Prevents Whisper from hallucinating text on silent stretches.
        condition_on_previous_text: Feed the previous window's text as context
            (default False). Left off to prevent repetition loops.
        hallucination_silence_threshold: If set (seconds), skip long silent gaps
            where hallucinations occur. Enables word timestamps and is slower, so
            it is off (None) by default.

    Returns:
        dict with transcription results
    """
    # Fail fast on the missing hard dependency, before any side effects
    # (e.g. _unload_ollama stopping the user's running model).
    if WhisperModel is None:
        print("Error: faster-whisper not installed", file=sys.stderr)
        print("Install with: pip install faster-whisper", file=sys.stderr)
        sys.exit(1)

    # Collapse None/empty/"auto" (case-insensitive) to auto-detect. This is the
    # single choke point every transcription path funnels through, so no
    # bash-side "auto" handling is needed.
    language = _normalize_language(language)

    if os.environ.get("UNLOAD_OLLAMA") == "1":
        _unload_ollama()

    # Determine device
    if device == "auto":
        device = "cuda"

    # int8_float16 uses ~half the VRAM of float16 with negligible quality loss.
    # Fall back to int8 on CPU if CUDA is not available.
    compute_type = "int8_float16" if device == "cuda" else "int8"

    def _load_model(dev, ctype):
        if _model_is_cached(model_size):
            print(f"Loading Whisper model '{model_size}' on {dev} ({ctype})...",
                  file=sys.stderr)
        else:
            # First use of this model: faster-whisper downloads it from Hugging
            # Face. That step is network-bound (low CPU) and, without this notice,
            # looks like a hang. huggingface_hub prints its own progress below.
            print(f"Downloading + loading Whisper model '{model_size}' on {dev} "
                  f"({ctype})...", file=sys.stderr)
            print("  First run for this model — fetching it from Hugging Face. "
                  "This can take a few minutes (large-v3 is ~3 GB); progress "
                  "appears below.", file=sys.stderr)
        sys.stderr.flush()
        # cpu_threads=0 lets CTranslate2 pick its default; a positive value caps
        # the CPU thread pool so other apps keep some cores (ignored on CUDA).
        return WhisperModel(model_size, device=dev, compute_type=ctype,
                            cpu_threads=cpu_threads)

    def _run_transcription(mdl):
        kwargs = _build_transcribe_kwargs(
            language, initial_prompt, hotwords,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
            hallucination_silence_threshold=hallucination_silence_threshold,
        )
        segments, info = mdl.transcribe(str(audio_file), **kwargs)
        print(f"Detected language: {info.language}", file=sys.stderr)
        result_segments = []
        for segment in segments:
            result_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            })
        return info, result_segments

    try:
        model = _load_model(device, compute_type)
    except RuntimeError as e:
        if "out of memory" in str(e).lower() or "CUDA" in str(e):
            print("GPU unavailable or out of memory during model load, using CPU", file=sys.stderr)
            device = "cpu"
            model = _load_model("cpu", "int8")
        else:
            raise

    print(f"Transcribing: {audio_file}", file=sys.stderr)
    try:
        info, all_segments = _run_transcription(model)
    except RuntimeError as e:
        if "out of memory" in str(e).lower() or "CUDA" in str(e):
            print("GPU unavailable or out of memory during transcription, using CPU", file=sys.stderr)
            del model
            model = _load_model("cpu", "int8")
            info, all_segments = _run_transcription(model)
        else:
            raise

    return {
        "language": info.language,
        "segments": all_segments,
        "text": " ".join(s["text"] for s in all_segments)
    }


def format_timestamp(seconds: float) -> str:
    """Format seconds to SRT timestamp format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def save_transcription(result: dict, output_file: str, format: str):
    """Save transcription in specified format"""
    output_path = Path(output_file)

    if format == "txt":
        output_path.write_text(result["text"])

    elif format == "json":
        output_path.write_text(json.dumps(result, indent=2))

    elif format == "srt":
        lines = []
        for i, seg in enumerate(result["segments"], 1):
            lines.append(str(i))
            lines.append(f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}")
            lines.append(seg["text"])
            lines.append("")
        output_path.write_text("\n".join(lines))

    elif format == "vtt":
        lines = ["WEBVTT", ""]
        for seg in result["segments"]:
            lines.append(f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}")
            lines.append(seg["text"])
            lines.append("")
        output_path.write_text("\n".join(lines))

    print(f"Transcription saved to: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio using faster-whisper")
    parser.add_argument("audio_file", help="Path to audio file")
    parser.add_argument("-m", "--model", default="large-v3",
                       choices=["tiny", "base", "small", "medium", "large-v3"],
                       help="Whisper model size (default: large-v3)")
    parser.add_argument("-d", "--device", default="auto",
                       choices=["cpu", "cuda", "auto"],
                       help="Device to use (default: auto)")
    parser.add_argument("-l", "--language", default=None,
                       help="Language code (default: auto-detect)")
    parser.add_argument("--initial-prompt", default=None,
                       help="Text to bias decoding toward correct spellings of "
                            "product/tech terms (takes precedence over --hotwords)")
    parser.add_argument("--hotwords", default=None,
                       help="Space-separated terms to bias decoding (applied only "
                            "when --initial-prompt is not set)")
    parser.add_argument("--vad", dest="vad", action=argparse.BooleanOptionalAction,
                       default=None,
                       help="Filter non-speech with VAD before decoding "
                            "(default on; --no-vad to disable). Removes text "
                            "hallucinated on silent stretches. Env: WHISPER_VAD")
    parser.add_argument("--condition-on-previous", dest="condition_on_previous",
                       action=argparse.BooleanOptionalAction, default=None,
                       help="Condition each window on the previous window's text "
                            "(default off; off prevents repetition loops). "
                            "Env: WHISPER_CONDITION_ON_PREVIOUS_TEXT")
    parser.add_argument("--hallucination-silence-threshold", type=float, default=None,
                       help="Skip silent gaps longer than N seconds where "
                            "hallucinations occur (enables word timestamps; "
                            "slower). Default: disabled. "
                            "Env: WHISPER_HALLUCINATION_SILENCE")
    parser.add_argument("-f", "--format", default="txt",
                       choices=["txt", "json", "srt", "vtt"],
                       help="Output format (default: txt)")
    parser.add_argument("-o", "--output",
                       help="Output file (default: audio_file.txt)")

    args = parser.parse_args()

    # Check if audio file exists
    if not Path(args.audio_file).exists():
        print(f"Error: Audio file not found: {args.audio_file}", file=sys.stderr)
        sys.exit(1)

    # Determine output file
    if args.output:
        output_file = args.output
    else:
        audio_path = Path(args.audio_file)
        output_file = audio_path.with_suffix(f".{args.format}")

    # CPU thread cap (0 = library default). Set by shepitnote so transcription
    # leaves cores free; a bad value falls back to the default rather than erroring.
    try:
        cpu_threads = int(os.getenv("CPU_THREADS") or 0)
    except ValueError:
        cpu_threads = 0

    # Anti-hallucination controls. A CLI flag wins; otherwise fall back to the
    # env var (exported from .shepitnoterc); otherwise the safe default (VAD on,
    # conditioning off, silence-threshold disabled).
    def _env_bool(name, default):
        v = os.getenv(name)
        if v is None or not v.strip():
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")

    vad_filter = args.vad if args.vad is not None else _env_bool("WHISPER_VAD", True)
    condition_on_previous_text = (
        args.condition_on_previous if args.condition_on_previous is not None
        else _env_bool("WHISPER_CONDITION_ON_PREVIOUS_TEXT", False)
    )
    hallucination_silence_threshold = args.hallucination_silence_threshold
    if hallucination_silence_threshold is None:
        env_hst = os.getenv("WHISPER_HALLUCINATION_SILENCE")
        if env_hst and env_hst.strip():
            try:
                hallucination_silence_threshold = float(env_hst)
            except ValueError:
                hallucination_silence_threshold = None

    # Cloud transcription (opt-in): when CLOUD_TRANSCRIBE is on AND a key is
    # configured, route to an OpenAI-compatible provider (Groq by default)
    # instead of local faster-whisper. Both env vars are exported by shepitnote
    # when cloud mode is enabled. Any failure — or a missing key — falls back to
    # local Whisper, so a meeting is never lost to a transient cloud hiccup.
    result = None
    if _env_bool("CLOUD_TRANSCRIBE", False):
        api_key = (os.getenv("CLOUD_TRANSCRIBE_API_KEY") or "").strip()
        if api_key:
            try:
                import cloud_transcribe
                print("Cloud transcription enabled — uploading audio to the "
                      "configured provider.", file=sys.stderr)
                result = cloud_transcribe.transcribe_via_api(
                    args.audio_file,
                    language=args.language,
                    base_url=os.getenv("CLOUD_TRANSCRIBE_BASE_URL",
                                       cloud_transcribe.DEFAULT_BASE_URL),
                    api_key=api_key,
                    model=os.getenv("CLOUD_TRANSCRIBE_MODEL",
                                    cloud_transcribe.DEFAULT_MODEL),
                    prompt=args.initial_prompt or args.hotwords or None,
                )
            except Exception as e:
                print(f"Cloud transcription failed ({e}); falling back to "
                      "local Whisper.", file=sys.stderr)
                result = None
        else:
            print("Cloud transcription requested but no CLOUD_TRANSCRIBE_API_KEY "
                  "/ GROQ_API_KEY is set — using local Whisper.", file=sys.stderr)

    # Transcribe (local faster-whisper) unless the cloud path already produced a
    # result above.
    try:
        if result is None:
            result = transcribe_audio(
                args.audio_file,
                model_size=args.model,
                device=args.device,
                language=args.language,
                output_format=args.format,
                initial_prompt=args.initial_prompt,
                hotwords=args.hotwords,
                cpu_threads=cpu_threads,
                vad_filter=vad_filter,
                condition_on_previous_text=condition_on_previous_text,
                hallucination_silence_threshold=hallucination_silence_threshold
            )

        # Save results
        save_transcription(result, output_file, args.format)

        # Print summary
        print(f"\nTranscription complete!", file=sys.stderr)
        print(f"Segments: {len(result['segments'])}", file=sys.stderr)

    except Exception as e:
        print(f"Error during transcription: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
