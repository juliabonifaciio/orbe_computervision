from services.aph_triage import make_triage
from services.occurrence_classifier import load_rules
from config import Config
from tests.conftest import FakeDetector, make_image_bytes, upload

RULES = load_rules(Config.RULES_PATH)


def d(name, conf=0.9, cat="vehicle"):
    return {"class_name": name, "confidence": conf, "bbox": [0, 0, 10, 10], "category": cat}


def test_possible_with_person_is_high_priority():
    t = make_triage("possible", [d("car"), d("car"), d("person", cat="vulnerable")], RULES)
    assert t["priority"] == "alta" and t["indicators"]["people"] == 1
    assert any("USA" in r for r in t["resources"]) and len(t["checklist"]) > 0


def test_possible_with_motorcycle_or_truck_is_high():
    assert make_triage("possible", [d("car"), d("motorcycle")], RULES)["priority"] == "alta"
    assert make_triage("possible", [d("car"), d("truck")], RULES)["priority"] == "alta"


def test_possible_with_two_cars_is_medium():
    t = make_triage("possible", [d("car"), d("car")], RULES)
    assert t["priority"] == "media" and t["indicators"]["vehicles"] == 2


def test_three_vehicles_is_high():
    assert make_triage("possible", [d("car"), d("car"), d("car")], RULES)["priority"] == "alta"


def test_low_confidence_items_are_not_counted():
    t = make_triage("possible", [d("car"), d("car"), d("person", 0.2, "vulnerable")], RULES)
    assert t["indicators"]["people"] == 0 and t["priority"] == "media"


def test_fire_and_rollover_flags_and_rescue():
    t = make_triage("possible", [d("vehicle_fire", cat="accident"), d("car")], RULES)
    assert t["indicators"]["fire"] and t["priority"] == "alta"
    assert any("resgate" in r.lower() for r in t["resources"])


def test_inconclusive_and_none():
    i = make_triage("inconclusive", [d("car")], RULES)
    assert i["priority"] == "verificar" and i["checklist"] == []
    n = make_triage("none", [d("car")], RULES)
    assert n["priority"] == "sem_acionamento" and n["level"] == 0


def test_triage_is_saved_with_analysis(make_app):
    det = FakeDetector(script=[(0, "car", 0.9, [100, 100, 300, 300]), (0, "car", 0.8, [130, 100, 330, 300]),
                               (4, "person", 0.8, [10, 10, 40, 90])])
    a = upload(make_app(det).test_client(), make_image_bytes()).get_json()["analysis"]
    assert a["triage"]["priority"] == "alta" and a["triage"]["indicators"]["people"] == 1


def possible(make_app):
    det = FakeDetector(script=[(0, "car", 0.9, [100, 100, 300, 300]), (0, "car", 0.8, [130, 100, 330, 300])])
    c = make_app(det).test_client()
    return c, upload(c, make_image_bytes()).get_json()["analysis"]


def step(c, aid, status):
    return c.post(f"/api/analyses/{aid}/dispatch", json={"status": status, "operator": "Julia"})


def test_confirmation_starts_dispatch_and_steps_must_follow_order(make_app):
    c, a = possible(make_app)
    assert step(c, a["id"], "a_caminho").status_code == 409
    c.post(f"/api/analyses/{a['id']}/decision", json={"decision": "confirmed", "operator": "Julia"})
    cur = c.get(f"/api/analyses/{a['id']}").get_json()["analysis"]
    assert cur["dispatch_status"] == "acionada"
    assert step(c, a["id"], "no_local").status_code == 409
    for s in ["a_caminho", "no_local", "concluida"]:
        r = step(c, a["id"], s)
        assert r.status_code == 200 and r.get_json()["analysis"]["dispatch_status"] == s
    assert step(c, a["id"], "concluida").status_code == 409
    assert c.get("/api/stats").get_json()["stats"]["active_dispatch"] == 0


def test_rejected_case_has_no_dispatch(make_app):
    c, a = possible(make_app)
    c.post(f"/api/analyses/{a['id']}/decision", json={"decision": "rejected"})
    assert step(c, a["id"], "acionada").status_code == 409
    assert c.get(f"/api/analyses/{a['id']}").get_json()["analysis"]["dispatch"] == []


def test_queue_is_sorted_by_priority(make_app):
    app = make_app(FakeDetector(script=[(0, "car", 0.9, [100, 100, 300, 300]), (0, "car", 0.8, [130, 100, 330, 300])]))
    c = app.test_client()
    upload(c, make_image_bytes())
    app.extensions["orbe_service"].detector.script += [(4, "person", 0.9, [1, 1, 30, 90])]
    upload(c, make_image_bytes())
    items = c.get("/api/history?review=1").get_json()["items"]
    assert [i["triage"]["priority"] for i in items] == ["alta", "media"]
    assert c.get("/api/stats").get_json()["stats"]["high_priority"] == 1


def test_old_database_without_triage_column_is_migrated(tmp_path):
    import sqlite3
    from database.db import init_db
    from database.models import SCHEMA
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript(SCHEMA.replace(",\n    triage_json      TEXT", ""))
    con.commit()
    con.close()
    init_db(p)
    cols = [r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(analyses)")]
    assert "triage_json" in cols
