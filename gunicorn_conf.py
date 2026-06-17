"""Gunicorn configuration for production deployment.

Used by: gunicorn -c gunicorn_conf.py run:app
"""
import os

# Bind address — Render/Fly inject PORT env var
port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Workers — default to one so ENABLE_SCHEDULER=1 cannot start duplicate
# in-process schedulers. Scale web workers separately from the scheduler.
workers = int(os.environ.get("WEB_CONCURRENCY", 2))

worker_class = "sync"

# Timeouts
timeout = 60
graceful_timeout = 30
keepalive = 5

# Logging — stdout/stderr so Render/Fly captures them
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'


if workers > 1 and os.environ.get("ENABLE_SCHEDULER") == "1":
    raise RuntimeError(
        "ENABLE_SCHEDULER=1 with multiple gunicorn workers can send duplicate digests. "
        "Set WEB_CONCURRENCY=1 or run the scheduler in a dedicated process."
    )
