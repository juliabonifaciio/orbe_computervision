from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from database import db
from database.models import DECISION_LABELS, DISPATCH_LABELS, OCCURRENCE_TYPES
from services.image_processing import ImageValidationError, is_valid_analysis_id, utc_now_iso
from services.inference import InferenceError, ModelUnavailableError

bp = Blueprint("analysis", __name__)
log = logging.getLogger("orbe.routes")


def _err(message: str, code: str, status: int):
    return jsonify({"ok": False, "error": {"code": code, "message": message}}), status


@bp.get("/analysis")
def analysis_page():
    return render_template("analysis.html", active="analysis", types=OCCURRENCE_TYPES,
                           max_mb=current_app.config["MAX_UPLOAD_MB"])


@bp.get("/analysis/<analysis_id>")
def analysis_detail(analysis_id: str):
    if not is_valid_analysis_id(analysis_id) or db.get_analysis(analysis_id) is None:
        return render_template("error.html", code=404, message="Análise não encontrada.", active=""), 404
    return render_template("detail.html", analysis_id=analysis_id, active="history", types=OCCURRENCE_TYPES)


@bp.post("/api/analyze")
def api_analyze():
    svc = current_app.extensions["orbe_service"]
    try:
        result = svc.analyze(request.files.get("image"), request.form.get("source"))
        return jsonify({"ok": True, "analysis": result}), 201
    except ImageValidationError as e:
        return _err(e.message, e.code, 400)
    except ModelUnavailableError as e:
        log.error("Modelo indisponível: %s", e)
        return _err(f"O modelo de visão computacional está indisponível. {e}", "model_unavailable", 503)
    except InferenceError as e:
        return _err(str(e), "inference_error", 500)
    except HTTPException:
        raise
    except Exception:
        log.exception("Erro inesperado na análise")
        return _err("Erro interno ao processar a imagem. Consulte o log do servidor.", "internal_error", 500)


@bp.get("/api/analyses/<analysis_id>")
def api_get(analysis_id: str):
    if not is_valid_analysis_id(analysis_id):
        return _err("Identificador inválido.", "bad_id", 400)
    a = db.get_analysis(analysis_id)
    if a is None:
        return _err("Análise não encontrada.", "not_found", 404)
    svc = current_app.extensions["orbe_service"]
    a["llm_summary"] = svc.llm.summarize(a)
    a["decision_labels"] = DECISION_LABELS
    a["dispatch_labels"] = DISPATCH_LABELS
    return jsonify({"ok": True, "analysis": a})


@bp.post("/api/analyses/<analysis_id>/decision")
def api_decision(analysis_id: str):
    if not is_valid_analysis_id(analysis_id):
        return _err("Identificador inválido.", "bad_id", 400)
    body = request.get_json(silent=True) or {}
    try:
        a = db.record_decision(
            analysis_id, str(body.get("decision", "")), operator=body.get("operator"),
            notes=body.get("notes"), corrected_type=body.get("corrected_type"), now_iso=utc_now_iso())
    except db.DecisionError as e:
        status = 404 if e.code == "not_found" else 409 if e.code in ("already_final", "not_reviewable") else 400
        return _err(e.message, e.code, status)
    a["decision_labels"] = DECISION_LABELS
    a["dispatch_labels"] = DISPATCH_LABELS
    return jsonify({"ok": True, "analysis": a})


@bp.post("/api/analyses/<analysis_id>/dispatch")
def api_dispatch(analysis_id: str):
    if not is_valid_analysis_id(analysis_id):
        return _err("Identificador inválido.", "bad_id", 400)
    body = request.get_json(silent=True) or {}
    try:
        a = db.add_dispatch_event(analysis_id, str(body.get("status", "")), body.get("operator"), utc_now_iso())
    except db.DecisionError as e:
        status = 404 if e.code == "not_found" else 409 if e.code in ("not_confirmed", "bad_step") else 400
        return _err(e.message, e.code, status)
    a["decision_labels"] = DECISION_LABELS
    a["dispatch_labels"] = DISPATCH_LABELS
    return jsonify({"ok": True, "analysis": a})
