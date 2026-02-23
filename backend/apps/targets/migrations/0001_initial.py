from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0004_department_default_reporter"),
    ]

    operations = [
        migrations.CreateModel(
            name="Period",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField()),
                ("name", models.CharField(max_length=64)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-month", "start_date", "id"],
                "unique_together": {("month", "name")},
            },
        ),
        migrations.CreateModel(
            name="DepartmentMonthTarget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_month", models.DateField()),
                ("target_count", models.PositiveIntegerField(default=0)),
                ("target_amount", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="month_targets",
                        to="accounts.department",
                    ),
                ),
            ],
            options={
                "ordering": ["-target_month", "department__code"],
                "unique_together": {("department", "target_month")},
            },
        ),
        migrations.CreateModel(
            name="DepartmentPeriodTarget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_count", models.PositiveIntegerField(default=0)),
                ("target_amount", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="period_targets",
                        to="accounts.department",
                    ),
                ),
                (
                    "period",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="department_targets",
                        to="targets.period",
                    ),
                ),
            ],
            options={
                "ordering": ["period__month", "department__code"],
                "unique_together": {("period", "department")},
            },
        ),
    ]
