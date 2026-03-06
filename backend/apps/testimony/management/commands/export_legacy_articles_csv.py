import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.testimony.models import Article, Product


class Command(BaseCommand):
    help = "Export products/articles to CSV for migration"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default=".", help="Output directory")

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"]).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        products_path = output_dir / "products.csv"
        articles_path = output_dir / "articles.csv"

        with products_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(["legacy_product_id", "name", "description"])
            for p in Product.objects.all().order_by("id"):
                writer.writerow([p.legacy_product_id or p.id, p.name, p.description or ""])

        with articles_path.open("w", encoding="utf-8", newline="") as fa:
            writer = csv.writer(fa)
            writer.writerow(
                [
                    "legacy_article_id",
                    "title",
                    "body",
                    "author",
                    "video_url",
                    "legacy_product_id",
                    "testimonied_at",
                    "created_at",
                    "updated_at",
                ]
            )
            for a in Article.objects.select_related("product").all().order_by("id"):
                writer.writerow(
                    [
                        a.legacy_article_id or a.id,
                        a.title,
                        a.body,
                        a.author,
                        a.video_url or "",
                        a.product.legacy_product_id if a.product else "",
                        a.testimonied_at.isoformat() if a.testimonied_at else "",
                        a.created_at.isoformat() if a.created_at else "",
                        a.updated_at.isoformat() if a.updated_at else "",
                    ]
                )

        self.stdout.write(self.style.SUCCESS(f"Exported: {products_path}"))
        self.stdout.write(self.style.SUCCESS(f"Exported: {articles_path}"))
