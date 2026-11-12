from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

log = logging.getLogger("orbe.inference")


class ModelUnavailableError(Exception):
    """Modelo não pôde ser carregado (pacote ausente, pesos inexistentes, sem rede para baixar...)."""


class InferenceError(Exception):
    """Falha durante a execução do modelo."""


def normalize_class(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(name).strip().lower())


@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: list
    category: str = "other"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = round(float(self.confidence), 4)
        d["bbox"] = [round(float(v), 1) for v in self.bbox]
        return d


@dataclass
class InferenceResult:
    detections: list[Detection]
    inference_ms: float
    model_name: str
    model_mode: str
    imgsz: int


class Detector:

    name: str = "detector"

    def info(self) -> dict:
        raise NotImplementedError

    def class_names(self) -> list[str]:
        raise NotImplementedError

    def detect(self, bgr: np.ndarray) -> list[tuple[int, str, float, list]]:
        raise NotImplementedError


class UltralyticsDetector(Detector):
    def __init__(self, model_path: Path, fallback_model: str, family: str = "yolo",
                 imgsz: int = 640, device: str | None = None,
                 conf: float = 0.25, iou: float = 0.5, agnostic_nms: bool = True):
        self.model_path = Path(model_path)
        self.fallback_model = fallback_model
        self.family = family
        self.imgsz = imgsz
        self.device = device
        self.conf = conf
        self.iou = iou
        self.agnostic_nms = agnostic_nms
        self.name = "não carregado"
        self.source = ""
        self._model = None
        self._lock = threading.Lock()
        self._error: str | None = None


    def _resolve_weights(self) -> tuple[str, str]:
        if self.model_path.is_file():
            return str(self.model_path), "customizado"
        fb = Path(self.fallback_model)
        if fb.is_file():
            return str(fb), "genérico (COCO)"

        local = self.model_path.parent / self.fallback_model
        local.parent.mkdir(parents=True, exist_ok=True)
        return str(local), "genérico (COCO)"

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                if self.family == "rtdetr":
                    from ultralytics import RTDETR as ModelClass
                else:
                    from ultralytics import YOLO as ModelClass
            except ImportError as exc:
                self._error = "Pacote 'ultralytics' não instalado (pip install -r requirements.txt)."
                raise ModelUnavailableError(self._error) from exc
            weights, source = self._resolve_weights()
            try:
                log.info("Carregando modelo: %s (%s)", weights, source)
                self._model = ModelClass(weights)
                self.name = Path(weights).name
                self.source = source
                self._error = None
            except Exception as exc:
                self._error = f"Falha ao carregar o modelo '{Path(weights).name}': {exc}"
                log.error(self._error)
                raise ModelUnavailableError(self._error) from exc


    def info(self) -> dict:
        return {
            "loaded": self._model is not None,
            "name": self.name,
            "source": self.source,
            "family": self.family,
            "imgsz": self.imgsz,
            "error": self._error,
        }

    def class_names(self) -> list[str]:
        if self._model is None:
            return []
        names = self._model.names
        return [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)

    def detect(self, bgr: np.ndarray):
        self.load()
        try:
            kwargs = dict(source=bgr, imgsz=self.imgsz, conf=self.conf, iou=self.iou,
                          agnostic_nms=self.agnostic_nms, verbose=False)
            if self.device:
                kwargs["device"] = self.device
            res = self._model.predict(**kwargs)[0]
            names = res.names
            boxes = res.boxes
            if boxes is None or len(boxes) == 0:
                return []
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            clss = boxes.cls.cpu().numpy().astype(int)
            return [(int(c), names[int(c)], float(p), [float(v) for v in b])
                    for b, p, c in zip(xyxy, confs, clss)]
        except ModelUnavailableError:
            raise
        except Exception as exc:
            log.exception("Erro durante a inferência")
            raise InferenceError(f"Erro durante a execução do modelo: {exc}") from exc


def categorize(class_name: str, classes_cfg: dict) -> str:
    n = normalize_class(class_name)
    for cat in ("accident", "vehicle", "vulnerable"):
        if n in {normalize_class(c) for c in classes_cfg.get(cat, [])}:
            return cat
    return "other"


def detect_model_mode(class_names: list[str], classes_cfg: dict) -> str:
    acc = {normalize_class(c) for c in classes_cfg.get("accident", [])}
    return "accident" if any(normalize_class(n) in acc for n in class_names) else "generic"


def run_inference(detector: Detector, bgr: np.ndarray, classes_cfg: dict, imgsz: int) -> InferenceResult:
    t0 = time.perf_counter()
    raw = detector.detect(bgr)
    elapsed = (time.perf_counter() - t0) * 1000
    dets = [Detection(cid, name, conf, bbox, categorize(name, classes_cfg)) for cid, name, conf, bbox in raw]
    dets.sort(key=lambda d: d.confidence, reverse=True)
    mode = detect_model_mode(detector.class_names(), classes_cfg)
    return InferenceResult(dets, round(elapsed, 1), detector.info().get("name", detector.name), mode, imgsz)
