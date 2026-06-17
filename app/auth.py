"""Email/password login and logout."""
from __future__ import annotations

import logging

from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app import limiter
from .models import User, db
from .subscriber_cookie import clear_subscriber_cookie

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html"), 400

        user = db.session.query(User).filter(
            db.func.lower(User.email) == email
        ).first()

        if user is None or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401

        login_user(user, remember="remember_me" in request.form)
        log.info("login: user_id=%s", user.id)

        next_url = request.args.get("next", "")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("preferences.preferences"))

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log.info("logout: user_id=%s", current_user.id)
    logout_user()
    flash("You've been logged out.", "info")
    resp = make_response(redirect(url_for("main.feed")))
    clear_subscriber_cookie(resp)
    return resp
