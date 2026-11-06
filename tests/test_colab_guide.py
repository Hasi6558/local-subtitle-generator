"""Check copyable guide code locally; no Colab connection or model download."""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import srt


GUIDE = Path(__file__).resolve().parents[1] / "docs" / "COLAB_MANUAL_TRANSLATION.md"


def test_all_python_cells_compile():
    cells = re.findall(r"```python\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)
    assert len(cells) == 6
    for cell in cells:
        ast.parse(cell)


@pytest.mark.parametrize("fail", [False, True])
def test_guide_original_movie_offset_clipping_and_partial_output(tmp_path, fail):
    text = (
        GUIDE.read_text(encoding="utf-8").split("### Cell 5")[1].split("### Cell 6")[0]
    )
    code = re.search(r"```python\n(.*?)```", text, re.S)[1]

    class Model:
        def transcribe(self, path, **kwargs):
            assert kwargs["task"] == "translate" and kwargs["language"] == "ja"

            def segments():
                yield SimpleNamespace(start=0.5, end=1.2, text=" First line. ")
                if fail:
                    raise RuntimeError("Interrupted GPU test")
                yield SimpleNamespace(start=2, end=4, text="Second line.")

            return segments(), None

    namespace = {
        "INPUT_DIR": tmp_path,
        "AUDIO_PATH": tmp_path / "audio.flac",
        "SOURCE_LANGUAGE": "ja",
        "OFFSET_MS": 600000,
        "metadata": {"audio_duration_ms": 3000},
        "MODEL_NAME": "large-v1",
        "MODEL_REVISION": "test",
        "COMPUTE_TYPE": "float16",
        "BEAM_SIZE": 5,
        "model": Model(),
    }
    if fail:
        with pytest.raises(RuntimeError, match="Interrupted GPU test"):
            exec(compile(code, str(GUIDE), "exec"), namespace)
    else:
        exec(compile(code, str(GUIDE), "exec"), namespace)
    directory = tmp_path / "results"
    restored = list(
        srt.parse((directory / "subtitles.en.srt").read_text(encoding="utf-8"))
    )
    report = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert restored[0].start.total_seconds() == 600.5
    assert restored[0].end.total_seconds() == 601.2
    assert report["state"] == ("failed" if fail else "completed")
    assert len(restored) == (1 if fail else 2)
    if not fail:
        assert restored[1].end.total_seconds() == 603
