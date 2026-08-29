"""List the WhatsApp Business templates that must be submitted for approval.

    python manage.py wa_templates

Copy each name / category / body into the kirim.chat (or Meta) template editor.
Once every template is approved, set the DB Setting WA_TEMPLATE_MODE to "on".
"""
from django.core.management.base import BaseCommand

from apps.notifications.templates_registry import all_templates_for_submission


class Command(BaseCommand):
    help = "List WABA templates to submit for approval."

    def handle(self, *args, **options):
        templates = all_templates_for_submission()
        self.stdout.write(f"{len(templates)} templates to submit:\n")
        for t in templates:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{t.name}  [{t.category} / {t.language}]"))
            if t.variables:
                for i, v in enumerate(t.variables, 1):
                    self.stdout.write(f"  {{{{{i}}}}} = {v}")
            self.stdout.write(f"  body: {t.body}")
