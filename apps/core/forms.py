"""Reusable form fields."""
from django import forms

from apps.core.images import ACCEPT, HELP_TEXT, process_upload


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
