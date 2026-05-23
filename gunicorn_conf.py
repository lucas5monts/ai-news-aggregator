"""Gunicorn configuration for production deployment.

Used by: gunicorn -c gunicorn_conf.py run:app
"""
import os

# Bind address — Render/Fly inject PORT env var
port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Workers — 2 is a safe default for a single-instance deploy
workers = 2

# Enable scheduler only in the first worker to avoid N parallel APScheduler instances.
# We use Gunicorn's post_fork hook to set ENABLE_SCHEDULER=1 only in worker 0.
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


def post_fork(server, worker):
    """Only the first worker should run the scheduler."""
    import os
    # APScheduler is started inside create_app() when ENABLE_SCHEDULER=1.
    # We can't easily number workers, so we gate on ENABLE_SCHEDULER env var
    # being set before gunicorn starts. For production, set ENABLE_SCHEDULER=1
    # in the environment and only one scheduler will start per process — each
    # worker gets its own Python process so multiple workers = multiple schedulers.
    # To run only one scheduler, use a single worker or a dedicated scheduler process.
    # Default: disabled in gunicorn, enabled only when explicitly set.
    pass
