import io
import sys
import types

import numpy as np
import pytest
from PIL import Image

from services import image_processing as ip
from services.inference import (Detection, InferenceError, ModelUnavailableError, UltralyticsDetector,
                                categorize, detect_model_mode, run_inference)
from services.occurrence_classifier import load_rules
from config import Config
from tests.conftest import FakeDetector, make_image_bytes

RULES = load_rules(Config.RULES_PATH)
KW = dict(max_pixels=50_000_000, min_side=32, max_side=2560, imgsz=640)


def _save(tmp_path, data, name):
    p = tmp_path / name
    p.write_bytes(data)
    return p


@pytest.mark.parametrize("fmt,name", [("PNG", "a.png"), ("JPEG", "a.jpg")])
def test_load_valid_images(tmp_path, fmt, name):
    p = _save(tmp_path, make_image_bytes(fmt, (300, 200)), name)
    prep = ip.load_and_prepare(p, **KW)
    assert (prep.width, prep.height) == (300, 200) and prep.bgr.shape == (200, 300, 3)
    assert prep.original_format in {"PNG", "JPEG"} and "laplacian_variance" in prep.quality
    assert prep.model_input.imgsz == 640


def test_rgba_png_is_converted_to_three_channels(tmp_path):
    p = _save(tmp_path, make_image_bytes("PNG", (100, 100), mode="RGBA"), "a.png")
    assert ip.load_and_prepare(p, **KW).bgr.shape[2] == 3


def test_corrupt_file_rejected(tmp_path):
    p = _save(tmp_path, b"isto nao e uma imagem", "x.jpg")
    with pytest.raises(ip.ImageValidationError) as e:
        ip.load_and_prepare(p, **KW)
    assert e.value.code == "corrupt_image"


def test_truncated_image_rejected(tmp_path):
    data = make_image_bytes("PNG", (200, 200))
    p = _save(tmp_path, data[: len(data) // 2], "t.png")
    with pytest.raises(ip.ImageValidationError):
        ip.load_and_prepare(p, **KW)


def test_wrong_format_with_valid_extension_rejected(tmp_path):
    p = _save(tmp_path, make_image_bytes("BMP", (100, 100)), "a.png")
    with pytest.raises(ip.ImageValidationError) as e:
        ip.load_and_prepare(p, **KW)
    assert e.value.code == "bad_content"


def test_too_small_rejected(tmp_path):
    p = _save(tmp_path, make_image_bytes("PNG", (16, 16)), "s.png")
    with pytest.raises(ip.ImageValidationError) as e:
        ip.load_and_prepare(p, **KW)
    assert e.value.code == "too_small"


def test_large_image_is_downscaled(tmp_path):
    p = _save(tmp_path, make_image_bytes("PNG", (800, 400)), "l.png")
    prep = ip.load_and_prepare(p, **{**KW, "max_side": 400})
    assert max(prep.width, prep.height) == 400 and prep.scale == 0.5 and prep.original_width == 800


def test_validate_upload_rules():
    class F:
        filename = "../../etc/passwd.exe"
    with pytest.raises(ip.ImageValidationError):
        ip.validate_upload(F(), {"jpg", "png"})
    with pytest.raises(ip.ImageValidationError):
        ip.validate_upload(None, {"jpg"})

    class G:
        filename = "../../minha foto.JPG"
    name, ext = ip.validate_upload(G(), {"jpg"})
    assert ext == "jpg" and "/" not in name and ".." not in name


def test_quality_metrics_distinguish_flat_and_textured():
    flat = np.full((200, 200, 3), 128, np.uint8)
    noisy = np.random.default_rng(1).integers(0, 255, (200, 200, 3), dtype=np.uint8)
    assert ip.compute_quality(flat)["laplacian_variance"] < 1 < ip.compute_quality(noisy)["laplacian_variance"]


def test_draw_detections_changes_only_marked_pixels():
    img = np.zeros((200, 300, 3), np.uint8)
    dets = [Detection(2, "car", 0.9, [50, 50, 150, 120], "vehicle").to_dict()]
    out = ip.draw_detections(img, dets, {0})
    assert out.shape == img.shape and out.sum() > 0 and img.sum() == 0


def test_analysis_id_format():
    assert ip.is_valid_analysis_id(ip.new_analysis_id())
    assert not ip.is_valid_analysis_id("../x")


def test_categorize_and_mode():
    c = RULES["classes"]
    assert categorize("car", c) == "vehicle" and categorize("Vehicle Fire", c) == "accident"
    assert categorize("person", c) == "vulnerable" and categorize("kite", c) == "other"
    assert detect_model_mode(["car", "person"], c) == "generic"
    assert detect_model_mode(["car", "collision"], c) == "accident"


def test_run_inference_sorts_and_categorizes():
    det = FakeDetector(script=[(2, "car", 0.5, [0, 0, 10, 10]), (7, "truck", 0.9, [20, 20, 90, 90])])
    r = run_inference(det, np.zeros((100, 100, 3), np.uint8), RULES["classes"], 640)
    assert [d.class_name for d in r.detections] == ["truck", "car"] and r.detections[0].category == "vehicle"
    assert r.model_mode == "generic" and r.inference_ms >= 0


def test_run_inference_propagates_errors():
    det = FakeDetector(raises=InferenceError("boom"))
    with pytest.raises(InferenceError):
        run_inference(det, np.zeros((10, 10, 3), np.uint8), RULES["classes"], 640)


class _T:
    def __init__(self, a): self.a = np.array(a)
    def cpu(self): return self
    def numpy(self): return self.a


def _install_fake_ultralytics(monkeypatch, boxes):
    class _Boxes:
        xyxy = _T([b[0] for b in boxes]); conf = _T([b[1] for b in boxes]); cls = _T([b[2] for b in boxes])
        def __len__(self): return len(boxes)

    class _Res:
        names = {0: "person", 2: "car", 7: "truck"}
        def __init__(self): self.boxes = _Boxes() if boxes else None

    class YOLO:
        calls = []
        def __init__(self, path): self.names = {0: "person", 2: "car", 7: "truck"}; self.path = path
        def predict(self, **kw):
            YOLO.calls.append(kw)
            return [_Res()]

    mod = types.ModuleType("ultralytics"); mod.YOLO = YOLO; mod.RTDETR = YOLO
    monkeypatch.setitem(sys.modules, "ultralytics", mod)
    return YOLO


def test_ultralytics_adapter_parses_results(tmp_path, monkeypatch):
    YOLO = _install_fake_ultralytics(monkeypatch, [([1, 2, 30, 40], 0.9, 2), ([5, 5, 9, 9], 0.4, 7)])
    w = tmp_path / "modelo.pt"; w.write_bytes(b"x")
    d = UltralyticsDetector(w, "yolo11s.pt", imgsz=640)
    out = d.detect(np.zeros((50, 50, 3), np.uint8))
    assert out[0] == (2, "car", pytest.approx(0.9), [1.0, 2.0, 30.0, 40.0]) and len(out) == 2
    assert d.info()["loaded"] and d.info()["source"] == "customizado" and d.class_names() == ["person", "car", "truck"]
    assert YOLO.calls[0]["imgsz"] == 640 and YOLO.calls[0]["agnostic_nms"] is True


def test_ultralytics_adapter_no_detections(tmp_path, monkeypatch):
    _install_fake_ultralytics(monkeypatch, [])
    d = UltralyticsDetector(tmp_path / "m.pt", str(tmp_path / "fb.pt"))
    (tmp_path / "fb.pt").write_bytes(b"x")
    assert d.detect(np.zeros((50, 50, 3), np.uint8)) == [] and d.info()["source"] == "genérico (COCO)"


def test_ultralytics_missing_package_is_model_unavailable(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    d = UltralyticsDetector(tmp_path / "m.pt", "yolo11s.pt")
    with pytest.raises(ModelUnavailableError):
        d.detect(np.zeros((10, 10, 3), np.uint8))
    assert d.info()["error"]


def test_ultralytics_predict_failure_becomes_inference_error(tmp_path, monkeypatch):
    YOLO = _install_fake_ultralytics(monkeypatch, [])
    YOLO.predict = lambda self, **kw: (_ for _ in ()).throw(RuntimeError("CUDA OOM"))
    w = tmp_path / "m.pt"; w.write_bytes(b"x")
    with pytest.raises(InferenceError):
        UltralyticsDetector(w, "yolo11s.pt").detect(np.zeros((10, 10, 3), np.uint8))


def test_evaluate_metrics_script_logic():
    from tools.evaluate import evaluate
    rows = [("a", "ocorrencia"), ("b", "ocorrencia"), ("c", "normal"), ("d", "normal")]
    preds = {"a": "possible", "b": "none", "c": "possible", "d": "inconclusive"}
    out = evaluate(rows, lambda p: (preds[p], 10.0))
    assert out["precisao"] == 0.5 and out["recall"] == 0.5 and out["f1"] == 0.5
    assert out["matriz_confusao"]["linhas_verdade_colunas_predicao"] == [[1, 1], [1, 1]]
    assert out["estados"] == {"possible": 2, "none": 1, "inconclusive": 1}
