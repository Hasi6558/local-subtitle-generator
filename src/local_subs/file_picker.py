"""Native local file selection in a separate process, leaving the API responsive."""

import json
import os
import subprocess
import sys
from pathlib import Path


def pick_file(initial_directory):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "local_subs.file_picker", str(initial_directory)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("File selection timed out; choose a video again") from exc
    if result.returncode:
        raise ValueError(
            "Could not open the local file picker. Use Enter path manually, or check that Python includes Tk and the server runs in your desktop session."
        )
    selected = json.loads(result.stdout)
    if selected is not None and not isinstance(selected, str):
        raise ValueError("Invalid file picker response")
    return Path(selected) if selected else None


def main():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(
            parent=root,
            title="Choose a video for subtitles",
            initialdir=sys.argv[1],
            filetypes=[
                (
                    "Video and audio",
                    "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mpg *.mpeg *.ts *.m2ts *.wav *.mp3 *.m4a *.flac *.ogg",
                ),
                ("All files", "*.*"),
            ],
        )
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(selected or None, ensure_ascii=False))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
