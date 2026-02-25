from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Department
from apps.targets.models import TargetMetric

DEFAULT_DEPARTMENTS = [
    ("UN", "UN"),
    ("WV", "WV"),
    ("STYLE1", "Style1"),
    ("STYLE2", "Style2"),
]

DEFAULT_METRICS_BY_DEPARTMENT = {
    "UN": [("count", "件数", "件"), ("amount", "金額", "円")],
    "WV": [("cs_count", "CS件数", "件"), ("refugee_count", "難民支援件数", "件")],
    "STYLE1": [("amount", "金額", "円")],
    "STYLE2": [("amount", "金額", "円")],
}


class Command(BaseCommand):
    help = (
        "Seed default departments and target metrics only when both Department and "
        "TargetMetric tables are empty."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Apply upsert even if data already exists.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        force = options["force"]
        has_departments = Department.objects.exists()
        has_metrics = TargetMetric.objects.exists()

        if not force and (has_departments or has_metrics):
            self.stdout.write(
                self.style.WARNING(
                    "Skipped: data already exists. Use --force to upsert defaults."
                )
            )
            return

        created_depts = 0
        created_metrics = 0
        for code, name in DEFAULT_DEPARTMENTS:
            department, dept_created = Department.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "is_active": True,
                },
            )
            if dept_created:
                created_depts += 1

            for order, (metric_code, label, unit) in enumerate(
                DEFAULT_METRICS_BY_DEPARTMENT[code],
                start=1,
            ):
                _, metric_created = TargetMetric.objects.update_or_create(
                    department=department,
                    code=metric_code,
                    defaults={
                        "label": label,
                        "unit": unit,
                        "display_order": order,
                        "is_active": True,
                    },
                )
                if metric_created:
                    created_metrics += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed: departments(created={created_depts}), "
                f"metrics(created={created_metrics})."
            )
        )
