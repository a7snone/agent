"""Shared DB connection helper and login guard, used by app.py and content.py."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from functools import wraps

from flask import current_app, g, redirect, session, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "auth.db")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        # A longer busy timeout than the 5s default matters once more than one
        # gunicorn worker writes concurrently -- SQLite allows only one writer
        # at a time and blocks the rest until it's free.
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def pseudonym_for(user_id: int) -> str:
    """A stable, non-reversible display name for a user_id: the same user
    always gets the same pseudonym, but it can't be turned back into the
    user_id or username without the app's SECRET_KEY (kept server-side)."""
    secret = current_app.config.get("SECRET_KEY", "")
    digest = hashlib.sha256(f"pseudonym:{secret}:{user_id}".encode("utf-8")).hexdigest()
    return f"مستخدم #{digest[:6].upper()}"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped
