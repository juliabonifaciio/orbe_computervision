from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from database import db
from database.models import DECISION_LABELS

bp = Blueprint("history", __name__)


@bp.get("/history")
def history_page():
    return render_template("history.html", active="history", review=False)


@bp.get("/review")
def review_page():
    return render_template("history.html", active="review", review=True)


@bp.get("/api/history")
def api_history():
    a = request.args
    rows = db.list_analyses(
        result=a.get("result") or None, status=a.get("status") or None,
        date_from=a.get("date_from") or None, date_to=a.get("date_to") or None,
        q=(a.get("q") or "").strip() or None, review_only=a.get("review") == "1",
        limit=min(int(a.get("limit", 200) or 200), 500))
    slim = [{k: r[k] for k in ("id", "image_name", "source", "created_at", "result", "situation_type",
                               "confidence", "detection_count", "classes", "inference_ms", "notify",
                               "validation_status", "model_mode", "evidence_level", "operator", "triage", "dispatch_status",
                               "stored_name", "processed_name")} for r in rows]
    return jsonify({"ok": True, "items": slim, "count": len(slim), "labels": DECISION_LABELS})


@bp.get("/api/stats")
def api_stats():
    return jsonify({"ok": True, "stats": db.dashboard_stats()})
