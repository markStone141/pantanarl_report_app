from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.activity_sites.import_service import import_activity_sites


class Command(BaseCommand):
    help = "Import reviewed activity-site CSV and link historical records"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Reviewed CSV exported from the performance dashboard")
        parser.add_argument("--dry-run", action="store_true", help="Validate and roll back all database changes")
        parser.add_argument("--skip-backfill", action="store_true", help="Import master data without linking history")

    def handle(self, *args, **options):
        try:
            result = import_activity_sites(
                options["csv_path"],
                dry_run=options["dry_run"],
                backfill=not options["skip_backfill"],
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        linked = ", ".join(f"{key}={value}" for key, value in sorted(result.linked_counts.items())) or "skipped"
        mode = "DRY RUN" if result.dry_run else "APPLIED"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: sites={result.site_count}, aliases={result.alias_count}, linked({linked})"
        ))
