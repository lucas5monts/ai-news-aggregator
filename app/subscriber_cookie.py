"""Signed subscriber cookie — identifies visitors who subscribed but aren't logged in."""
from __future__ import annotations

from datetime import timedelta

from flask import current_app, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .models import User, db

COOKIE_NAME = "subscriber_id"
COOKIE_MAX_AGE = int(timedelta(days=30).total_seconds())


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="subscriber")


def set_subscriber_cookie(response, user_id: int) -> None:
    """Write a signed subscriber cookie to the response."""
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
    """Delete the subscriber cookie."""
    response.delete_cookie(COOKIE_NAME, samesite="Lax")


def get_subscriber_user() -> User | None:
    """Decode the subscriber cookie and return the User, or None on miss/error."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        user_id = _serializer().loads(token, max_age=COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(user_id, int):
        return None
    return db.session.get(User, user_id)
