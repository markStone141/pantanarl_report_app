from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.talks.models import KnowledgeReactionType


class Command(BaseCommand):
    help = "Seed only talks reaction types (icon master) from seed json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default="demo_data.json",
            help="Seed json file name under apps/talks/seed.",
        )

    def handle(self, *args, **options):
        data = self._load_seed(options["file"])
        payload = data.get("reaction_types", [])

        created_or_updated = 0
        for idx, item in enumerate(payload, start=1):
            code = (item.get("code") or "").strip()
            if not code:
                continue
            KnowledgeReactionType.objects.update_or_create(
                code=code,
                defaults={
                    "label": item.get("label") or code,
                    "icon_class": item.get("icon_class") or "fa-solid fa-circle",
                    "color": item.get("color") or "#126e82",
                    "sort_order": int(item.get("sort_order", idx * 10)),
                    "is_active": bool(item.get("is_active", True)),
                },
            )
            created_or_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Talks reaction types seed completed. ({created_or_updated} items)"
            )
        )

    def _load_seed(self, seed_file: str) -> dict:
        seed_path = Path(__file__).resolve().parents[2] / "seed" / seed_file
        if not seed_path.exists():
            raise CommandError(f"Seed file not found: {seed_path}")
        with seed_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
