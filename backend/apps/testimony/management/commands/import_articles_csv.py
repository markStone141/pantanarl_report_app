import csv
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.testimony.models import Article, Product


class Command(BaseCommand):
    help = "Import products.csv and articles.csv with idempotency"

    def add_arguments(self, parser):
        parser.add_argument("--products", required=True, help="Path to products.csv")
        parser.add_argument("--articles", required=True, help="Path to articles.csv")
        parser.add_argument("--errors", default="import_errors.csv", help="Output path for error rows")
        parser.add_argument("--source", default="legacy_testimony", help="Migration source label")

    @staticmethod
    def _parse_dt(value: str):
        value = (value or "").strip()
        if not value:
            return timezone.now()
        dt = parse_datetime(value)
        if dt is None:
            raise ValueError(f"invalid datetime: {value}")
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    def handle(self, *args, **options):
        products_path = Path(options["products"]).resolve()
        articles_path = Path(options["articles"]).resolve()
        errors_path = Path(options["errors"]).resolve()
        source = options["source"]

        product_map: dict[str, Product] = {}

        with transaction.atomic():
            with products_path.open("r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    legacy_id = (row.get("legacy_product_id") or "").strip()
                    name = (row.get("name") or "").strip()
                    if not name:
                        continue
                    defaults = {
                        "name": name,
                        "description": (row.get("description") or "").strip(),
                    }
                    if legacy_id:
                        product, _ = Product.objects.update_or_create(
                            legacy_product_id=int(legacy_id),
                            defaults=defaults,
                        )
                        product_map[legacy_id] = product
                    else:
                        product, _ = Product.objects.get_or_create(name=name, defaults=defaults)

            errors: list[dict[str, str]] = []
            with articles_path.open("r", encoding="utf-8-sig", newline="") as fa:
                reader = csv.DictReader(fa)
                for line_no, row in enumerate(reader, start=2):
                    try:
                        legacy_article_id = (row.get("legacy_article_id") or "").strip()
                        title = (row.get("title") or "").strip()
                        body = row.get("body") or ""
                        author = (row.get("author") or "").strip()
                        if not title or not author:
                            raise ValueError("title/author is required")

                        legacy_product_id = (row.get("legacy_product_id") or "").strip()
                        product = product_map.get(legacy_product_id) if legacy_product_id else None
                        if legacy_product_id and product is None:
                            raise ValueError(f"legacy_product_id not found: {legacy_product_id}")

                        defaults = {
                            "title": title,
                            "body": body,
                            "author": author,
                            "video_url": (row.get("video_url") or "").strip(),
                            "product": product,
                            "testimonied_at": parse_date((row.get("testimonied_at") or "").strip()) if row.get("testimonied_at") else None,
                            "created_at": self._parse_dt(row.get("created_at") or ""),
                            "updated_at": self._parse_dt(row.get("updated_at") or ""),
                            "migrated_at": timezone.now(),
                            "migration_source": source,
                        }

                        if legacy_article_id:
                            Article.objects.update_or_create(
                                legacy_article_id=int(legacy_article_id),
                                defaults=defaults,
                            )
                        else:
                            Article.objects.create(**defaults)
                    except Exception as exc:
                        errors.append(
                            {
                                "line": str(line_no),
                                "reason": str(exc),
                                "legacy_article_id": (row.get("legacy_article_id") or ""),
                                "title": (row.get("title") or ""),
                            }
                        )

        if errors:
            with errors_path.open("w", encoding="utf-8", newline="") as fe:
                writer = csv.DictWriter(fe, fieldnames=["line", "reason", "legacy_article_id", "title"])
                writer.writeheader()
                writer.writerows(errors)
            self.stdout.write(self.style.WARNING(f"Import completed with errors: {errors_path}"))
        else:
            self.stdout.write(self.style.SUCCESS("Import completed without errors."))
