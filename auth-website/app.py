"""موقع مصادقة بسيط: تسجيل، دخول (بكلمة مرور أو جوجل)، خروج، لوحة تحكم محمية.

التشغيل:
    pip install -r requirements.txt
    export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
    # اختياري لتفعيل تسجيل الدخول عبر جوجل:
    export GOOGLE_CLIENT_ID=...
    export GOOGLE_CLIENT_SECRET=...
    python app.py
"""

from __future__ import annotations

import os
import re
import sqlite3
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "auth.db")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]")

class ReverseProxyPrefixMiddleware:
    """Honors an X-Script-Name header set by nginx so url_for() generates
    correct links when the app is reverse-proxied under a path prefix
    (e.g. https://fractionksa.com/auth/)."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        script_name = environ.get("HTTP_X_SCRIPT_NAME", "")
        if script_name:
            environ["SCRIPT_NAME"] = script_name
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(script_name):
                environ["PATH_INFO"] = path_info[len(script_name):]
        scheme = environ.get("HTTP_X_FORWARDED_PROTO", "")
        if scheme:
            environ["wsgi.url_scheme"] = scheme
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = ReverseProxyPrefixMiddleware(app.wsgi_app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

oauth = OAuth(app)
if GOOGLE_OAUTH_ENABLED:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@app.context_processor
def inject_flags():
    return {"google_oauth_enabled": GOOGLE_OAUTH_ENABLED}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def _unique_username_from_email(db: sqlite3.Connection, email: str) -> str:
    base = USERNAME_SANITIZE_RE.sub("", email.split("@")[0]).lower()
    if len(base) < 3:
        base = (base + "user")[:3]
    base = base[:28]

    candidate = base
    suffix = 1
    while db.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone() is not None:
        candidate = f"{base}{suffix}"[:32]
        suffix += 1
    return candidate


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        error = None
        if not (3 <= len(username) <= 32):
            error = "اسم المستخدم يجب أن يكون بين 3 و32 حرفًا."
        elif not EMAIL_RE.match(email):
            error = "البريد الإلكتروني غير صالح."
        elif len(password) < 8:
            error = "كلمة المرور يجب أن تكون 8 أحرف على الأقل."

        if error is None:
            db = get_db()
            existing = db.execute(
                "SELECT id FROM users WHERE username = ? OR email = ?",
                (username, email),
            ).fetchone()
            if existing is not None:
                error = "اسم المستخدم أو البريد الإلكتروني مستخدم بالفعل."

        if error is None:
            db = get_db()
            db.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, generate_password_hash(password)),
            )
            db.commit()
            return redirect(url_for("login"))

        return render_template("register.html", error=error, username=username, email=email)

    return render_template("register.html", error=None, username="", email="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (identifier, identifier.lower()),
        ).fetchone()

        if user is None or user["password_hash"] is None or not check_password_hash(user["password_hash"], password):
            error = "بيانات الدخول غير صحيحة."
            if user is not None and user["password_hash"] is None:
                error = "هذا الحساب مسجّل عبر جوجل. استخدم زر «الدخول عبر جوجل»."
            return render_template("login.html", error=error, identifier=identifier)

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("dashboard"))

    return render_template("login.html", error=None, identifier="")


@app.route("/oauth/google")
def google_login():
    if not GOOGLE_OAUTH_ENABLED:
        flash("تسجيل الدخول عبر جوجل غير مُفعّل على هذا الخادم بعد.")
        return redirect(url_for("login"))
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/oauth/google/callback")
def google_callback():
    if not GOOGLE_OAUTH_ENABLED:
        return redirect(url_for("login"))

    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo")
    if userinfo is None or not userinfo.get("email"):
        flash("تعذّر جلب بيانات الحساب من جوجل.")
        return redirect(url_for("login"))

    google_id = userinfo["sub"]
    email = userinfo["email"].strip().lower()

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()

    if user is None:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is not None:
            db.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, user["id"]))
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        else:
            username = _unique_username_from_email(db, email)
            cursor = db.execute(
                "INSERT INTO users (username, email, password_hash, google_id) VALUES (?, ?, NULL, ?)",
                (username, email, google_id),
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("dashboard.html", user=user)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
else:
    init_db()
