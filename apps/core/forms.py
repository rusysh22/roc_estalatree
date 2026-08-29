"""Reusable form fields."""
import re

from django import forms

from apps.core.images import ACCEPT, HELP_TEXT, process_upload


class RupiahInput(forms.TextInput):
    """A text input that shows a live thousand-separated amount as the user types
    (via `data-money` + site.js) and strips the separators back out on submit, so
    the bound field still receives a plain integer string.
    """

    def __init__(self, attrs=None):
        base = {"data-money": "", "inputmode": "numeric", "autocomplete": "off"}
        if attrs:
            base.update(attrs)
        super().__init__(base)

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        if value in (None, ""):
            return value
        return re.sub(r"[^\d]", "", str(value)) or ""


def clean_rupiah(raw) -> int:
    """Parse a possibly-formatted rupiah string ('Rp1.500.000', '1.500.000') → int."""
    return int(re.sub(r"[^\d]", "", str(raw or "")) or 0)


class ImageUploadField(forms.ImageField):
    """Drop-in ``ImageField`` that normalises whatever the user uploads.

    Django's ``ImageField`` already confirms the file decodes as an image; this
    subclass then runs :func:`apps.core.images.process_upload` so the value
    handed to the model is a right-sized, metadata-stripped WebP ``ContentFile``.
    Oversized dimensions/bytes are fixed silently; only unusable files raise.

    Pass ``square=True`` for avatars / logos to centre-crop to 1:1.
    """

    default_help_text = HELP_TEXT

    def __init__(self, *args, square: bool = False, fmt: str = "webp", **kwargs):
        self._square = square
        self._fmt = fmt
        kwargs.setdefault("help_text", self.default_help_text)
        widget = kwargs.pop("widget", None) or forms.FileInput(
            attrs={"class": "hidden", "accept": ACCEPT}
        )
        if hasattr(widget, "attrs"):
            widget.attrs.setdefault("accept", ACCEPT)
        super().__init__(*args, widget=widget, **kwargs)

    def clean(self, data, initial=None):
        value = super().clean(data, initial)
        # No new file this submission (kept existing, or cleared) → pass through.
        if not value or value is initial or not hasattr(value, "read"):
            return value
        return process_upload(value, square=self._square, fmt=self._fmt)
