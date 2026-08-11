import io

import cv2
import numpy as np
from PIL import Image

TARGET_SIZE = (450, 750)  # (width, height)


def decode_jpeg(image_bytes):
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def denoise(img):
    return cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)


def correct_lighting(img):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    lab = cv2.merge((l_channel, a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def resize_final(img):
    return cv2.resize(img, TARGET_SIZE, interpolation=cv2.INTER_LANCZOS4)


def encode_jpeg(img_bgr):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=95, dpi=(96, 96))
    return buf.getvalue()


def load_restorer(model_path, device="cuda"):
    from gfpgan import GFPGANer

    return GFPGANer(
        model_path=model_path,
        upscale=2,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,
        device=device,
    )


def restore_face(img, restorer):
    _, _, restored_img = restorer.enhance(
        img, has_aligned=False, only_center_face=False, paste_back=True
    )
    return restored_img


def enhance(image_bytes, restorer):
    img = decode_jpeg(image_bytes)
    img = denoise(img)
    img = correct_lighting(img)
    img = restore_face(img, restorer)
    img = resize_final(img)
    return encode_jpeg(img)
