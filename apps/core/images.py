"""Shared image-upload processing.

One code path for every user-uploaded image on the site (seller logo, store
avatar & banner, product cover, static QRIS, payment proof). The goal is to
*not* bounce the user back for fixable problems:

  * Wrong orientation .............. auto-rotated from EXIF, metadata stripped
  * Dimensions too large ........... auto-downscaled to MAX_SIDE
  * File a few MB heavy ............ auto re-encoded to WebP, quality stepped down
  * Animated GIF .................. first frame is kept
  * Has transparency ............. preserved (WebP keeps alpha)

Only genuinely unusable uploads are rejected, each with a plain-language fix:

  * Not an image / corrupt ........ "pick a JPG, PNG or WebP file"
  * Absurdly large file (> MAX_UPLOAD_MB) — refused before decoding (DoS guard)
  * Too small to ever look good (< MIN_SIDE on the short edge)

`process_upload()` returns a Django ``ContentFile`` ready to assign to an
``ImageField``; callers never touch Pillow directly.
"""
from __future__ import annotations

import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

# ── Uniform limits (shared by every upload field on the site) ────────────────
MAX_UPLOAD_MB = 10            # hard cap on the raw upload, before decoding
MIN_SIDE = 200               # shortest edge; smaller than this can't be salvaged
MAX_SIDE = 2048              # longest edge; anything bigger is downscaled
TARGET_BYTES = 900 * 1024    # aim for the stored file to be under this
_QUALITY_STEPS = (85, 78, 70, 62, 55)
ACCEPT = "image/jpeg,image/png,image/webp,image/gif"

# Human-friendly guidance surfaced next to every upload widget.
HELP_TEXT = (
    f"JPG, PNG, or WebP. Max {MAX_UPLOAD_MB} MB, at least {MIN_SIDE}×{MIN_SIDE} px. "
    "Large images are resized automatically — no need to edit them first."
)


def process_upload(f, *, square: bool = False, fmt: str = "webp") -> ContentFile:
    """Validate + normalise an uploaded image.

    Args:
        f: an ``UploadedFile`` (from ``request.FILES`` / a form ``ImageField``).
        square: if True, centre-crop to a square (used for avatars / logos).
        fmt: ``"webp"`` (default, best for photos) or ``"png"`` (lossless — use
            for QR codes / line art where compression artifacts would hurt).

    Raises:
        ValidationError: only when the upload cannot be used at all.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    size = getattr(f, "size", None)
    if size and size > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(
            f"Ukuran file {size / 1024 / 1024:.1f} MB melebihi batas {MAX_UPLOAD_MB} MB. "
            "Coba pilih gambar lain atau kompres dulu (mis. lewat tinypng.com)."
        )

    try:
        f.seek(0)
        img = Image.open(f)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError(
            "File ini bukan gambar yang bisa dibaca. Gunakan format JPG, PNG, atau WebP."
        )

    # Animated GIF / multi-frame → keep the first frame only.
    if getattr(img, "is_animated", False):
        img.seek(0)

    # Respect the camera's rotation flag, then drop all metadata.
    img = ImageOps.exif_transpose(img)

    # Normalise colour mode. Preserve alpha (WebP supports it); otherwise RGB.
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        has_alpha = True
    else:
        img = img.convert("RGB")
        has_alpha = False

    w, h = img.size
    if min(w, h) < MIN_SIDE:
        raise ValidationError(
            f"Gambar terlalu kecil ({w}×{h} px). Minimal {MIN_SIDE}×{MIN_SIDE} px "
            "supaya tidak pecah saat ditampilkan — upload versi yang lebih besar."
        )

    if square:
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        w = h = s

    if max(w, h) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    if fmt == "png":
        # Lossless — right for QR codes. Shrink further if it lands very large.
        data = _encode_png(img)
        if len(data) > TARGET_BYTES * 2 and max(img.size) > 1024:
            img.thumbnail((1024, 1024), Image.LANCZOS)
            data = _encode_png(img)
        return ContentFile(data, name=f"{uuid.uuid4().hex}.png")

    # WebP — step quality down until it fits TARGET_BYTES.
    data = _encode(img, has_alpha, _QUALITY_STEPS[0])
    for q in _QUALITY_STEPS[1:]:
        if len(data) <= TARGET_BYTES:
            break
        data = _encode(img, has_alpha, q)

    return ContentFile(data, name=f"{uuid.uuid4().hex}.webp")


def _encode_png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_placeholder(text: str, *, size=(1200, 900), seed: str | None = None) -> ContentFile:
    """Generate a simple branded placeholder image (used by seed commands)."""
    import colorsys
    import hashlib

    from PIL import Image, ImageDraw

    key = seed or text
    hue = int(hashlib.md5(key.encode()).hexdigest(), 16) % 360 / 360
    r, g, b = (int(c * 255) for c in colorsys.hls_to_rgb(hue, 0.45, 0.55))
    img = Image.new("RGB", size, (r, g, b))
    d = ImageDraw.Draw(img)
    initials = "".join(w[0] for w in text.split()[:2]).upper() or "•"
    # No bundled TTF — use the default bitmap font, scaled up by drawing large.
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=min(size) // 3)
    except TypeError:  # older Pillow: load_default() takes no size
        from PIL import ImageFont
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), initials, font=font)
    d.text(((size[0] - (bbox[2] - bbox[0])) / 2, (size[1] - (bbox[3] - bbox[1])) / 2 - bbox[1]),
           initials, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80, method=6)
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4().hex}.webp")


def _encode(img, has_alpha: bool, quality: int) -> bytes:
    buf = io.BytesIO()
    params = {"format": "WEBP", "quality": quality, "method": 6}
    if not has_alpha:
        img.save(buf, **params)
    else:
        img.save(buf, exact=True, **params)
    return buf.getvalue()
