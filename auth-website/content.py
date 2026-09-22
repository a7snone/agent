"""Content authentication ("مصادقة") feature.

A user creates content (news text or a video link). Any other logged-in
user can "authenticate" it, which copies its exact current text into their
own account. A copy's live authenticator count is simply how many copies of
the same content item currently share its exact content hash -- editing a
copy changes its hash and drops it out of that count; reverting to the
identical text brings it back in, same as before.

Every state-changing event (create / authenticate / edit) is appended to an
internal hash-chained ledger (ledger_blocks), so the history is
tamper-evident -- the same block-linking idea a blockchain uses, kept as a
single trusted-server structure instead of a distributed chain.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from core import get_db, login_required

content_bp = Blueprint("content", __name__)

GENESIS_PREV_HASH = "0" * 64


def init_content_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS content_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK(kind IN ('news', 'video')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS content_copies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_item_id INTEGER NOT NULL REFERENCES content_items(id),
                owner_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                source_copy_id INTEGER REFERENCES content_copies(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(content_item_id, owner_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_index INTEGER NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                content_item_id INTEGER NOT NULL,
                copy_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                prev_copy_hash TEXT,
                timestamp TEXT NOT NULL,
                prev_block_hash TEXT NOT NULL,
                block_hash TEXT NOT NULL
            )
            """
        )


def _hash_content(title: str, body: str) -> str:
    normalized = f"{title.strip()}\n{body.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _block_payload(block_index, event_type, content_item_id, copy_id, actor_id,
                    content_hash, prev_copy_hash, timestamp, prev_block_hash) -> str:
    return "|".join(
        [
            str(block_index),
            event_type,
            str(content_item_id),
            str(copy_id),
            str(actor_id),
            content_hash,
            prev_copy_hash or "",
            timestamp,
            prev_block_hash,
        ]
    )


def _append_block(db, *, event_type, content_item_id, copy_id, actor_id, content_hash, prev_copy_hash):
    last = db.execute("SELECT * FROM ledger_blocks ORDER BY block_index DESC LIMIT 1").fetchone()
    block_index = (last["block_index"] + 1) if last else 0
    prev_block_hash = last["block_hash"] if last else GENESIS_PREV_HASH
    timestamp = datetime.now(timezone.utc).isoformat()

    payload = _block_payload(
        block_index, event_type, content_item_id, copy_id, actor_id,
        content_hash, prev_copy_hash, timestamp, prev_block_hash,
    )
    block_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    db.execute(
        """
        INSERT INTO ledger_blocks
            (block_index, event_type, content_item_id, copy_id, actor_id,
             content_hash, prev_copy_hash, timestamp, prev_block_hash, block_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            block_index, event_type, content_item_id, copy_id, actor_id,
            content_hash, prev_copy_hash, timestamp, prev_block_hash, block_hash,
        ),
    )


def _authenticators(db, content_item_id: int, content_hash: str):
    return db.execute(
        """
        SELECT content_copies.id AS copy_id, users.username AS username,
               content_copies.owner_id AS owner_id
        FROM content_copies
        JOIN users ON users.id = content_copies.owner_id
        WHERE content_copies.content_item_id = ? AND content_copies.content_hash = ?
        ORDER BY content_copies.created_at ASC
        """,
        (content_item_id, content_hash),
    ).fetchall()


@content_bp.route("/content")
def feed():
    db = get_db()
    items = db.execute(
        """
        SELECT cc.*, u.username AS owner_username, ci.kind AS kind
        FROM content_copies cc
        JOIN users u ON u.id = cc.owner_id
        JOIN content_items ci ON ci.id = cc.content_item_id
        WHERE cc.id IN (SELECT MIN(id) FROM content_copies GROUP BY content_item_id)
        ORDER BY cc.created_at DESC
        """
    ).fetchall()
    counts = {
        item["content_item_id"]: len(_authenticators(db, item["content_item_id"], item["content_hash"]))
        for item in items
    }
    return render_template("content_feed.html", items=items, counts=counts)


@content_bp.route("/content/new", methods=["GET", "POST"])
@login_required
def new_content():
    if request.method == "POST":
        kind = request.form.get("kind", "news")
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()

        error = None
        if kind not in ("news", "video"):
            error = "نوع المحتوى غير صالح."
        elif not (3 <= len(title) <= 200):
            error = "العنوان يجب أن يكون بين 3 و200 حرف."
        elif kind == "news" and not (10 <= len(body) <= 20000):
            error = "نص الخبر يجب أن يكون بين 10 و20000 حرف."
        elif kind == "video" and not (body.startswith("http://") or body.startswith("https://")):
            error = "رابط الفيديو يجب أن يبدأ بـ http:// أو https://"

        if error:
            return render_template("content_new.html", error=error, kind=kind, title=title, body=body)

        db = get_db()
        cursor = db.execute("INSERT INTO content_items (kind) VALUES (?)", (kind,))
        content_item_id = cursor.lastrowid
        content_hash = _hash_content(title, body)
        owner_id = session["user_id"]

        cursor = db.execute(
            """
            INSERT INTO content_copies
                (content_item_id, owner_id, title, body, content_hash, source_copy_id)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (content_item_id, owner_id, title, body, content_hash),
        )
        copy_id = cursor.lastrowid
        _append_block(
            db,
            event_type="create",
            content_item_id=content_item_id,
            copy_id=copy_id,
            actor_id=owner_id,
            content_hash=content_hash,
            prev_copy_hash=None,
        )
        db.commit()
        return redirect(url_for("content.view_copy", copy_id=copy_id))

    return render_template("content_new.html", error=None, kind="news", title="", body="")


@content_bp.route("/content/c/<int:copy_id>")
def view_copy(copy_id: int):
    db = get_db()
    copy = db.execute(
        """
        SELECT content_copies.*, content_items.kind AS kind, users.username AS owner_username
        FROM content_copies
        JOIN content_items ON content_items.id = content_copies.content_item_id
        JOIN users ON users.id = content_copies.owner_id
        WHERE content_copies.id = ?
        """,
        (copy_id,),
    ).fetchone()
    if copy is None:
        abort(404)

    authenticators = _authenticators(db, copy["content_item_id"], copy["content_hash"])

    my_copy = None
    if session.get("user_id"):
        my_copy = db.execute(
            "SELECT * FROM content_copies WHERE content_item_id = ? AND owner_id = ?",
            (copy["content_item_id"], session["user_id"]),
        ).fetchone()

    return render_template(
        "content_view.html",
        copy=copy,
        authenticators=authenticators,
        count=len(authenticators),
        my_copy=my_copy,
    )


@content_bp.route("/content/c/<int:copy_id>/authenticate", methods=["POST"])
@login_required
def authenticate(copy_id: int):
    db = get_db()
    source = db.execute("SELECT * FROM content_copies WHERE id = ?", (copy_id,)).fetchone()
    if source is None:
        abort(404)

    actor_id = session["user_id"]
    content_item_id = source["content_item_id"]

    if source["owner_id"] == actor_id:
        flash("هذا هو محتواك الخاص بالفعل.")
        return redirect(url_for("content.view_copy", copy_id=copy_id))

    existing = db.execute(
        "SELECT * FROM content_copies WHERE content_item_id = ? AND owner_id = ?",
        (content_item_id, actor_id),
    ).fetchone()

    if existing is not None:
        prev_hash = existing["content_hash"]
        db.execute(
            """
            UPDATE content_copies
            SET title = ?, body = ?, content_hash = ?, source_copy_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (source["title"], source["body"], source["content_hash"], copy_id, existing["id"]),
        )
        my_copy_id = existing["id"]
    else:
        prev_hash = None
        cursor = db.execute(
            """
            INSERT INTO content_copies
                (content_item_id, owner_id, title, body, content_hash, source_copy_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (content_item_id, actor_id, source["title"], source["body"], source["content_hash"], copy_id),
        )
        my_copy_id = cursor.lastrowid

    _append_block(
        db,
        event_type="authenticate",
        content_item_id=content_item_id,
        copy_id=my_copy_id,
        actor_id=actor_id,
        content_hash=source["content_hash"],
        prev_copy_hash=prev_hash,
    )
    db.commit()
    flash("تمت المصادقة على المحتوى ونسخه إلى حسابك.")
    return redirect(url_for("content.view_copy", copy_id=my_copy_id))


@content_bp.route("/content/c/<int:copy_id>/edit", methods=["GET", "POST"])
@login_required
def edit_copy(copy_id: int):
    db = get_db()
    copy = db.execute("SELECT * FROM content_copies WHERE id = ?", (copy_id,)).fetchone()
    if copy is None:
        abort(404)
    if copy["owner_id"] != session["user_id"]:
        abort(403)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()

        error = None
        if not (3 <= len(title) <= 200):
            error = "العنوان يجب أن يكون بين 3 و200 حرف."
        elif not body:
            error = "المحتوى لا يمكن أن يكون فارغًا."

        if error:
            return render_template("content_edit.html", error=error, copy=copy, title=title, body=body)

        new_hash = _hash_content(title, body)
        prev_hash = copy["content_hash"]

        db.execute(
            """
            UPDATE content_copies
            SET title = ?, body = ?, content_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, body, new_hash, copy_id),
        )
        _append_block(
            db,
            event_type="edit",
            content_item_id=copy["content_item_id"],
            copy_id=copy_id,
            actor_id=session["user_id"],
            content_hash=new_hash,
            prev_copy_hash=prev_hash,
        )
        db.commit()

        if new_hash == prev_hash:
            flash("لم يتغيّر شيء.")
        elif new_hash != prev_hash and prev_hash is not None:
            flash("تحديث المحتوى: إذا لم يعد مطابقًا للنسخة الأصلية فسيفقد عدد المصادقات.")

        return redirect(url_for("content.view_copy", copy_id=copy_id))

    return render_template("content_edit.html", error=None, copy=copy, title=copy["title"], body=copy["body"])


@content_bp.route("/content/c/<int:copy_id>/cancel", methods=["POST"])
@login_required
def cancel_copy(copy_id: int):
    db = get_db()
    copy = db.execute("SELECT * FROM content_copies WHERE id = ?", (copy_id,)).fetchone()
    if copy is None:
        abort(404)
    if copy["owner_id"] != session["user_id"]:
        abort(403)

    content_item_id = copy["content_item_id"]
    prev_hash = copy["content_hash"]

    # detach any copies that were authenticated FROM this one so the delete
    # below doesn't violate the source_copy_id foreign key
    db.execute("UPDATE content_copies SET source_copy_id = NULL WHERE source_copy_id = ?", (copy_id,))
    db.execute("DELETE FROM content_copies WHERE id = ?", (copy_id,))

    _append_block(
        db,
        event_type="cancel",
        content_item_id=content_item_id,
        copy_id=copy_id,
        actor_id=session["user_id"],
        content_hash="",
        prev_copy_hash=prev_hash,
    )
    db.commit()
    flash("تم إلغاء نسختك من هذا المحتوى.")

    remaining = db.execute(
        "SELECT id FROM content_copies WHERE content_item_id = ? ORDER BY id LIMIT 1",
        (content_item_id,),
    ).fetchone()
    if remaining:
        return redirect(url_for("content.view_copy", copy_id=remaining["id"]))
    return redirect(url_for("content.feed"))


@content_bp.route("/ledger")
def ledger():
    db = get_db()
    blocks = db.execute("SELECT * FROM ledger_blocks ORDER BY block_index ASC").fetchall()

    valid_chain = True
    prev_block_hash = GENESIS_PREV_HASH
    verified = []
    for block in blocks:
        payload = _block_payload(
            block["block_index"], block["event_type"], block["content_item_id"], block["copy_id"],
            block["actor_id"], block["content_hash"], block["prev_copy_hash"], block["timestamp"],
            block["prev_block_hash"],
        )
        recomputed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        ok = recomputed == block["block_hash"] and block["prev_block_hash"] == prev_block_hash
        if not ok:
            valid_chain = False
        prev_block_hash = block["block_hash"]
        verified.append({"block": block, "ok": ok})

    return render_template("ledger.html", blocks=verified, valid_chain=valid_chain)
