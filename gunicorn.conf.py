"""gunicorn settings for production (python run.py --prod).

One worker on purpose: Socket.IO keeps per-connection state in memory, so several
worker processes would need sticky sessions and a message queue. One worker with
threads handles our traffic and keeps memory low on the 512 MB free tier.
"""

from backend.config import WEB_HOST, WEB_PORT

bind = f"{WEB_HOST}:{WEB_PORT}"
workers = 1
worker_class = "gthread"   # threads: WebSockets and MJPEG streams are long-lived requests
threads = 32
timeout = 120              # generous: the free tier has only 0.1 CPU
graceful_timeout = 10      # don't hang for 30 s on redeploys
accesslog = "-"            # logs to stdout, which Render shows
errorlog = "-"
