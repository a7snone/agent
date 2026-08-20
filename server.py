"""Flask web server exposing the agent through a simple browser chat UI.

Run:
    python server.py

Then open http://localhost:5000
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory

from agent import Agent

app = Flask(__name__, static_folder="static", static_url_path="")

# One Agent (and its conversation history) per browser session. In-memory and
# per-process, which is fine for local/dev use; swap for a real session store
# before deploying anywhere with multiple workers or persistence needs.
_sessions: dict[str, Agent] = {}


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    message = (data.get("message") or "").strip()

    if not session_id or not message:
        return jsonify({"error": "session_id and message are required"}), 400

    agent = _sessions.setdefault(session_id, Agent())
    try:
        reply = agent.send(message)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"reply": reply})


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set the ANTHROPIC_API_KEY environment variable first (see .env.example).")
    app.run(debug=True, port=5000)
