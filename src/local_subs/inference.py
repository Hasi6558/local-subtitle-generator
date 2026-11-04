"""Offline model loading and bounded, speech-aware language resolution."""

import hashlib
import json

from local_subs.media import milliseconds

POLICY = "speech-windows-v1"


class LanguageResolutionError(ValueError):
    def __init__(self, diagnostics):
        super().__init__(
            "No confident language detected after bounded speech sampling; rerun with --source-language CODE"
        )
        self.diagnostics = diagnostics


def load_model(settings, notify):
    import ctranslate2
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    try:
        path = download_model(
            settings.speech_model,
            cache_dir=str(settings.model_cache),
            local_files_only=True,
        )
    except Exception as exc:
        raise ValueError(
            f'Model is not cached. Run local-subs models download {settings.speech_model} --model-cache "{settings.model_cache}" first. {exc}'
        ) from exc
    from pathlib import Path

    path = Path(path)
    for required in ("model.bin", "config.json", "tokenizer.json"):
        if not (path / required).is_file():
            raise ValueError(
                f"Cached model missing {required}; explicitly download the model again"
            )
    device = settings.device
    if device == "auto":
        try:
            device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
        except RuntimeError:
            device = "cpu"
        notify(f"Auto device selected {device}")
    compute = settings.compute_type

    def create(device):
        types = ctranslate2.get_supported_compute_types(device)
        chosen = compute or ("int8" if device == "cpu" else "float16")
        if chosen not in types:
            if compute:
                raise ValueError(
                    f"{chosen} unsupported on {device}; supported: {sorted(types)}"
                )
            chosen = "float32"
        notify(
            f"Loading cached {settings.speech_model} on {device}/{chosen}; no download"
        )
        return WhisperModel(
            str(path), device=device, compute_type=chosen, local_files_only=True
        ), chosen

    try:
        model, chosen = create(device)
    except RuntimeError as exc:
        if settings.device != "auto" or device == "cpu" or compute:
            raise ValueError(
                f"Model load failed on {device}: {exc}. Check CUDA/cuDNN DLLs or explicitly use --device cpu"
            ) from exc
        notify(f"CUDA loading failed ({exc}); auto mode falling back to CPU")
        device = "cpu"
        model, chosen = create(device)
    return model, {
        "device": device,
        "compute_type": chosen,
        "model_path": str(path),
        "model_revision": path.name,
    }


def resolve_language(model, audio, settings, offset_ms, speech, cached=None):
    if settings.source_language != "auto":
        language = settings.source_language
        diagnostics = {"policy": "explicit", "samples": []}
    elif cached:
        language, diagnostics = cached["language"], cached["diagnostics"]
    else:
        diagnostics = {
            "policy": POLICY,
            "threshold": settings.detection_threshold,
            "samples": [],
        }
        language = None
        # Each pass uses an original contiguous window, not stitched speech.
        starts = []
        for region in speech:
            position = region["start"]
            while (
                position < region["end"] and len(starts) < settings.detection_attempts
            ):
                if not starts or position >= starts[-1] + 30 * 16000:
                    starts.append(position)
                position += 30 * 16000
            if len(starts) == settings.detection_attempts:
                break
        for start in starts:
            end = min(start + 30 * 16000, len(audio))
            code, score, scores = model.detect_language(
                audio=audio[start:end], vad_filter=False
            )
            diagnostics["samples"].append(
                {
                    "start_ms": offset_ms + milliseconds(start / 16000),
                    "end_ms": offset_ms + milliseconds(end / 16000),
                    "language": code,
                    "score": score,
                    "scores": scores,
                }
            )
            if score >= settings.detection_threshold:
                language = code
                break
        if language is None:
            raise LanguageResolutionError(diagnostics)
    if language not in model.supported_languages or (
        language == "yue" and settings.speech_model != "large-v3"
    ):
        raise ValueError(f"Language {language} is unsupported by selected model")
    return language, diagnostics


def cache_key(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()
