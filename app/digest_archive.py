"""Digest archive — list and view past email digests."""
from __future__ import annotations

import logging

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from app.models import Digest, db

log = logging.getLogger(__name__)

digest_archive_bp = Blueprint("digest_archive", __name__)


@digest_archive_bp.route("/digests")
@login_required
def digest_list():
    """All digests for the current user, newest first."""
    digests = (
        db.session.query(Digest)
        .filter_by(user_id=current_user.id)
        .order_by(Digest.sent_at.desc())
        .all()
    )
    return render_template("digest_archive.html", digests=digests)


@digest_archive_bp.route("/digests/<int:digest_id>")
@login_required
def digest_view(digest_id: int):
    """Single past digest rendered in a sandboxed srcdoc iframe."""
    digest = db.session.get(Digest, digest_id)
    if digest is None or digest.user_id != current_user.id:
        abort(404)
    return render_template("digest_view.html", digest=digest)
