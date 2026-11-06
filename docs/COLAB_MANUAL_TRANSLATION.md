# Export audio locally and test Whisper Large v1 in Google Colab

This is a manual, independent test. The local app extracts audio and gives you
downloadable files. You choose what to upload in Colab, create the notebook cells
yourself, run Whisper there, and download the English SRT. No Google account,
Drive connection, cloud worker or automatic upload is added to this project.

Start with a **3-minute Japanese sample**, then try a full video after checking
the subtitles. GPU output may differ from the laptop's CPU/int8 output even when
the model and beam size match. Translation quality still needs listening review.

## 1. Export the audio on your laptop

Restart your local server after updating the app, then refresh the browser.

1. Open **New subtitles** and click **Choose video…**.
2. Select the correct **Audio track**. With several tracks, choose the Japanese
   dialogue track rather than commentary, an English dub or audio description.
3. In **Optional sample**, use Start time `0` and Duration `180` for your first
   test. For the whole video, leave Duration blank and Start time at `0`.
4. Under **Export audio only**, leave the format at **FLAC** and click
   **Extract audio only**. A prepared Whisper model is not required.
5. Click **Download audio + timing ZIP** and save `audio-export.zip`.

The ZIP contains `audio.flac` (or `audio.wav`) and `audio_export.json`. Both export
formats contain 16 kHz, mono speech audio. FLAC compresses that audio losslessly;
WAV is uncompressed. Stereo/multichannel source audio is downmixed and resampled
for recognition. No VAD silence removal is applied during extraction; delayed
audio starts remain padded so the movie timeline is preserved.

Keep the JSON with the audio. A sample exported from ten minutes into a movie
starts at zero in its audio file; `timeline_offset_ms` tells the notebook to add
ten minutes back to every subtitle timestamp. The code below handles this.

Optional PowerShell alternative, from the project folder:

```powershell
.venv\Scripts\local-subs.exe inspect "D:\Movies\video.mkv"
.venv\Scripts\local-subs.exe extract-audio "D:\Movies\video.mkv" --audio-stream 1 --start 0 --duration 180 --audio-format flac --output-dir outputs/audio-exports
```

`--audio-stream` is the **global ffprobe stream index** printed by `inspect`.
Omit it only when there is one audio track. The command prints the output paths.
Use `--audio-format wav` for WAV. Omit `--duration` for the remaining video.
Each export gets a separate folder; previous files and the original video remain.

## 2. Create your own GPU notebook

1. Open [Google Colab](https://colab.research.google.com/), sign in, and choose
   **New notebook**. Give it a name such as `Japanese_Large_v1_Test`.
2. Open **Runtime → Change runtime type**, select an available **GPU**, and save.
   A T4 is suitable for an initial test if offered. GPU availability is not
   guaranteed, and free sessions have usage/runtime limits.
3. Add one **code cell** for each numbered cell below. Paste only the code inside
   its Python block, then run the cells in order using the play buttons.

This notebook uses Colab's hosted GPU. Connecting Colab to a **local runtime**
would use your laptop instead. Uploading the ZIP sends its audio and metadata to
Google; it does not upload the original video. The metadata includes the source
filename, selected stream and timing, but no full local path or account token.

### Cell 1 — Install the inference packages

```python
import os
import subprocess
import sys

assert sys.version_info >= (3, 11), "Use a Colab runtime with Python 3.11 or newer"
os.environ["HF_HUB_DISABLE_XET"] = "1"
subprocess.check_call([
    sys.executable, "-m", "pip", "install", "-q",
    "faster-whisper==1.2.1", "ctranslate2==4.8.5", "srt==3.5.3",
])
print("Packages installed. If Colab requests a session restart, restart and continue from Cell 2.")
```

These versions match the project's speech engine. The Windows `requirements.lock`
is not used here. Installing CUDA-dependent packages alone does not allocate a
GPU; the runtime selection in step 2 is required.

### Cell 2 — Verify that a GPU is available

```python
import os
import subprocess
from importlib.metadata import version

os.environ["HF_HUB_DISABLE_XET"] = "1"
subprocess.run(["nvidia-smi"], check=True)
import ctranslate2

assert ctranslate2.get_cuda_device_count() > 0, "No CUDA GPU. Change runtime type to GPU."
print("GPU compute types:", sorted(ctranslate2.get_supported_compute_types("cuda")))
print("faster-whisper:", version("faster-whisper"))
print("ctranslate2:", version("ctranslate2"))
```

If this fails, fix the GPU environment before proceeding. This example does not
silently fall back to CPU.

### Cell 3 — Manually upload the exported ZIP

Run this cell and select **one** `audio-export.zip` downloaded from the app.
The file picker here uploads from your laptop to the Colab session. For full
movies, this may take time and temporarily use browser/notebook memory; start
with the small sample. You can also upload the ZIP through Colab's Files panel
and replace `files.upload()` with a path to that ZIP yourself.

```python
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4
from google.colab import files

uploaded = files.upload()
assert len(uploaded) == 1, "Choose exactly one audio-export.zip"
ZIP_PATH = Path(next(iter(uploaded)))
del uploaded  # Release the upload dictionary's copy of the ZIP bytes.
INPUT_DIR = Path("/content") / ("audio-test-" + uuid4().hex[:8])
INPUT_DIR.mkdir()

with zipfile.ZipFile(ZIP_PATH) as archive:
    names = archive.namelist()
    assert len(names) == 2 and "audio_export.json" in names, "Use the ZIP exported by the app"
    assert archive.getinfo("audio_export.json").file_size < 100_000, "Unexpected metadata size"
    metadata = json.loads(archive.read("audio_export.json"))
    assert metadata["schema_version"] == 1
    assert metadata["audio_file"] in ("audio.flac", "audio.wav")
    assert set(names) == {metadata["audio_file"], "audio_export.json"}
    AUDIO_PATH = INPUT_DIR / metadata["audio_file"]
    with archive.open(metadata["audio_file"]) as source, AUDIO_PATH.open("wb") as target:
        shutil.copyfileobj(source, target)

with AUDIO_PATH.open("rb") as handle:
    assert hashlib.file_digest(handle, "sha256").hexdigest() == metadata["audio_sha256"], "Audio checksum mismatch"
assert type(metadata["timeline_offset_ms"]) is int and metadata["timeline_offset_ms"] >= 0
assert type(metadata["audio_duration_ms"]) is int and metadata["audio_duration_ms"] > 0
assert metadata["sample_rate"] == 16000 and metadata["channels"] == 1
OFFSET_MS = metadata["timeline_offset_ms"]
print("Audio:", AUDIO_PATH.name)
print("Duration in seconds:", metadata["audio_duration_ms"] / 1000)
print("Original movie offset in seconds:", OFFSET_MS / 1000)
```

### Cell 4 — Load Whisper Large v1 on the GPU

```python
from faster_whisper import WhisperModel

MODEL_NAME = "large-v1"
MODEL_REVISION = "b07c8d4be0be90092aa01a29c975077acb8d15c9"
SOURCE_LANGUAGE = "ja"
BEAM_SIZE = 5
COMPUTE_TYPE = "float16"
assert COMPUTE_TYPE in ctranslate2.get_supported_compute_types("cuda")

model = WhisperModel(
    MODEL_NAME,
    revision=MODEL_REVISION,
    device="cuda",
    compute_type=COMPUTE_TYPE,
    download_root="/content/whisper-models",
)
print("Large v1 is loaded on the GPU.")
```

This explicitly downloads Large v1 into Colab, independently of the model on your
laptop. It needs about 3.1 GB of runtime disk for the weights. `float16` is a GPU
setting; your laptop test used CPU `int8`, so exact wording is not guaranteed to
match. Keep `BEAM_SIZE = 5` initially. A later test may use `3` or `1`, but compare
meaning and omissions before accepting a faster result.

### Cell 5 — Translate into English and write the SRT

This is **Whisper direct translation**, without a contextual text model. Times
are shifted back to the original video automatically. Output is saved every
20 accepted segments and at completion or a caught interruption.

```python
import json
import textwrap
import time
from datetime import timedelta
from pathlib import Path
import srt

OUTPUT_DIR = INPUT_DIR / "results"
OUTPUT_DIR.mkdir(exist_ok=True)
rows = []
started = time.perf_counter()
state = "running"
error = None
task = "transcribe" if SOURCE_LANGUAGE == "en" else "translate"

def save_outputs():
    subtitles = [
        srt.Subtitle(
            index=i,
            start=timedelta(milliseconds=row["start_ms"]),
            end=timedelta(milliseconds=row["end_ms"]),
            content="\n".join(textwrap.wrap(
                row["text"], width=42, break_long_words=False, break_on_hyphens=False,
            )),
        )
        for i, row in enumerate(rows, 1)
    ]
    payloads = {
        "subtitles.en.srt": srt.compose(subtitles, reindex=False),
        "segments.en.json": json.dumps(rows, ensure_ascii=False, indent=2),
        "run.json": json.dumps({
            "state": state, "error": error, "model": MODEL_NAME,
            "revision": MODEL_REVISION, "compute_type": COMPUTE_TYPE,
            "source_language": SOURCE_LANGUAGE, "task": task, "beam_size": BEAM_SIZE,
            "timeline_offset_ms": OFFSET_MS, "cue_count": len(rows),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "human_meaning": "unverified",
        }, indent=2),
    }
    for name, text in payloads.items():
        temporary = OUTPUT_DIR / (name + ".part")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(OUTPUT_DIR / name)

save_outputs()
try:
    segments, info = model.transcribe(
        str(AUDIO_PATH), language=SOURCE_LANGUAGE, task=task,
        beam_size=BEAM_SIZE, vad_filter=True,
    )
    for segment in segments:
        first = max(0, round(segment.start * 1000))
        last = min(metadata["audio_duration_ms"], round(segment.end * 1000))
        text = " ".join(segment.text.split())
        if not text or last <= first:
            continue
        rows.append({
            "id": f"cue_{len(rows) + 1:06d}",
            "start_ms": OFFSET_MS + first, "end_ms": OFFSET_MS + last, "text": text,
        })
        if len(rows) % 20 == 0:
            save_outputs()
            print(f"Saved {len(rows)} cues; audio position {last / 1000:.1f}s")
    state = "completed"
except KeyboardInterrupt:
    state = "interrupted"
    error = "Stopped before completion; this is a partial result"
    raise
except Exception as exc:
    state = "failed"
    error = str(exc)
    raise
finally:
    save_outputs()
    print(f"{state}: {len(rows)} cues, {time.perf_counter() - started:.1f}s; files in {OUTPUT_DIR}")
```

The generator must be iterated for inference to execute; the loop above does so.
`elapsed_seconds` measures Cell 5's translation/output work, excluding upload,
package installation and model loading. Include those separately when comparing
the overall cloud workflow with your laptop's job timings.
The displayed audio position excludes the movie offset. Subtitle times include
it. Wrapping does not invent word-level timings or remove text to fit two lines.
An empty SRT is not proof that there is no speech; listen to the selected track.

This simple notebook does **not** resume Whisper's decoder or reuse existing
local-project chunk checkpoints. Rerunning Cell 5 starts this selected audio from
the beginning. Its JSON/SRT outputs are independent test results, not files to
copy into the app's SQLite job/checkpoint directories.

### Cell 6 — Download your result

```python
import json
import shutil
from google.colab import files

run = json.loads((OUTPUT_DIR / "run.json").read_text(encoding="utf-8"))
print("Result state:", run["state"], "— any state other than completed is PARTIAL")
bundle_path = shutil.make_archive(str(INPUT_DIR / "translation-results"), "zip", OUTPUT_DIR)
files.download(bundle_path)
```

The ZIP includes `subtitles.en.srt`, `segments.en.json` and `run.json`. To download
only the SRT, run `files.download(str(OUTPUT_DIR / "subtitles.en.srt"))` instead.

## 3. Test the subtitles locally

1. Extract the downloaded results ZIP.
2. Open the **original video** in a player such as VLC and add `subtitles.en.srt`.
3. If you exported a sample, seek to that sample's original movie position. For
   example, a sample starting at `00:10:00` has subtitles around ten minutes, not
   zero. For the extracted audio alone, subtract the JSON's offset to use an
   audio-relative subtitle file; do not subtract it for the original movie.
4. Compare the same dialogue against your laptop Large v1 output. Check names,
   negation, missing lines, repeated text and synchronization; successful export
   and GPU speed do not establish translation accuracy.

The app has no automatic import/sync for these standalone Colab results in this
feature. Use the downloaded SRT externally for this test.

## 4. Troubleshooting and longer runs

- **No GPU / `nvidia-smi` fails:** select an available GPU runtime and rerun the
  setup cells. Free Colab GPU allocation and session duration are not guaranteed.
- **CUDA/cuDNN library errors:** current faster-whisper/CTranslate2 GPU wheels
  require matching CUDA/cuDNN libraries. Consult the linked official GPU setup
  instructions rather than changing random package versions. If required, the
  documented Linux packages are `nvidia-cublas-cu12` and `nvidia-cudnn-cu12==9.*`;
  their library directories must be configured before starting the Python
  process. Restart the runtime after changing native libraries, then rerun setup.
- **GPU out of memory:** restart the runtime to clear other loaded models, then
  try `COMPUTE_TYPE = "int8_float16"` if Cell 2 lists it. Compare the changed
  output. Begin with a short sample; do not load both Large v1 and another large
  model at once on a small GPU.
- **Runtime disconnected/deleted:** files in its temporary disk can disappear.
  Download completed results promptly. For longer experiments, you can manually
  mount your own Drive in your notebook and back up the result files there.
  No persistent backup is configured by these cells. Saved partial files are
  useful for review but are not a decoder-resume implementation.
- **Wrong language or dialogue track:** choose the correct track locally, export
  again, and keep `SOURCE_LANGUAGE = "ja"` for Japanese. English output requires
  `task="translate"` for Japanese, as Cell 5 uses.
- **Offset seems wrong:** use the matching audio + metadata ZIP. Do not combine
  one sample's audio with another sample's timing JSON.

## References and verification limits

Instructions checked against official documentation on 6 November 2026:

- [faster-whisper usage, GPU requirements and VAD](https://github.com/SYSTRAN/faster-whisper)
- [Official Large v1 model repository](https://huggingface.co/Systran/faster-whisper-large-v1)
- [Colab FAQ: runtime lifetime, GPU availability and temporary files](https://research.google.com/colaboratory/faq.html)
- [Colab file upload/download examples](https://colab.research.google.com/notebooks/io.ipynb)

Local checks cover extraction formats, selected tracks, delayed audio/nonzero
offsets, ZIP metadata, API access, downloads and notebook-code timestamp/output
logic. A real hosted Colab GPU session has not been executed by this agent.
Colab's interface and preinstalled native libraries can change; use the
diagnostic cell and official requirements if the environment differs.
