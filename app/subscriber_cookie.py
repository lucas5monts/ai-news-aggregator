"""Signed cookie for identifying a subscriber on the public feed (no login).

Set after subscribe or preferences load/save; cleared on unsubscribe.
"""
from __future__ import annotations

from datetime import timedelta

from flask import current_app, request
from itsdangerous import BadSignature, URLSafeSerializer

from .models import User, db

COOKIE_NAME = "subscriber_id"
COOKIE_MAX_AGE = int(timedelta(days=30).total_seconds())


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="subscriber")


def set_subscriber_cookie(response, user_id: int) -> None:
    """Attach a signed HttpOnly cookie identifying *user_id*."""
    secure = current_app.config.get("SESSION_COOKIE_SECURE", False)
    token = _serializer().dumps(user_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure,
    )


def clear_subscriber_cookie(response) -> None:
    """Remove the subscriber cookie."""
    response.delete_cookie(COOKIE_NAME, samesite="Lax")


def get_subscriber_user() -> User | None:
    """Return the User for the signed subscriber cookie, or None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        user_id = _serializer().loads(token)
    except BadSignature:
        return None
    if not isinstance(user_id, int):
        return None
    return db.session.get(User, user_id)
