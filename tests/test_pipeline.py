import numpy as np

from enhancer.pipeline import (
    TARGET_SIZE,
    decode_jpeg,
    denoise,
    correct_lighting,
    resize_final,
    encode_jpeg,
)


def _load_sample():
    with open("tests/fixtures/sample.jpg", "rb") as f:
        return f.read()


def test_decode_jpeg_returns_bgr_array():
    img = decode_jpeg(_load_sample())
    assert isinstance(img, np.ndarray)
    assert img.ndim == 3
    assert img.shape[2] == 3


def test_denoise_preserves_shape():
    img = decode_jpeg(_load_sample())
    result = denoise(img)
    assert result.shape == img.shape


def test_correct_lighting_preserves_shape():
    img = decode_jpeg(_load_sample())
    result = correct_lighting(img)
    assert result.shape == img.shape


def test_resize_final_produces_target_dimensions():
    img = decode_jpeg(_load_sample())
    result = resize_final(img)
    height, width = result.shape[:2]
    assert (width, height) == TARGET_SIZE


def test_encode_jpeg_roundtrip_decodable():
    img = decode_jpeg(_load_sample())
    resized = resize_final(img)
    encoded = encode_jpeg(resized)
    assert isinstance(encoded, bytes)
    decoded_again = decode_jpeg(encoded)
    height, width = decoded_again.shape[:2]
    assert (width, height) == TARGET_SIZE
