from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from services import image_processing as ip
from services.inference import run_inference
from services.occurrence_classifier import classify


def evaluate(rows, predict):
    y_true, y_pred, states, times = [], [], [], []
    for path, label in rows:
        state, ms = predict(path)
        y_true.append(1 if label == "ocorrencia" else 0)
        y_pred.append(1 if state == "possible" else 0)
        states.append(state)
        times.append(ms)
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist()
    return {
        "n_imagens": len(rows), "precisao": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f1), 4),
        "matriz_confusao": {"labels": ["normal", "ocorrencia"], "linhas_verdade_colunas_predicao": cm},
        "estados": {s: states.count(s) for s in ("possible", "none", "inconclusive")},
        "inferencia_ms": {"media": round(statistics.mean(times), 1), "mediana": round(statistics.median(times), 1),
                          "max": round(max(times), 1)} if times else None,
    }


def main():
    from app import create_app
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--labels", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path("avaliacao.json"))
    a = ap.parse_args()
    app = create_app({"WARMUP_ON_START": False})
    svc = app.extensions["orbe_service"]
    cfg = app.config
    with open(a.labels, encoding="utf-8") as fh:
        rows = [(a.images / r["arquivo"], r["rotulo"].strip().lower()) for r in csv.DictReader(fh)]
    if not rows:
        sys.exit("Arquivo de rótulos vazio.")

    def predict(path):
        prep = ip.load_and_prepare(path, max_pixels=cfg["MAX_IMAGE_PIXELS"], min_side=cfg["MIN_IMAGE_SIDE"],
                                   max_side=cfg["MAX_ANALYSIS_SIDE"], imgsz=cfg["IMGSZ"])
        inf = run_inference(svc.detector, prep.bgr, svc.rules["classes"], cfg["IMGSZ"])
        res = classify([d.to_dict() for d in inf.detections], (prep.width, prep.height), prep.quality,
                       inf.model_mode, svc.rules)
        return res.result, inf.inference_ms

    t0 = time.time()
    out = evaluate(rows, predict)
    out["modelo"] = svc.detector.info()["name"]
    out["duracao_s"] = round(time.time() - t0, 1)
    a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
