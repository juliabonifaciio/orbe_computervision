from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, render_template, request

from config import Config
from database import db
from routes import analysis_routes, history_routes, main_routes
from services.analysis_service import AnalysisService
from services.inference import ModelUnavailableError, UltralyticsDetector
from services.llm_service import LLMService
from services.occurrence_classifier import load_rules


def _setup_logging(app: Flask) -> None:
    app.config["LOG_DIR"].mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(app.config["LOG_DIR"] / "orbe.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("orbe")
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(fh)
        root.addHandler(logging.StreamHandler())


def create_app(overrides: dict | None = None, detector=None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    for d in ("UPLOAD_DIR", "PROCESSED_DIR"):
        app.config[d].mkdir(parents=True, exist_ok=True)
    _setup_logging(app)
    db.init_app(app)

    rules = load_rules(app.config["RULES_PATH"])
    if detector is None:
        inf = rules["inference"]
        detector = UltralyticsDetector(
            app.config["MODEL_PATH"], app.config["FALLBACK_MODEL"], app.config["MODEL_FAMILY"],
            app.config["IMGSZ"], app.config["DEVICE"], inf["min_detection_confidence"],
            inf["nms_iou"], inf["agnostic_nms"])
    llm = LLMService(app.config["LLM_PROVIDER"], app.config["LLM_BASE_URL"],
                     app.config["LLM_API_KEY"], app.config["LLM_MODEL"])
    app.extensions["orbe_service"] = AnalysisService(app.config, detector, llm)

    for mod in (main_routes, analysis_routes, history_routes):
        app.register_blueprint(mod.bp)

    @app.errorhandler(413)
    def too_large(_e):
        msg = f"Arquivo maior que o limite de {app.config['MAX_UPLOAD_MB']} MB."
        return jsonify({"ok": False, "error": {"code": "too_large", "message": msg}}), 413

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"code": "not_found", "message": "Recurso não encontrado."}}), 404
        return render_template("error.html", code=404, message="Página não encontrada.", active=""), 404

    @app.errorhandler(500)
    def server_error(_e):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"code": "internal_error", "message": "Erro interno."}}), 500
        return render_template("error.html", code=500, message="Erro interno do servidor.", active=""), 500

    if app.config["WARMUP_ON_START"] and not app.config["TESTING"] and hasattr(detector, "load"):
        def _warm():
            try:
                detector.load()
            except ModelUnavailableError:
                pass
        threading.Thread(target=_warm, daemon=True).start()
    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
