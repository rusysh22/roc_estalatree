"""Tests for the shared image-upload processing (apps/core/images.py)."""
import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.images import MAX_SIDE, MAX_UPLOAD_MB, MIN_SIDE, process_upload


def _png(w, h, color="white"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return SimpleUploadedFile("x.png", buf.getvalue(), content_type="image/png")


def test_valid_image_becomes_webp():
    out = process_upload(_png(800, 600))
    assert out.name.endswith(".webp")
    im = Image.open(out)
    assert im.format == "WEBP"
    assert im.size == (800, 600)


def test_png_format_stays_lossless_png():
    out = process_upload(_png(600, 600), fmt="png")
    assert out.name.endswith(".png")
    im = Image.open(out)
    assert im.format == "PNG"


def test_oversized_dimensions_are_downscaled():
    out = process_upload(_png(5000, 3000))
    im = Image.open(out)
    assert max(im.size) == MAX_SIDE
    assert abs(im.size[1] - MAX_SIDE * 3000 / 5000) <= 1


def test_too_small_is_rejected():
    with pytest.raises(ValidationError):
        process_upload(_png(MIN_SIDE - 10, MIN_SIDE - 10))


def test_non_image_is_rejected():
    bad = SimpleUploadedFile("evil.png", b"not really a png", content_type="image/png")
    with pytest.raises(ValidationError):
        process_upload(bad)


def test_absurdly_large_file_is_rejected():
    big = SimpleUploadedFile("big.png", b"\x00", content_type="image/png")
    big.size = (MAX_UPLOAD_MB + 1) * 1024 * 1024
    with pytest.raises(ValidationError):
        process_upload(big)


def test_square_crop():
    out = process_upload(_png(1000, 400), square=True)
    im = Image.open(out)
    assert im.size[0] == im.size[1]


def test_transparency_is_preserved():
    buf = io.BytesIO()
    Image.new("RGBA", (400, 400), (0, 0, 0, 0)).save(buf, format="PNG")
    f = SimpleUploadedFile("t.png", buf.getvalue(), content_type="image/png")
    im = Image.open(process_upload(f))
    assert im.mode in ("RGBA", "LA", "P")


def test_heavy_photo_is_compressed_under_target():
    # Random noise doesn't compress well — exercises the quality step-down loop.
    import os
    buf = io.BytesIO()
    Image.frombytes("RGB", (1600, 1600), os.urandom(1600 * 1600 * 3)).save(buf, format="PNG")
    f = SimpleUploadedFile("noise.png", buf.getvalue(), content_type="image/png")
    out = process_upload(f)
    assert out.size < 1_500_000  # comfortably smaller than the ~7.7 MB source
