import io

import cv2
import numpy as np
from PIL import Image

TARGET_SIZE = (372, 490)  # (width, height)


def decode_jpeg(image_bytes):
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def denoise(img, strength=10):
    if strength == 0:
        return img
    return cv2.fastNlMeansDenoisingColored(img, None, strength, strength, 7, 21)


def correct_lighting(img, strength=2.0):
    if strength == 0:
        return img
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=strength, tileGridSize=(8, 8))
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


def apply_filters(img, brightness=0, contrast=1.0, saturation=1.0, sharpness=0):
    # Adjust around mid-gray; clip instead of wrapping negative pixel values.
    adjusted = (img.astype(np.float32) - 127.5) * contrast + 127.5 + brightness
    img = np.clip(adjusted, 0, 255).astype(np.uint8)
    if saturation != 1:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    if sharpness:
        blurred = cv2.GaussianBlur(img, (0, 0), 1.0)
        img = cv2.addWeighted(img, 1 + sharpness, blurred, -sharpness, 0)
    return img


def enhance(image_bytes, restorer, *, brightness=0, contrast=1.0,
            smoothness=10, saturation=1.0, sharpness=0, lighting=2.0):
    img = decode_jpeg(image_bytes)
    if img is None:
        raise ValueError("Foto tidak dapat dibaca")
    img = denoise(img, smoothness)
    img = correct_lighting(img, lighting)
    img = restore_face(img, restorer)
    img = resize_final(img)
    img = apply_filters(img, brightness, contrast, saturation, sharpness)
    return encode_jpeg(img)
