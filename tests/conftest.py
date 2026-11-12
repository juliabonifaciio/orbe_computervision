import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from services.inference import Detector, InferenceError, ModelUnavailableError


class FakeDetector(Detector):
    name = "fake-test-detector"

    def __init__(self, names=None, script=None, raises=None):
        self.names = names or ["car", "truck", "motorcycle", "bus", "person"]
        self.script = script or []
        self.raises = raises

    def info(self):
        return {"loaded": True, "name": self.name, "source": "teste", "family": "fake", "imgsz": 640, "error": None}

    def class_names(self):
        return self.names

    def detect(self, bgr):
        if self.raises:
            raise self.raises
        return list(self.script)


def make_image_bytes(fmt="PNG", size=(320, 240), blur=False, dark=False, mode="RGB"):
    rng = np.random.default_rng(7)
    arr = rng.integers(60, 200, (size[1], size[0], 3), dtype=np.uint8)
    if blur:
        arr[:] = 128
    if dark:
        arr = (arr * 0.05).astype(np.uint8)
    img = Image.fromarray(arr).convert(mode)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def make_app(tmp_path):
    def _make(detector=None, **over):
        cfg = dict(TESTING=True, UPLOAD_DIR=tmp_path / "up", PROCESSED_DIR=tmp_path / "proc",
                   LOG_DIR=tmp_path / "log", DATABASE_PATH=tmp_path / "t.db", WARMUP_ON_START=False)
        cfg.update(over)
        return create_app(cfg, detector=detector or FakeDetector())
    return _make


def upload(client, data, name="foto.png", source=None):
    form = {"image": (io.BytesIO(data), name)}
    if source:
        form["source"] = source
    return client.post("/api/analyze", data=form, content_type="multipart/form-data")
