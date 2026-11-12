from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

POSSIBLE, NONE, INCONCLUSIVE = "possible", "none", "inconclusive"
RESULT_LABELS = {
    POSSIBLE: "Possível ocorrência identificada",
    NONE: "Nenhuma ocorrência identificada",
    INCONCLUSIVE: "Resultado inconclusivo",
}


@dataclass
class ClassificationResult:
    result: str
    situation_type: str
    confidence: float | None
    notify: bool
    requires_review: bool
    evidence_level: str
    evidence_indices: list[int] = field(default_factory=list)
    reasons: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        return RESULT_LABELS[self.result]


def load_rules(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def iou(a, b) -> float:
    i = _inter(a, b)
    u = _area(a) + _area(b) - i
    return i / u if u > 0 else 0.0


def _r(rule: str, text: str) -> dict:
    return {"rule": rule, "text": text}


def quality_ok(quality: dict, q_rules: dict) -> tuple[bool, str]:
    lap = quality.get("laplacian_variance")
    br = quality.get("mean_brightness")
    if lap is not None and lap < q_rules["min_laplacian_variance"]:
        return False, f"imagem pouco nítida (variância do Laplaciano {lap} < {q_rules['min_laplacian_variance']})"
    if br is not None and br < q_rules["min_mean_brightness"]:
        return False, f"imagem muito escura (brilho médio {br} < {q_rules['min_mean_brightness']})"
    if br is not None and br > q_rules["max_mean_brightness"]:
        return False, f"imagem muito clara/estourada (brilho médio {br} > {q_rules['max_mean_brightness']})"
    return True, ""


def classify(detections: list, image_size: tuple[int, int], quality: dict,
             model_mode: str, rules: dict) -> ClassificationResult:
    dets = [_as_obj(d) for d in detections]
    notif = rules["notification"]
    q_ok, q_msg = quality_ok(quality or {}, rules["quality"])

    if model_mode == "accident":
        res = _classify_accident_model(dets, image_size, rules["accident_model"])
    else:
        res = _classify_generic_model(dets, rules["generic_model"])

    if res is None:
        res = _no_trigger(dets, q_ok, q_msg, model_mode)

    res.notify = res.result in notif["notify_on"]
    res.requires_review = res.result in notif["review_on"]
    if res.result == POSSIBLE and not q_ok:
        res.reasons.append(_r("Q1", f"Atenção: {q_msg}; confirme visualmente."))
    return res


class _D:
    def __init__(self, d):
        self.class_name, self.confidence = d["class_name"], d["confidence"]
        self.bbox, self.category = d["bbox"], d.get("category", "other")


def _as_obj(d):
    return _D(d) if isinstance(d, dict) else d


def _no_trigger(dets, q_ok, q_msg, mode) -> ClassificationResult:
    vehicles = [d for d in dets if d.category == "vehicle"]
    if not q_ok:
        return ClassificationResult(INCONCLUSIVE, "Imagem com qualidade insuficiente", None, False, True,
                                    "sem_evidencia", [], [_r("Q1", f"Qualidade insuficiente: {q_msg}.")])
    if not dets:
        return ClassificationResult(INCONCLUSIVE, "Nenhum objeto relevante detectado", None, False, True,
                                    "sem_evidencia", [],
                                    [_r("N0", "O modelo não detectou nenhum objeto; não é possível afirmar que a cena é normal.")])
    if not vehicles:
        return ClassificationResult(INCONCLUSIVE, "Cena sem veículos detectados", None, False, True,
                                    "sem_evidencia", [],
                                    [_r("N1", "Há detecções, mas nenhum veículo; a cena não pôde ser avaliada.")])
    txt = ("Nenhuma classe de acidente detectada com confiança suficiente." if mode == "accident"
           else "Nenhum indício geométrico (sobreposição forte entre veículos) encontrado. "
                "Modelo genérico: isto não comprova a ausência de acidente.")
    return ClassificationResult(NONE, "Nenhum indício identificado", None, False, False, "sem_evidencia", [],
                                [_r("N2", f"{len(vehicles)} veículo(s) detectado(s). {txt}")])


def _classify_accident_model(dets, image_size, r) -> ClassificationResult | None:
    W, H = image_size
    img_area = float(W * H) or 1.0
    acc = [(i, d) for i, d in enumerate(dets) if d.category == "accident"]
    vehicles = [d for d in dets if d.category == "vehicle"]
    solid = [(i, d) for i, d in acc
             if d.confidence >= r["possible_min_confidence"] and _area(d.bbox) / img_area >= r["min_box_area_ratio"]]
    if solid:
        best_i, best = max(solid, key=lambda t: t[1].confidence)
        touching = any(_inter(best.bbox, v.bbox) > 0 for v in vehicles)
        strong = best.confidence >= r["strong_confidence"]
        multi = len(solid) >= 2
        if strong or touching or multi:
            why = ("confiança alta" if strong else "veículo detectado sobreposto à região" if touching
                   else "múltiplas detecções de acidente")
            return ClassificationResult(
                POSSIBLE, f"Possível {best.class_name.replace('_', ' ')}", round(best.confidence, 3),
                True, True, "modelo_de_acidentes", [i for i, _ in solid],
                [_r("A1", f"Classe de acidente '{best.class_name}' com confiança {best.confidence:.0%} "
                          f"(mín. {r['possible_min_confidence']:.0%}), área ≥ {r['min_box_area_ratio']:.1%} da imagem; "
                          f"corroboração: {why}.")])
        return ClassificationResult(
            INCONCLUSIVE, f"Indício de {best.class_name.replace('_', ' ')} sem corroboração",
            round(best.confidence, 3), False, True, "modelo_de_acidentes", [best_i],
            [_r("A2", f"Classe '{best.class_name}' com {best.confidence:.0%}, porém sem corroboração "
                      f"(confiança < {r['strong_confidence']:.0%}, sem veículo sobreposto, detecção única).")])
    weak = [(i, d) for i, d in acc if d.confidence >= r["inconclusive_min_confidence"]]
    if weak:
        best_i, best = max(weak, key=lambda t: t[1].confidence)
        return ClassificationResult(
            INCONCLUSIVE, f"Indício fraco de {best.class_name.replace('_', ' ')}", round(best.confidence, 3),
            False, True, "modelo_de_acidentes", [best_i],
            [_r("A3", f"Classe '{best.class_name}' com {best.confidence:.0%}: abaixo do limiar de "
                      f"{r['possible_min_confidence']:.0%} ou com área muito pequena.")])
    return None


def _classify_generic_model(dets, r) -> ClassificationResult | None:
    vehicles = [(i, d) for i, d in enumerate(dets)
                if d.category == "vehicle" and d.confidence >= r["min_vehicle_confidence"]]
    strong, weak = [], []
    for (i, a), (j, b) in combinations(vehicles, 2):
        v = iou(a.bbox, b.bbox)
        if r["overlap_possible_iou"] <= v <= r["overlap_max_iou"]:
            strong.append((v, i, j, a, b))
        elif r["overlap_inconclusive_iou"] <= v < r["overlap_possible_iou"]:
            weak.append((v, i, j, a, b))
    if strong:
        v, i, j, a, b = max(strong, key=lambda t: t[0])
        conf = round(min(a.confidence, b.confidence), 3)
        return ClassificationResult(
            POSSIBLE, "Possível colisão/sobreposição de veículos (indício geométrico)", conf, True, True,
            "heuristica_modelo_generico", sorted({i, j}),
            [_r("G1", f"Veículos '{a.class_name}' e '{b.class_name}' com IoU {v:.2f} "
                      f"(≥ {r['overlap_possible_iou']:.2f}). Modelo genérico: é apenas um indício geométrico, "
                      f"que também pode ser causado por oclusão/perspectiva. Não é reconhecimento de acidente.")])
    if weak:
        v, i, j, a, b = max(weak, key=lambda t: t[0])
        return ClassificationResult(
            INCONCLUSIVE, "Sobreposição moderada entre veículos", round(min(a.confidence, b.confidence), 3),
            False, True, "heuristica_modelo_generico", sorted({i, j}),
            [_r("G2", f"Veículos '{a.class_name}' e '{b.class_name}' com IoU {v:.2f} "
                      f"(entre {r['overlap_inconclusive_iou']:.2f} e {r['overlap_possible_iou']:.2f}); "
                      f"compatível com tráfego denso ou com um evento. Requer revisão humana.")])
    return None
