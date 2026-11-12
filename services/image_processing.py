from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename


CATEGORY_COLORS = {
    "accident": (77, 77, 229),
    "vehicle": (216, 120, 91),
    "vulnerable": (60, 190, 240),
    "other": (160, 160, 160),
}
EVIDENCE_COLOR = (77, 77, 229)


class ImageValidationError(Exception):

    def __init__(self, message: str, code: str = "invalid_image"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ModelInputInfo:
    imgsz: int
    letterbox: bool = True
    normalization: str = "pixels / 255.0 (float32, RGB, CHW) — aplicado pelo Ultralytics"


@dataclass
class PreparedImage:
    bgr: np.ndarray
    width: int
    height: int
    original_width: int
    original_height: int
    original_format: str
    scale: float
    quality: dict = field(default_factory=dict)
    model_input: ModelInputInfo | None = None


def new_analysis_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"ORBE-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


_ID_RE = re.compile(r"^ORBE-\d{8}-[0-9A-F]{6}$")


def is_valid_analysis_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def validate_upload(file_storage, allowed_ext: set[str]) -> tuple[str, str]:
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raise ImageValidationError("Nenhum arquivo foi enviado.", "no_file")
    original = secure_filename(file_storage.filename) or "imagem"
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in allowed_ext:
        raise ImageValidationError(
            f"Formato não aceito. Envie arquivos {', '.join(sorted(e.upper() for e in allowed_ext))}.",
            "bad_extension",
        )
    return original, ext


def save_upload(file_storage, upload_dir: Path, analysis_id: str, ext: str) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{analysis_id}.{'jpg' if ext == 'jpeg' else ext}"
    file_storage.save(dest)
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise ImageValidationError("O arquivo enviado está vazio.", "empty_file")
    return dest


def load_and_prepare(path: Path, *, max_pixels: int, min_side: int, max_side: int,
                     imgsz: int) -> PreparedImage:
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(path) as probe:
            probe.verify()
        with Image.open(path) as img:
            fmt = (img.format or "").upper()
            if fmt not in {"JPEG", "PNG"}:
                raise ImageValidationError(
                    "O conteúdo do arquivo não corresponde a uma imagem JPG ou PNG.", "bad_content")
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            rgb = np.asarray(img)
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, ValueError) as exc:
        raise ImageValidationError(
            "Não foi possível ler a imagem: o arquivo está corrompido ou não é uma imagem válida.",
            "corrupt_image") from exc

    h, w = rgb.shape[:2]
    if min(h, w) < min_side:
        raise ImageValidationError(
            f"Imagem muito pequena ({w}x{h}px). O lado mínimo é {min_side}px.", "too_small")

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    scale = 1.0
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        bgr = cv2.resize(bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)

    return PreparedImage(
        bgr=np.ascontiguousarray(bgr), width=bgr.shape[1], height=bgr.shape[0],
        original_width=w, original_height=h, original_format=fmt, scale=scale,
        quality=compute_quality(bgr), model_input=ModelInputInfo(imgsz=imgsz),
    )


def compute_quality(bgr: np.ndarray) -> dict:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    f = 640 / max(h, w)
    if f < 1:
        gray = cv2.resize(gray, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    return {
        "laplacian_variance": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
        "mean_brightness": round(float(gray.mean()), 2),
    }


def draw_detections(bgr: np.ndarray, detections: list[dict], evidence_idx: set[int]) -> np.ndarray:
    out = bgr.copy()
    h, w = out.shape[:2]
    thick = max(2, round(min(h, w) / 360))
    font_scale = max(0.5, min(h, w) / 1100)
    for i, d in enumerate(detections):
        x1, y1, x2, y2 = (int(round(v)) for v in d["bbox"])
        is_ev = i in evidence_idx
        color = EVIDENCE_COLOR if is_ev else CATEGORY_COLORS.get(d["category"], CATEGORY_COLORS["other"])
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thick + (1 if is_ev else 0))
        label = f"{d['class_name']} {d['confidence']:.0%}"
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        ty = y1 - 4 if y1 - th - base - 4 > 0 else y1 + th + base + 2
        cv2.rectangle(out, (x1, ty - th - base), (x1 + tw + 6, ty + base - 2), color, -1)
        cv2.putText(out, label, (x1 + 3, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    (255, 255, 255), 1, cv2.LINE_AA)
    return out


def save_jpeg(bgr: np.ndarray, dest: Path, quality: int = 90) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(dest), bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise OSError("Falha ao gravar a imagem processada.")
    return dest
