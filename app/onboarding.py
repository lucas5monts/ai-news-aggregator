"""Onboarding email sequence — welcome + day-3 topic nudge."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _already_sent(user, step: str) -> bool:
    from app.models import OnboardingEmail, db
    return db.session.query(OnboardingEmail).filter_by(user_id=user.id, step=step).first() is not None


def _record_sent(user, step: str) -> None:
    from app.models import OnboardingEmail, db
    db.session.add(OnboardingEmail(user_id=user.id, step=step))
    db.session.commit()


def send_welcome_email(user, app) -> None:
    """Send the welcome email immediately after signup."""
    with app.app_context():
        try:
            if _already_sent(user, "welcome"):
                return
            from core.deliver import load_email_config, send_digest
            cfg = load_email_config()
            base_url = os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/")
            prefs_url = f"{base_url}/preferences"
            unsub_url = f"{base_url}/unsubscribe/{user.unsubscribe_token}"

            subject = "Welcome to AI News — here's how to get started"
            plaintext = f"""Hey, welcome aboard!

You're now getting a daily AI news digest. Here's how to make it yours:

1. Set your interest topics: {prefs_url}
   Tell us what you care about — AI, startups, climate, F1, whatever — and we'll surface the most relevant stories for you.

2. Pick your sources
   Enable or disable any of the RSS sources from the same preferences page.

3. Set your delivery time
   Morning briefing, evening recap, or both — your call.

Your first digest will arrive at your scheduled time. See you then.

—
Unsubscribe: {unsub_url}
"""
            html = f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:32px 24px;color:#18181b;">
  <h1 style="font-size:22px;font-weight:700;margin-bottom:8px;">Welcome to AI News</h1>
  <p style="color:#52525b;margin-bottom:24px;">You're subscribed. Your first digest is on its way.</p>
  <p style="font-weight:600;margin-bottom:12px;">Make it yours in 3 steps:</p>
  <ol style="padding-left:20px;color:#3f3f46;line-height:1.8;">
    <li><strong>Set your topics</strong> — tell us what you care about and we'll personalize your feed with AI</li>
    <li><strong>Choose your sources</strong> — enable the outlets you trust</li>
    <li><strong>Pick your delivery time</strong> — morning, evening, or both</li>
  </ol>
  <a href="{prefs_url}" style="display:inline-block;margin-top:24px;padding:12px 24px;background:#6366f1;color:#fff;border-radius:10px;text-decoration:none;font-weight:600;">Set up my preferences</a>
  <p style="margin-top:40px;font-size:12px;color:#a1a1aa;text-align:center;"><a href="{unsub_url}" style="color:#a1a1aa;">Unsubscribe</a></p>
</div>
"""
            send_digest(
                subject=subject,
                plaintext=plaintext,
                html=html,
                to_address=user.email,
                from_address=cfg["GMAIL_ADDRESS"],
                app_password=cfg["GMAIL_APP_PASSWORD"],
            )
            _record_sent(user, "welcome")
            log.info("onboarding welcome sent to user_id=%s", user.id)
        except Exception as exc:
            log.warning("onboarding welcome failed for user_id=%s: %s", user.id, exc)


def send_day3_nudge(app) -> None:
    """Scheduler job — send day-3 topic nudge to users with no topics set."""
    with app.app_context():
        from app.models import OnboardingEmail, User, UserSettings, UserTopic, db
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        # users created 3+ days ago who haven't set topics and haven't received this email
        users = db.session.query(User).filter(User.created_at <= three_days_ago).all()
        for user in users:
            settings = db.session.get(UserSettings, user.id)
            if not settings or not settings.send_email:
                continue
            if _already_sent(user, "day3"):
                continue
            topic_count = db.session.query(UserTopic).filter_by(user_id=user.id).count()
            if topic_count > 0:
                # they already set topics; still mark it sent so we don't check again
                _record_sent(user, "day3")
                continue
            try:
                from core.deliver import load_email_config, send_digest
                cfg = load_email_config()
                base_url = os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/")
                prefs_url = f"{base_url}/preferences"
                unsub_url = f"{base_url}/unsubscribe/{user.unsubscribe_token}"
                subject = "Quick tip: personalize your AI digest"
                plaintext = f"""Hey — you've been getting AI News for a few days now.

One thing that makes a big difference: setting your interest topics.

Once you tell us what you're into, we use AI to score every story against your interests and surface the most relevant ones first. Takes 30 seconds.

Set your topics here: {prefs_url}

—
Unsubscribe: {unsub_url}
"""
                html = f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:32px 24px;color:#18181b;">
  <h1 style="font-size:20px;font-weight:700;margin-bottom:8px;">Personalize your digest</h1>
  <p style="color:#52525b;margin-bottom:20px;">You've been subscribed for a few days — here's one thing that makes the digest way better.</p>
  <p style="color:#3f3f46;line-height:1.7;">Set your interest topics and we'll use AI to score every story against what you care about. The result is a feed that's actually relevant to you, not just the most-clicked headlines.</p>
  <a href="{prefs_url}" style="display:inline-block;margin-top:24px;padding:12px 24px;background:#6366f1;color:#fff;border-radius:10px;text-decoration:none;font-weight:600;">Set my topics</a>
  <p style="margin-top:40px;font-size:12px;color:#a1a1aa;text-align:center;"><a href="{unsub_url}" style="color:#a1a1aa;">Unsubscribe</a></p>
</div>
"""
                send_digest(
                    subject=subject,
                    plaintext=plaintext,
                    html=html,
                    to_address=user.email,
                    from_address=cfg["GMAIL_ADDRESS"],
                    app_password=cfg["GMAIL_APP_PASSWORD"],
                )
                _record_sent(user, "day3")
                log.info("onboarding day3 sent to user_id=%s", user.id)
            except Exception as exc:
                log.warning("onboarding day3 failed for user_id=%s: %s", user.id, exc)
