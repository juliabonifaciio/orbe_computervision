import pytest
from services.occurrence_classifier import classify, load_rules, iou, POSSIBLE, NONE, INCONCLUSIVE
from config import Config

RULES = load_rules(Config.RULES_PATH)
GOOD_Q = {"laplacian_variance": 300.0, "mean_brightness": 120.0}
SIZE = (1000, 600)


def D(name, conf, box, cat):
    return {"class_name": name, "confidence": conf, "bbox": box, "category": cat}


def car(conf, box):
    return D("car", conf, box, "vehicle")


def acc(conf, box=(100, 100, 400, 300), name="collision"):
    return D(name, conf, list(box), "accident")


def test_accident_high_confidence_is_possible_and_notifies():
    r = classify([acc(0.85)], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == POSSIBLE and r.notify and r.requires_review
    assert r.evidence_level == "modelo_de_acidentes" and r.confidence == 0.85
    assert r.reasons[0]["rule"] == "A1"


def test_accident_medium_confidence_without_corroboration_is_inconclusive():
    r = classify([acc(0.55)], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == INCONCLUSIVE and not r.notify and r.requires_review


def test_accident_medium_confidence_with_touching_vehicle_is_possible():
    r = classify([acc(0.55), car(0.9, [300, 200, 600, 400])], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == POSSIBLE


def test_accident_two_detections_corroborate():
    r = classify([acc(0.55), acc(0.52, (600, 100, 900, 300))], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == POSSIBLE


def test_accident_tiny_box_does_not_count():
    r = classify([acc(0.95, (10, 10, 20, 20))], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == INCONCLUSIVE


def test_accident_weak_confidence_is_inconclusive():
    r = classify([acc(0.30), car(0.9, [0, 0, 50, 50])], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == INCONCLUSIVE and r.reasons[0]["rule"] == "A3"


def test_accident_model_vehicles_only_is_none():
    r = classify([car(0.9, [0, 0, 100, 100]), car(0.8, [200, 0, 300, 100])], SIZE, GOOD_Q, "accident", RULES)
    assert r.result == NONE and not r.notify and not r.requires_review


def test_generic_strong_overlap_is_heuristic_possible():
    a, b = car(0.9, [100, 100, 300, 300]), car(0.8, [130, 100, 330, 300])
    r = classify([a, b], SIZE, GOOD_Q, "generic", RULES)
    assert r.result == POSSIBLE and r.evidence_level == "heuristica_modelo_generico"
    assert "indício" in r.situation_type.lower() and r.reasons[0]["rule"] == "G1"


def test_generic_moderate_overlap_is_inconclusive():
    a, b = car(0.9, [100, 100, 300, 300]), car(0.8, [200, 100, 400, 300])
    r = classify([a, b], SIZE, GOOD_Q, "generic", RULES)
    assert r.result == INCONCLUSIVE and not r.notify


def test_generic_duplicate_box_is_not_a_collision():
    a, b = car(0.9, [100, 100, 300, 300]), car(0.8, [101, 100, 300, 301])
    assert iou(a["bbox"], b["bbox"]) > 0.9
    assert classify([a, b], SIZE, GOOD_Q, "generic", RULES).result == NONE


def test_generic_low_confidence_vehicles_ignored():
    a, b = car(0.3, [100, 100, 300, 300]), car(0.3, [130, 100, 330, 300])
    assert classify([a, b], SIZE, GOOD_Q, "generic", RULES).result == NONE


def test_generic_separate_vehicles_is_none_and_never_claims_accident():
    r = classify([car(0.9, [0, 0, 100, 100]), car(0.9, [500, 0, 600, 100])], SIZE, GOOD_Q, "generic", RULES)
    assert r.result == NONE and r.evidence_level == "sem_evidencia"


def test_no_detections_is_inconclusive():
    r = classify([], SIZE, GOOD_Q, "generic", RULES)
    assert r.result == INCONCLUSIVE and r.requires_review


def test_only_person_is_inconclusive():
    r = classify([D("person", 0.9, [0, 0, 50, 100], "vulnerable")], SIZE, GOOD_Q, "generic", RULES)
    assert r.result == INCONCLUSIVE


@pytest.mark.parametrize("q", [{"laplacian_variance": 5, "mean_brightness": 120},
                               {"laplacian_variance": 300, "mean_brightness": 10},
                               {"laplacian_variance": 300, "mean_brightness": 250}])
def test_bad_quality_without_evidence_is_inconclusive(q):
    r = classify([car(0.9, [0, 0, 100, 100])], SIZE, q, "generic", RULES)
    assert r.result == INCONCLUSIVE and r.reasons[0]["rule"] == "Q1"


def test_possible_with_bad_quality_adds_warning():
    q = {"laplacian_variance": 5, "mean_brightness": 120}
    r = classify([acc(0.9)], SIZE, q, "accident", RULES)
    assert r.result == POSSIBLE and any(x["rule"] == "Q1" for x in r.reasons)


def test_notification_is_configurable():
    rules = {**RULES, "notification": {"notify_on": ["possible", "inconclusive"], "review_on": ["possible", "inconclusive"]}}
    assert classify([], SIZE, GOOD_Q, "generic", rules).notify is True
