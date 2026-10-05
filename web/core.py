import io
import os
import re
import threading

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from enhancer.pipeline import load_restorer

MODEL_PATH = os.path.join("enhancer", "models", "GFPGANv1.4.pth")
NIM_PATTERN = re.compile(r"^[0-9A-Za-z]{1,20}$")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
WEB_DIR = os.path.dirname(__file__)

_restorer = None
# GPU hanya satu: muat model sekali dan jalankan enhance satu per satu
gpu_lock = threading.Lock()


def get_restorer():
    global _restorer
    if _restorer is None:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("GPU CUDA tidak terdeteksi. Enhance membutuhkan GPU NVIDIA dengan CUDA aktif.")
        _restorer = load_restorer(MODEL_PATH)
    return _restorer


def buat_templates():
    """Jinja2Templates dengan `css_versi` agar browser memuat ulang app.css setiap kali file berubah."""
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=os.path.join(WEB_DIR, "templates"))
    templates.env.globals["css_versi"] = lambda: int(os.path.getmtime(os.path.join(WEB_DIR, "static", "app.css")))
    return templates


def is_valid_nim(nim):
    return bool(NIM_PATTERN.match(nim))


def check_nim(nim):
    nim = nim.strip()
    if not is_valid_nim(nim):
        raise HTTPException(status_code=400, detail="NIM tidak valid")
    return nim


def to_jpeg(data):
    """Pastikan data adalah gambar valid; JPEG disimpan apa adanya, format lain dikonversi ke JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if img.format == "JPEG":
                return data
            out = io.BytesIO()
            img.convert("RGB").save(out, format="JPEG", quality=95)
            return out.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("File bukan gambar yang valid") from exc
