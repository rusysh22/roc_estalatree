"""Convert any legacy WebP static-QRIS images to PNG.

QRIS images are now stored as lossless PNG (see apps/core/images.py `fmt="png"`)
so the code stays crisp and the buyer's "Download QRIS" gives a universally
openable file. This backfills sellers whose QRIS was uploaded before that change.

Usage:  python manage.py reprocess_qris_png
Idempotent — skips images already stored as .png.
"""
import io

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.accounts.models import SellerProfile


class Command(BaseCommand):
    help = "Re-encode legacy WebP static-QRIS images as PNG."

    def handle(self, *args, **options):
        from PIL import Image

        qs = SellerProfile.objects.exclude(qris_image="").exclude(qris_image__iendswith=".png")
        converted = 0
        for seller in qs:
            try:
                seller.qris_image.open("rb")
                img = Image.open(seller.qris_image).convert("RGB")
                seller.qris_image.close()
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                old = seller.qris_image.name
                seller.qris_image.save(
                    old.rsplit("/", 1)[-1].rsplit(".", 1)[0] + ".png",
                    ContentFile(buf.getvalue()), save=True,
                )
                converted += 1
                self.stdout.write(f"  {seller.slug}: {old} -> {seller.qris_image.name}")
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.WARNING(f"  {seller.slug}: skipped ({exc})"))
        self.stdout.write(self.style.SUCCESS(f"Done — {converted} converted."))
