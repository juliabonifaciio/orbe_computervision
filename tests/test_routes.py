import io

import pytest

from tests.conftest import FakeDetector, make_image_bytes, upload
from services.inference import InferenceError, ModelUnavailableError

IMG = make_image_bytes("PNG", (320, 240))
ACC_NAMES = ["car", "truck", "collision"]


def acc_detector(conf=0.88):
    return FakeDetector(names=ACC_NAMES, script=[(2, "collision", conf, [40, 40, 200, 180]),
                                                 (0, "car", 0.9, [100, 100, 300, 220])])


def possible_analysis(make_app):
    app = make_app(acc_detector())
    c = app.test_client()
    return app, c, upload(c, IMG, source="Câmera KM 12").get_json()["analysis"]


def test_pages_render(make_app):
    c = make_app().test_client()
    for url in ["/", "/analysis", "/history", "/review", "/settings", "/api/health", "/api/stats", "/api/history"]:
        assert c.get(url).status_code == 200, url
    assert c.get("/analysis/ORBE-20260101-ABCDEF").status_code == 404
    assert c.get("/nao-existe").status_code == 404


def test_dashboard_starts_with_real_zeros(make_app):
    s = make_app().test_client().get("/api/stats").get_json()["stats"]
    assert s["total"] == 0 and s["possible"] == 0 and s["awaiting"] == 0


def test_possible_occurrence_flow(make_app):
    app, c, a = possible_analysis(make_app)
    assert a["result"] == "possible" and a["notify"] is True and a["validation_status"] == "pending"
    assert a["source"] == "Câmera KM 12" and a["detection_count"] == 2 and a["inference_ms"] >= 0
    assert a["evidence_level"] == "modelo_de_acidentes" and a["decisions"] == [] and a["definitive"] is None
    assert c.get(f"/media/processed/{a['id']}.jpg").status_code == 200
    assert c.get(f"/media/uploads/{a['id']}.png").status_code == 200
    assert c.get("/api/stats").get_json()["stats"]["awaiting"] == 1


def test_no_occurrence(make_app):
    det = FakeDetector(script=[(0, "car", 0.9, [10, 10, 100, 100]), (0, "car", 0.8, [200, 10, 300, 100])])
    a = upload(make_app(det).test_client(), IMG).get_json()["analysis"]
    assert a["result"] == "none" and a["notify"] is False and a["validation_status"] == "not_required"


def test_inconclusive_when_nothing_detected(make_app):
    a = upload(make_app(FakeDetector()).test_client(), IMG).get_json()["analysis"]
    assert a["result"] == "inconclusive" and a["validation_status"] == "pending" and a["notify"] is False


def test_inconclusive_for_blurry_image(make_app):
    det = FakeDetector(script=[(0, "car", 0.9, [10, 10, 100, 100])])
    a = upload(make_app(det).test_client(), make_image_bytes(blur=True)).get_json()["analysis"]
    assert a["result"] == "inconclusive" and a["reasons"][0]["rule"] == "Q1"


def test_generic_model_never_reports_accident_evidence(make_app):
    det = FakeDetector(script=[(0, "car", 0.9, [100, 100, 300, 300]), (0, "car", 0.8, [130, 100, 330, 300])])
    a = upload(make_app(det).test_client(), IMG).get_json()["analysis"]
    assert a["model_mode"] == "generic" and a["evidence_level"] == "heuristica_modelo_generico"
    assert "genérico" in a["llm_summary"]["text"]


def test_invalid_extension(make_app):
    r = upload(make_app().test_client(), b"MZ...", name="virus.exe")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_extension"


def test_corrupt_image_leaves_no_file(make_app):
    app = make_app()
    r = upload(app.test_client(), b"lixo", name="x.jpg")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "corrupt_image"
    assert list(app.config["UPLOAD_DIR"].glob("*")) == []
    assert app.test_client().get("/api/stats").get_json()["stats"]["total"] == 0


def test_no_file(make_app):
    r = make_app().test_client().post("/api/analyze", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "no_file"


def test_file_too_large(make_app):
    r = upload(make_app(MAX_CONTENT_LENGTH=1000).test_client(), IMG)
    assert r.status_code == 413 and r.get_json()["error"]["code"] == "too_large"


def test_inference_error_is_reported_and_not_stored(make_app):
    app = make_app(FakeDetector(raises=InferenceError("falha simulada")))
    r = upload(app.test_client(), IMG)
    assert r.status_code == 500 and r.get_json()["error"]["code"] == "inference_error"
    assert app.test_client().get("/api/stats").get_json()["stats"]["total"] == 0


def test_model_unavailable(make_app):
    r = upload(make_app(FakeDetector(raises=ModelUnavailableError("sem pesos"))).test_client(), IMG)
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "model_unavailable"


def test_unexpected_error_does_not_leak_details(make_app):
    r = upload(make_app(FakeDetector(raises=ValueError("segredo interno"))).test_client(), IMG)

    assert r.status_code == 500 and "segredo" not in r.get_data(as_text=True)


def test_media_rejects_traversal_and_foreign_names(make_app):
    c = make_app().test_client()
    assert c.get("/media/uploads/..%2Fapp.py").status_code == 404
    assert c.get("/media/uploads/app.py").status_code == 404
    assert c.get("/media/secret/ORBE-20260101-ABCDEF.jpg").status_code == 404


def decide(c, aid, **body):
    return c.post(f"/api/analyses/{aid}/decision", json=body)


def test_human_confirmation_creates_definitive_record(make_app):
    app, c, a = possible_analysis(make_app)
    r = decide(c, a["id"], decision="confirmed", operator="Julia", notes="Visto na câmera")
    out = r.get_json()["analysis"]
    assert r.status_code == 200 and out["validation_status"] == "confirmed"
    assert out["definitive"]["operator"] == "Julia" and out["definitive"]["final_type"] == a["situation_type"]
    assert out["result"] == "possible"
    assert out["decisions"][0]["notes"] == "Visto na câmera"
    s = c.get("/api/stats").get_json()["stats"]
    assert s["confirmed"] == 1 and s["awaiting"] == 0


def test_human_rejection_is_not_definitive(make_app):
    app, c, a = possible_analysis(make_app)
    out = decide(c, a["id"], decision="rejected", operator="Julia").get_json()["analysis"]
    assert out["validation_status"] == "rejected" and out["definitive"] is None
    assert out["decisions"][0]["decision"] == "rejected" and out["result"] == "possible"
    assert c.get("/api/stats").get_json()["stats"]["rejected"] == 1


def test_correction_with_different_type(make_app):
    app, c, a = possible_analysis(make_app)
    out = decide(c, a["id"], decision="confirmed", operator="Ana", corrected_type="Veículo parado na via").get_json()["analysis"]
    assert out["validation_status"] == "corrected" and out["definitive"]["final_type"] == "Veículo parado na via"


def test_additional_analysis_keeps_case_open_then_final(make_app):
    app, c, a = possible_analysis(make_app)
    out = decide(c, a["id"], decision="additional_review", operator="Ana").get_json()["analysis"]
    assert out["validation_status"] == "additional_review" and out["definitive"] is None
    assert c.get("/api/stats").get_json()["stats"]["awaiting"] == 1
    assert decide(c, a["id"], decision="rejected").status_code == 200
    assert len(c.get(f"/api/analyses/{a['id']}").get_json()["analysis"]["decisions"]) == 2


def test_final_decision_is_immutable(make_app):
    app, c, a = possible_analysis(make_app)
    decide(c, a["id"], decision="rejected")
    r = decide(c, a["id"], decision="confirmed", operator="X")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "already_final"


def test_confirmation_requires_operator(make_app):
    app, c, a = possible_analysis(make_app)
    r = decide(c, a["id"], decision="confirmed")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "operator_required"


def test_invalid_decision_and_unknown_id(make_app):
    app, c, a = possible_analysis(make_app)
    assert decide(c, a["id"], decision="apagar").status_code == 400
    assert decide(c, "ORBE-20260101-ABCDEF", decision="rejected").status_code == 404
    assert decide(c, "x'; DROP TABLE analyses;--", decision="rejected").status_code == 400


def test_no_occurrence_cannot_be_validated(make_app):
    det = FakeDetector(script=[(0, "car", 0.9, [10, 10, 100, 100])])
    c = make_app(det).test_client()
    a = upload(c, IMG).get_json()["analysis"]
    assert decide(c, a["id"], decision="confirmed", operator="x").status_code == 409


def test_history_filters(make_app):
    app, c, a = possible_analysis(make_app)
    app.extensions["orbe_service"].detector.script = [(0, "car", 0.9, [10, 10, 100, 100])]
    upload(c, IMG, source="Outra câmera")
    all_ = c.get("/api/history").get_json()
    assert all_["count"] == 2
    assert c.get("/api/history?result=possible").get_json()["count"] == 1
    assert c.get("/api/history?status=pending").get_json()["count"] == 1
    assert c.get("/api/history?review=1").get_json()["count"] == 1
    assert c.get("/api/history?q=Outra").get_json()["count"] == 1
    assert c.get("/api/history?date_from=2999-01-01").get_json()["count"] == 0
    decide(c, a["id"], decision="rejected", operator="Julia")
    assert c.get("/api/history?status=rejected").get_json()["items"][0]["operator"] == "Julia"
    assert c.get("/api/history?review=1").get_json()["count"] == 0
