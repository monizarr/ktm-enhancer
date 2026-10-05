import argparse
import base64
import io
import os

import cv2
import numpy as np
from PIL import Image

from enhancer.db import connect_db, write_foto2

TARGET_SIZE = (372, 490)  # (width, height)
RAW_DIR = os.path.join("Input", "raw")


def decode_jpeg(image_bytes):
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def resize_final(img):
    return cv2.resize(img, TARGET_SIZE, interpolation=cv2.INTER_LANCZOS4)


def encode_jpeg(img_bgr):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=95, dpi=(96, 96))
    return buf.getvalue()


def resize_and_save(input_path):
    nim = os.path.splitext(os.path.basename(input_path))[0]

    with open(input_path, "rb") as f:
        image_bytes = f.read()

    img = decode_jpeg(image_bytes)
    img = resize_final(img)
    result_bytes = encode_jpeg(img)

    os.makedirs("Output", exist_ok=True)
    output_path = os.path.join("Output", f"{nim}.jpg")
    with open(output_path, "wb") as f:
        f.write(result_bytes)

    base64_str = base64.b64encode(result_bytes).decode("utf-8")

    print(f"Tersimpan: {output_path} ({TARGET_SIZE[0]}x{TARGET_SIZE[1]}px)")
    print("Base64:")
    print(base64_str)


def restore_raw_to_foto2(nim):
    raw_path = os.path.join(RAW_DIR, f"{nim}.jpg")
    if not os.path.exists(raw_path):
        print(f"File tidak ditemukan: {raw_path}")
        return

    with open(raw_path, "rb") as f:
        raw_bytes = f.read()

    conn = connect_db()
    try:
        write_foto2(conn, nim, raw_bytes)
        conn.commit()
    finally:
        conn.close()

    print(f"foto2 untuk NIM {nim} dikembalikan ke foto asli dari {raw_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Resize+encode foto KTM, atau kembalikan foto2 ke foto raw"
    )
    parser.add_argument(
        "target",
        help="Path file JPEG (mode resize) atau NIM (mode --restore)",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Kembalikan foto2 ke foto raw dari Input/raw/<nim>.jpeg (tulis ke database)",
    )
    args = parser.parse_args()

    if args.restore:
        restore_raw_to_foto2(args.target)
    else:
        resize_and_save(args.target)


if __name__ == "__main__":
    main()
