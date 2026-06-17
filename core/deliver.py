"""Gmail SMTP delivery for the AI news digest."""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT = 30


def load_email_config() -> dict[str, str]:
    """Load Gmail credentials from environment / .env file.

    Required keys: GMAIL_ADDRESS, GMAIL_APP_PASSWORD
    Optional key:  TO_ADDRESS (used by the CLI; the web app uses each user's
                   own email address and does not need this key)

    Raises RuntimeError with a clear pointer to .env.example if anything is missing.
    """
    load_dotenv()
    required = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
    config: dict[str, str] = {}
    missing: list[str] = []
    for key in required:
        val = os.environ.get(key, "").strip()
        if not val:
            missing.append(key)
        else:
            config[key] = val

    # TO_ADDRESS is only needed for the CLI; include it if present but don't require it
    to_addr = os.environ.get("TO_ADDRESS", "").strip()
    if to_addr:
        config["TO_ADDRESS"] = to_addr

    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}.\n"
            "Copy .env.example to .env and fill in the values.\n"
            "See .env.example for the Gmail App Password walkthrough."
        )
    return config


def build_subject(edition: str, story_count: int, send_time: str | None = None) -> str:
    """Return formatted subject: 'AI Brief · Thu May 21 · 6:00 AM · 12 stories'.

    If *send_time* ("HH:MM", 24-hour) is provided, it is formatted as a 12-hour
    time and used in the subject. Otherwise a sensible default is used based on
    *edition*.
    """
    now = datetime.now()
    weekday = now.strftime("%a")
    mon = now.strftime("%b")
    day = str(now.day)
    edition_time = _format_12h(send_time) or ("6:00 AM" if edition == "morning" else "8:00 PM")
    return f"AI Brief · {weekday} {mon} {day} · {edition_time} · {story_count} stories"


def _format_12h(time_str: str | None) -> str | None:
    """Convert 'HH:MM' (24-hour) to a 12-hour label like '5:00 AM'. None on bad input."""
    if not time_str:
        return None
    try:
        hour, minute = (int(x) for x in time_str.split(":"))
        suffix = "AM" if hour < 12 else "PM"
        h12 = hour % 12 or 12
        return f"{h12}:{minute:02d} {suffix}"
    except Exception:
        return None


def send_digest(
    subject: str,
    plaintext: str,
    html: str,
    to_address: str,
    from_address: str,
    app_password: str,
    unsubscribe_url: str = "",
) -> None:
    """Build a MIMEMultipart/alternative message and send via Gmail SMTP_SSL.

    Logs message size on success; logs a useful error and re-raises on failure.
    Never logs the app password. When *unsubscribe_url* is provided, a footer
    link is appended to both the plaintext and HTML parts (CAN-SPAM / GDPR).
    """
    if unsubscribe_url:
        plaintext = plaintext + f"\n\n─\nUnsubscribe: {unsubscribe_url}"
        # For HTML: inject a footer link before the closing body tag.
        html = html.replace(
            "</body>",
            f'<p style="text-align:center;font-size:11px;color:#999;margin-top:32px;">'
            f'<a href="{unsubscribe_url}" style="color:#999;">Unsubscribe</a></p></body>',
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    # RFC 2046: plain first, HTML second — client picks the last part it understands
    msg.attach(MIMEText(plaintext, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    payload = msg.as_bytes()
    log.info(
        "sending to=%s from=%s subject=%r size=%d bytes",
        to_address,
        from_address,
        subject,
        len(payload),
    )

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
            smtp.login(from_address, app_password)
            smtp.sendmail(from_address, to_address, payload)
        log.info("digest sent successfully (%d bytes)", len(payload))
    except (smtplib.SMTPException, OSError) as exc:
        log.error(
            "failed to send digest to %s: %s: %s",
            to_address,
            type(exc).__name__,
            exc,
        )
        raise
