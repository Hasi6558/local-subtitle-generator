"""Explicit, pinned preparation of a portable local runtime and text weights."""

import hashlib
import json
import platform
import urllib.request
import zipfile

RUNTIME_TAG = "b12099"
RUNTIME_SHA = "ba751a91caeb8f5492c408386a46c9e0eba7da599c81bce1383260342e2b672b"
MODELS = {
    "qwen3-1.7b": {
        "repo": "Qwen/Qwen3-1.7B-GGUF",
        "revision": "90862c4b9d2787eaed51d12237eafdfe7c5f6077",
        "file": "Qwen3-1.7B-Q8_0.gguf",
        "sha256": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a",
        "quantization": "Q8_0",
        "bytes": 1834426016,
    },
    "qwen3-4b": {
        "repo": "Qwen/Qwen3-4B-GGUF",
        "revision": "bc640142c66e1fdd12af0bd68f40445458f3869b",
        "file": "Qwen3-4B-Q4_K_M.gguf",
        "sha256": "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
        "quantization": "Q4_K_M",
        "bytes": 2497280256,
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def paths(cache, model):
    if model not in MODELS:
        raise ValueError(f"Unknown text model; choose {', '.join(MODELS)}")
    return (
        cache / "text" / "runtime" / RUNTIME_TAG / "llama-server.exe",
        cache / "text" / model / MODELS[model]["file"],
    )


def prepare(cache, model, offline=False, notify=print):
    from huggingface_hub import hf_hub_download

    executable, weights = paths(cache, model)
    spec = MODELS[model]
    if not executable.is_file():
        if offline:
            raise ValueError(
                "Portable runtime missing; run local-subs text-models prepare first"
            )
        if platform.system() != "Windows" or platform.machine().lower() not in (
            "amd64",
            "x86_64",
        ):
            raise ValueError(
                "Automatic runtime preparation is currently Windows x64 only"
            )
        folder = executable.parent
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / "runtime.zip.part"
        notify(
            f"Explicit download: llama.cpp {RUNTIME_TAG}, Windows CPU runtime (25 MB)"
        )
        urllib.request.urlretrieve(
            f"https://github.com/ggml-org/llama.cpp/releases/download/{RUNTIME_TAG}/llama-{RUNTIME_TAG}-bin-win-cpu-x64.zip",
            archive,
        )
        if sha256(archive) != RUNTIME_SHA:
            raise ValueError(
                "Runtime archive checksum mismatch; no executable was installed"
            )
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                target = (folder / member.filename).resolve()
                if not target.is_relative_to(folder.resolve()):
                    raise ValueError("Unsafe runtime archive path")
            source.extractall(folder)
        archive.unlink()
        if not executable.exists():
            found = list(folder.rglob("llama-server.exe"))
            if len(found) != 1:
                raise ValueError("Runtime archive has no unambiguous llama-server.exe")
            executable = found[0]
    if not weights.is_file():
        if offline:
            raise ValueError(
                f"Text weights missing; run local-subs text-models prepare {model}"
            )
        notify(
            f"Explicit download: {spec['repo']}@{spec['revision']} ({spec['bytes'] / 1e9:.2f} GB)"
        )
        hf_hub_download(
            spec["repo"],
            spec["file"],
            revision=spec["revision"],
            local_dir=weights.parent,
        )
    if sha256(weights) != spec["sha256"]:
        raise ValueError("Text weights checksum mismatch; inference will not use them")
    metadata = spec | {
        "id": model,
        "license": "Apache-2.0",
        "runtime": RUNTIME_TAG,
        "runtime_archive_sha256": RUNTIME_SHA,
        "executable": str(executable.resolve()),
        "weights": str(weights.resolve()),
    }
    (weights.parent / "prepared.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def prepared(cache, model):
    executable, weights = paths(cache, model)
    metadata = weights.parent / "prepared.json"
    return executable.is_file() and weights.is_file() and metadata.is_file()
