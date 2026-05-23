"""Development server entrypoint.

Usage:
    python3 run.py          # boots Flask dev server on http://127.0.0.1:5000
    ENABLE_SCHEDULER=1 python3 run.py   # also starts APScheduler

For production, use gunicorn:
    gunicorn -c gunicorn_conf.py run:app
"""
from __future__ import annotations

import logging
import os

# Enable scheduler when running directly via `python3 run.py`
# (gunicorn sets this via gunicorn_conf.py instead)
if __name__ == "__main__":
    os.environ.setdefault("ENABLE_SCHEDULER", "1")

from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
