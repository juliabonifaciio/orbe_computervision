from __future__ import annotations

import re

from flask import Blueprint, current_app, jsonify, render_template, send_from_directory, abort

from database import db

bp = Blueprint("main", __name__)
_FILE_RE = re.compile(r"^ORBE-\d{8}-[0-9A-F]{6}\.(jpg|png)$")


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", stats=db.dashboard_stats(),
                           recent=db.list_analyses(limit=6), active="dashboard")


@bp.get("/settings")
def settings():
    svc = current_app.extensions["orbe_service"]
    return render_template("settings.html", rules=svc.rules, cfg=current_app.config,
                           detector=svc.detector.info(), llm=svc.llm, active="settings")


@bp.get("/api/health")
def health():
    svc = current_app.extensions["orbe_service"]
    info = svc.detector.info()
    if info["error"]:
        state, label = "error", "Modelo indisponível"
    elif info["loaded"]:
        state, label = "ok", "Sistema operacional"
    else:
        state, label = "idle", "Modelo será carregado na 1ª análise"
    return jsonify({"state": state, "label": label, "model": info,
                    "pending_review": db.dashboard_stats()["awaiting"]})


@bp.get("/media/<kind>/<filename>")
def media(kind: str, filename: str):
    if kind not in ("uploads", "processed") or not _FILE_RE.match(filename):
        abort(404)
    folder = current_app.config["UPLOAD_DIR" if kind == "uploads" else "PROCESSED_DIR"]
    return send_from_directory(folder, filename, max_age=0)
