"""Hermes CLI as the ADAGS runtime: `hermes proxy` → Nous Portal.

We do not read `~/.hermes/config.yaml` for the model. ADAGS pins Nemotron.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8645
# Nous Portal catalog name (same family as OpenRouter's :free slug, billed
# against the Portal subscription you already funded).
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def hermes_bin() -> str:
    override = os.environ.get("ADAGS_HERMES_BIN")
    if override:
        return override
    found = shutil.which("hermes")
    if not found:
        raise RuntimeError(
            "hermes CLI not on PATH. Install Hermes Agent or set ADAGS_HERMES_BIN."
        )
    return found


def resolve_model(explicit: str | None = None) -> str:
    return (explicit or os.environ.get("ADAGS_MODEL") or DEFAULT_MODEL).strip()


def hermes_mode() -> str:
    return "proxy"


def proxy_listening(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_proxy(
    *,
    host: str | None = None,
    port: int | None = None,
) -> tuple[str, int]:
    host = host or os.environ.get("ADAGS_HERMES_HOST", DEFAULT_HOST)
    port = int(port or os.environ.get("ADAGS_HERMES_PORT", DEFAULT_PORT))
    if proxy_listening(host, port):
        return host, port
    print(f"starting `hermes proxy` on {host}:{port} …", flush=True)
    cmd = [
        hermes_bin(),
        "proxy",
        "start",
        "--provider",
        os.environ.get("ADAGS_HERMES_UPSTREAM", "nous"),
        "--host",
        host,
        "--port",
        str(port),
    ]
    log = Path(os.environ.get("ADAGS_HERMES_LOG", "/tmp/adags-hermes-proxy.log"))
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("ab")
    subprocess.Popen(
        cmd,
        stdout=fh,
        stderr=fh,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + float(os.environ.get("ADAGS_HERMES_WAIT", "20"))
    while time.time() < deadline:
        if proxy_listening(host, port):
            return host, port
        time.sleep(0.2)
    raise RuntimeError(
        f"started `hermes proxy start` but {host}:{port} never came up. "
        f"Check {log} or run `hermes portal` if you are not logged in."
    )


def endpoint(*, model: str | None = None) -> dict:
    """Return {mode, model, base_url, api_key} for ChatLLM."""
    chosen = resolve_model(model)
    host, port = ensure_proxy()
    return {
        "mode": "proxy",
        "model": chosen,
        "api_key": os.environ.get("ADAGS_HERMES_KEY", "sk-hermes-proxy"),
        "base_url": os.environ.get("ADAGS_BASE_URL") or f"http://{host}:{port}/v1",
    }


# Kept for tests that still import the old name.
def config_model() -> str:
    return resolve_model()
