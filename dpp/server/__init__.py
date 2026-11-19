"""The server: stores the snapshots and inputs a client uploads, and lets an admin approve clients.

Two kinds of callers:
  * the admin, in a browser, authenticated with the server password (HTTP Basic);
  * game clients, which register themselves, wait until the admin accepts them
    and from then on authenticate with the token they got at registration.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, url_for

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PENDING_CLIENTS = 20  # registration needs no password, so bound what strangers can queue up
SNAPSHOTS_SHOWN = 50

_SNAPSHOT_ID = re.compile(r"[0-9a-f]{32}")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL,                 -- shown on the client's screen and in the admin page
    token_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, accepted, rejected, replaced
    start_snapshot TEXT,                -- what the admin told this client to continue from
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,  -- arrival order
    id TEXT NOT NULL UNIQUE,                -- chosen by the client
    parent_id TEXT,                         -- the snapshot this one was played on from, if known
    client_id INTEGER NOT NULL REFERENCES clients (id),
    created_at TEXT NOT NULL,
    frame INTEGER NOT NULL,
    metadata TEXT NOT NULL,                 -- JSON
    state BLOB NOT NULL                     -- zlib-compressed emulator state
);
-- The key mask changes between a snapshot's parent and the snapshot itself.
CREATE TABLE IF NOT EXISTS inputs (
    snapshot_seq INTEGER NOT NULL REFERENCES snapshots (seq),
    frame INTEGER NOT NULL,
    keys INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS inputs_by_snapshot ON inputs (snapshot_seq);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # UTC


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_app(database: str | Path, password: str) -> Flask:
    if not password:
        raise ValueError("the server needs a password")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    with connect() as connection:
        connection.executescript(_SCHEMA)

    @app.before_request
    def open_database() -> None:
        g.db = connect()

    @app.teardown_request
    def close_database(error) -> None:
        g.db.close()

    def admin(view):
        """Require the server password; for POSTs also that the request comes from our own pages."""

        @wraps(view)
        def wrapper(*args, **kwargs):
            auth = request.authorization
            given = auth.password if auth and auth.type == "basic" and auth.password else ""
            if not hmac.compare_digest(given.encode(), password.encode()):
                return Response("Password required.", 401, {"WWW-Authenticate": 'Basic realm="DECT plays Pokemon"'})
            # Browsers attach the password to cross-site form posts too, so refuse those.
            if request.method == "POST" and request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    def client(*, accepted: bool):
        """Require a registered client's token; with accepted=True the admin must have accepted it."""

        def decorator(view):
            @wraps(view)
            def wrapper(*args, **kwargs):
                scheme, _, token = request.headers.get("Authorization", "").partition(" ")
                row = g.db.execute("SELECT * FROM clients WHERE token_hash = ?", (_hash(token),)).fetchone()
                if scheme != "Bearer" or row is None:
                    abort(401)
                if accepted and row["status"] != "accepted":
                    abort(403)
                with g.db:
                    g.db.execute("UPDATE clients SET last_seen_at = ? WHERE id = ?", (_now(), row["id"]))
                g.client = row
                return view(*args, **kwargs)

            return wrapper

        return decorator

    def state_response(snapshot_id: str) -> Response:
        row = g.db.execute("SELECT state FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if row is None:
            abort(404)
        return Response(row["state"], mimetype="application/octet-stream")

    # ---- admin pages -------------------------------------------------------

    @app.get("/")
    @admin
    def index():
        snapshots = []
        query = """
            SELECT s.*, c.name AS client_name,
                   (SELECT COUNT(*) FROM inputs i WHERE i.snapshot_seq = s.seq AND i.keys != 0) AS presses
            FROM snapshots s JOIN clients c ON c.id = s.client_id ORDER BY s.seq DESC LIMIT ?"""
        for row in g.db.execute(query, (SNAPSHOTS_SHOWN,)):
            snapshots.append(dict(row) | {"metadata": json.loads(row["metadata"])})
        totals = g.db.execute(
            "SELECT (SELECT COUNT(*) FROM snapshots) AS snapshots, (SELECT COUNT(*) FROM inputs WHERE keys != 0) AS presses"
        ).fetchone()
        return render_template(
            "admin.html",
            pending=g.db.execute("SELECT * FROM clients WHERE status = 'pending' ORDER BY id").fetchall(),
            active=g.db.execute("SELECT * FROM clients WHERE status = 'accepted'").fetchone(),
            snapshots=snapshots,
            totals=totals,
        )

    @app.post("/clients/<int:client_id>/accept")
    @admin
    def accept(client_id: int):
        start = request.form.get("snapshot") or None
        if start is not None and g.db.execute("SELECT 1 FROM snapshots WHERE id = ?", (start,)).fetchone() is None:
            abort(400, "no such snapshot")
        with g.db:
            # Only one client plays at a time; a previously accepted one may no longer upload.
            g.db.execute("UPDATE clients SET status = 'replaced' WHERE status = 'accepted'")
            changed = g.db.execute(
                "UPDATE clients SET status = 'accepted', start_snapshot = ? WHERE id = ? AND status = 'pending'",
                (start, client_id),
            ).rowcount
            if not changed:
                abort(404)  # leaving the block with an exception rolls the first update back
        return redirect(url_for("index"))

    @app.post("/clients/<int:client_id>/reject")
    @admin
    def reject(client_id: int):
        with g.db:
            g.db.execute("UPDATE clients SET status = 'rejected' WHERE id = ? AND status = 'pending'", (client_id,))
        return redirect(url_for("index"))

    @app.get("/snapshots/<snapshot_id>/state")
    @admin
    def download_state(snapshot_id: str):
        response = state_response(snapshot_id)
        response.headers["Content-Disposition"] = f'attachment; filename="{snapshot_id}.state.z"'
        return response

    # ---- client API --------------------------------------------------------

    @app.post("/api/clients")
    def register():
        body = request.get_json(silent=True)
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            abort(400, "name must be 1 to 64 characters")
        pending = g.db.execute("SELECT COUNT(*) FROM clients WHERE status = 'pending'").fetchone()[0]
        if pending >= MAX_PENDING_CLIENTS:
            abort(429, "too many clients are waiting for approval")
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(10000):04d}"
        with g.db:
            g.db.execute(
                "INSERT INTO clients (name, code, token_hash, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
                (name, code, _hash(token), _now(), _now()),
            )
        return jsonify(token=token, code=code), 201

    @app.get("/api/client")
    @client(accepted=False)
    def client_status():
        return jsonify(status=g.client["status"], start_snapshot=g.client["start_snapshot"])

    @app.get("/api/snapshots/<snapshot_id>/state")
    @client(accepted=True)
    def client_state(snapshot_id: str):
        return state_response(snapshot_id)

    @app.put("/api/snapshots/<snapshot_id>")
    @client(accepted=True)
    def upload(snapshot_id: str):
        body = request.get_json(silent=True)
        try:
            parent, frame, metadata, inputs = body["parent"], body["frame"], body["metadata"], body["inputs"]
            state = base64.b64decode(body["state"], validate=True)
            valid = (
                _SNAPSHOT_ID.fullmatch(snapshot_id)
                and (parent is None or (isinstance(parent, str) and _SNAPSHOT_ID.fullmatch(parent)))
                and type(frame) is int
                and frame >= 0
                and isinstance(metadata, dict)
                and state
                and isinstance(inputs, list)
                and all(type(f) is int and type(k) is int and f >= 0 and 0 <= k < 1024 for f, k in inputs)
            )
        except (KeyError, TypeError, ValueError, binascii.Error):
            valid = False
        if not valid:
            abort(400, "malformed snapshot")
        if g.db.execute("SELECT 1 FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone():
            return jsonify(stored=True)  # a retried upload
        with g.db:
            seq = g.db.execute(
                "INSERT INTO snapshots (id, parent_id, client_id, created_at, frame, metadata, state) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, parent, g.client["id"], _now(), frame, json.dumps(metadata), state),
            ).lastrowid
            g.db.executemany("INSERT INTO inputs VALUES (?, ?, ?)", ((seq, f, k) for f, k in inputs))
        return jsonify(stored=True), 201

    return app
