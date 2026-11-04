"""Narrow local-only llama.cpp adapter with owned lifecycle and bounded output."""

import json
import os
import secrets
import socket
import queue
import threading
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

from local_subs.jobs import write_json
from local_subs.text_models import prepare


class LocalTextModel:
    def __init__(self, settings, directory, check_cancel=lambda: None):
        self.settings, self.directory, self.check_cancel = (
            settings,
            directory,
            check_cancel,
        )
        self.process = None

    def __enter__(self):
        self.identity = prepare(
            self.settings.model_cache,
            self.settings.text_model,
            offline=True,
            notify=lambda _: None,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.token = secrets.token_urlsafe(32)
        folder = self.directory / "text-runtime" / uuid4().hex
        folder.mkdir(parents=True)
        self.stop_file = folder / "stop.request"
        command = [
            self.identity["executable"],
            "-m",
            self.identity["weights"],
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--api-key",
            self.token,
            "--ctx-size",
            str(self.settings.translation_context_tokens),
            "--parallel",
            "1",
            "--threads",
            "4",
            "--threads-batch",
            "4",
            "--n-gpu-layers",
            "0",
            "--jinja",
            "--reasoning",
            "off",
            "--no-webui",
        ]
        config = folder / "guard.json"
        self.metrics_path = config.with_suffix(".metrics.json")
        write_json(
            config,
            {
                "command": command,
                "parent_pid": os.getpid(),
                "stop_file": str(self.stop_file),
                "log_file": str(folder / "server.log"),
                "stdin_control": True,
            },
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "local_subs.text_runtime_guard", str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + 120
        try:
            while time.monotonic() < deadline:
                self.check_cancel()
                if self.process.poll() is not None:
                    raise ValueError(
                        f"Local text server stopped during loading; inspect {folder / 'server.log'}"
                    )
                try:
                    self.request("/health", None, timeout=1)
                    return self
                except (OSError, ValueError):
                    time.sleep(0.2)
            raise ValueError(
                f"Text model loading timed out; inspect {folder / 'server.log'}"
            )
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def request(self, path, payload, timeout=180):
        data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            self.url + path,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Text server response exceeds the bounded limit")
            return json.loads(raw)

    def translate(self, messages, schema):
        self.check_cancel()
        result = queue.Queue(maxsize=1)

        def complete():
            try:
                result.put((True, self.completion(messages, schema)))
            except BaseException as exc:
                result.put((False, exc))

        # Poll cancellation while the owned native server handles a bounded request.
        threading.Thread(target=complete, daemon=True).start()
        while True:
            self.check_cancel()
            try:
                success, response = result.get(timeout=0.2)
                break
            except queue.Empty:
                continue
        if not success:
            raise response
        self.check_cancel()
        if response["choices"][0].get("finish_reason") == "length":
            raise ValueError(
                "Translation hit the output-token limit; reduce batch size or increase the limit"
            )
        return response["choices"][0]["message"]["content"], response

    def completion(self, messages, schema):
        return self.request(
            "/v1/chat/completions",
            {
                "messages": messages,
                "temperature": 0,
                "seed": 42,
                "max_tokens": self.settings.translation_max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                "reasoning_effort": "none",
                "response_format": {"type": "json_object", "schema": schema},
            },
        )

    def __exit__(self, *args):
        if self.process is not None:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
                if self.metrics_path.is_file():
                    self.identity["memory"] = json.loads(
                        self.metrics_path.read_text(encoding="utf-8")
                    )
            finally:
                self.token = ""
