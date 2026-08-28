#!/usr/bin/env python3
"""Hermes-owned OBLITERATUS Gradio server shim.

The upstream ``obliteratus ui`` command may return after launching Gradio in
some non-interactive environments. Hermes needs a stable background process, so
this module imports the upstream Gradio ``demo``, launches it, and keeps the
process alive until it receives SIGTERM/SIGINT.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path


def parse_auth(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    if ":" not in value:
        raise SystemExit("--auth must be formatted as user:pass")
    user, password = value.split(":", 1)
    if not user or not password:
        raise SystemExit("--auth must include both user and pass")
    return user, password


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OBLITERATUS UI for Hermes")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--auth")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not (project_root / "app.py").is_file():
        raise SystemExit(f"app.py not found under {project_root}")

    sys.path.insert(0, str(project_root))

    from app import demo  # pylint: disable=import-error,import-outside-toplevel

    should_stop = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal should_stop
        should_stop = True
        try:
            demo.close()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=False,
        inbrowser=False,
        auth=parse_auth(args.auth),
        quiet=args.quiet,
        prevent_thread_lock=True,
    )

    while not should_stop:
        time.sleep(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
