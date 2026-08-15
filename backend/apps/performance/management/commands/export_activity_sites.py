from pathlib import Path

from django.core.management.base import BaseCommand

from apps.performance.services.activity_site_export import (
    collect_activity_site_discovery_rows,
    write_activity_site_discovery_csv,
)


class Command(BaseCommand):
    help = "Export distinct historical activity-site names for master-data review"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="activity_sites.csv",
            help="Output CSV path (default: activity_sites.csv)",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = collect_activity_site_discovery_rows()
        with output_path.open("w", encoding="utf-8-sig", newline="") as output:
            write_activity_site_discovery_csv(output, rows)
        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} activity sites: {output_path}"))
