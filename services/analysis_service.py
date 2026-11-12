from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from database import db
from . import image_processing as ip
from .inference import Detector, InferenceError, ModelUnavailableError, run_inference
from .occurrence_classifier import classify, load_rules
from .llm_service import LLMService
from .aph_triage import make_triage

log = logging.getLogger("orbe.analysis")


class AnalysisService:
    def __init__(self, cfg, detector: Detector, llm: LLMService):
        self.cfg = cfg
        self.detector = detector
        self.llm = llm
        self.rules = load_rules(Path(cfg["RULES_PATH"]))
        self.rules_version = f"rules.json@{int(Path(cfg['RULES_PATH']).stat().st_mtime)}"

    def analyze(self, file_storage, source: str | None = None) -> dict:
        t_total = time.perf_counter()
        cfg = self.cfg

        original_name, ext = ip.validate_upload(file_storage, cfg["ALLOWED_EXTENSIONS"])
        analysis_id = ip.new_analysis_id()
        created_at = ip.utc_now_iso()
        stored = ip.save_upload(file_storage, Path(cfg["UPLOAD_DIR"]), analysis_id, ext)
        try:

            prepared = ip.load_and_prepare(
                stored, max_pixels=cfg["MAX_IMAGE_PIXELS"], min_side=cfg["MIN_IMAGE_SIDE"],
                max_side=cfg["MAX_ANALYSIS_SIDE"], imgsz=cfg["IMGSZ"])
        except ip.ImageValidationError:
            stored.unlink(missing_ok=True)
            raise


        try:
            inf = run_inference(self.detector, prepared.bgr, self.rules["classes"], cfg["IMGSZ"])
        except (ModelUnavailableError, InferenceError):
            stored.unlink(missing_ok=True)
            raise


        det_dicts = [d.to_dict() for d in inf.detections]
        cls = classify(det_dicts, (prepared.width, prepared.height), prepared.quality, inf.model_mode, self.rules)

        for i, d in enumerate(det_dicts):
            d["is_evidence"] = i in cls.evidence_indices


        annotated = ip.draw_detections(prepared.bgr, det_dicts, set(cls.evidence_indices))
        processed_name = f"{analysis_id}.jpg"
        ip.save_jpeg(annotated, Path(cfg["PROCESSED_DIR"]) / processed_name)

        triage = make_triage(cls.result, det_dicts, self.rules)
        classes = sorted({d["class_name"] for d in det_dicts})
        total_ms = round((time.perf_counter() - t_total) * 1000, 1)
        record = {
            "id": analysis_id, "image_name": original_name, "stored_name": stored.name,
            "processed_name": processed_name, "source": (source or "").strip()[:120] or None,
            "created_at": created_at, "result": cls.result, "situation_type": cls.situation_type,
            "evidence_level": cls.evidence_level, "confidence": cls.confidence,
            "detections_json": json.dumps(det_dicts), "detection_count": len(det_dicts),
            "classes_json": json.dumps(classes), "reasons_json": json.dumps(cls.reasons, ensure_ascii=False),
            "quality_json": json.dumps(prepared.quality), "image_width": prepared.width,
            "image_height": prepared.height, "inference_ms": inf.inference_ms, "total_ms": total_ms,
            "notify": int(cls.notify), "requires_review": int(cls.requires_review),
            "model_name": inf.model_name, "model_mode": inf.model_mode, "rules_version": self.rules_version,
            "triage_json": json.dumps(triage, ensure_ascii=False),
        }
        db.insert_analysis(record)
        log.info("Análise %s: resultado=%s detecções=%d inferência=%.0fms",
                 analysis_id, cls.result, len(det_dicts), inf.inference_ms)

        out = db.get_analysis(analysis_id)
        out["llm_summary"] = self.llm.summarize(out)
        return out
