"""Opt-in real media/model browser server, without test fixture endpoints."""

import os
from pathlib import Path
from uuid import uuid4
import uvicorn
from local_subs.api import create_app
from local_subs.jobs import write_json

PROJECT = Path(__file__).resolve().parents[2]
media = Path(os.environ["LOCAL_SUBS_TEST_MEDIA"]).resolve()
root = PROJECT / "outputs" / f"phase5-live-{uuid4().hex}"
app = create_app(
    root, [media.parent], model_cache=PROJECT / "models", token="ui-test-key", port=8767
)
write_json(
    PROJECT / "outputs" / "phase5-live-info.json",
    {"output_root": str(root), "source": str(media)},
)
uvicorn.run(
    app,
    host="127.0.0.1",
    port=8767,
    access_log=False,
    log_level="warning",
    loop="asyncio:SelectorEventLoop" if os.name == "nt" else "auto",
)
