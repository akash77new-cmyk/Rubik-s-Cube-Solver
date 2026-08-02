#!/usr/bin/env python
"""Single entry point: starts the vision engine process, the web server and the UI.

    python run.py              # normal launch, opens the browser
    python run.py --dev        # expects `npm run dev` for hot-reloading the UI
    python run.py --no-engine  # attach to an engine already running elsewhere
    python run.py --headless   # do not open a browser
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import ENGINE_HOST, ENGINE_PORT, FRONTEND_DIST, WEB_HOST, WEB_PORT

BANNER = r"""
  ____      _          ____       _
 / ___|   _| |__   ___/ ___|  ___ | |_   _____ _ __
| |  | | | | '_ \ / _ \___ \ / _ \| \ \ / / _ \ '__|
| |__| |_| | |_) |  __/___) | (_) | |\ V /  __/ |
 \____\__,_|_.__/ \___|____/ \___/|_| \_/ \___|_|
   real-time computer-vision Rubik's Cube solver
"""


def _spawn_engine(host: str, port: int) -> subprocess.Popen:
    """Launch the vision engine in its own process (true socket IPC)."""
    command = [sys.executable, "-m", "backend.engine", "--host", host, "--port", str(port)]
    return subprocess.Popen(command, cwd=str(PROJECT_ROOT))


def _open_browser(url: str, delay: float = 1.5) -> None:
    def _later() -> None:
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=_later, daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Rubik's Cube Solver app")
    parser.add_argument("--host", default=WEB_HOST)
    parser.add_argument("--port", type=int, default=WEB_PORT)
    parser.add_argument("--engine-host", default=ENGINE_HOST)
    parser.add_argument("--engine-port", type=int, default=ENGINE_PORT)
    parser.add_argument("--no-engine", action="store_true", help="do not spawn the engine")
    parser.add_argument("--headless", action="store_true", help="do not open a browser")
    parser.add_argument("--dev", action="store_true", help="frontend runs under Vite")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    print(BANNER)

    engine_process = None
    if not args.no_engine:
        engine_process = _spawn_engine(args.engine_host, args.engine_port)
        print(f"  vision engine  -> pid {engine_process.pid} "
              f"on {args.engine_host}:{args.engine_port}")

    url = f"http://{args.host}:{args.port}"
    if args.dev:
        print("  frontend       -> run `npm run dev` in ./frontend (http://localhost:5173)")
    elif not (FRONTEND_DIST / "index.html").exists():
        print("  frontend       -> NOT BUILT. Run: cd frontend && npm install && npm run build")
    else:
        print(f"  web ui         -> {url}")

    if not args.headless and not args.dev:
        _open_browser(url)

    from backend.server.app import run as run_server

    try:
        run_server(
            host=args.host,
            port=args.port,
            engine_host=args.engine_host,
            engine_port=args.engine_port,
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if engine_process and engine_process.poll() is None:
            engine_process.terminate()
            try:
                engine_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                engine_process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
