"""WSGI entry point for gunicorn:  gunicorn backend.server.wsgi:app

Builds the same app as the dev server, then starts the engine client so this
process relays between browsers and the vision engine.
"""

from __future__ import annotations

import logging

from werkzeug.middleware.proxy_fix import ProxyFix

from backend.config import RUNTIME
from backend.server.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app, socketio, engine = create_app()

if RUNTIME.is_production:
    # Render's proxy terminates HTTPS. ProxyFix makes Flask see the real
    # scheme, host and client IP from the X-Forwarded-* headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

engine.start()
