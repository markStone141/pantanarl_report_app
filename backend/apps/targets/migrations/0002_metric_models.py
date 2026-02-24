from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_department_default_reporter"),
        ("targets", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TargetMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32)),
                ("label", models.CharField(max_length=64)),
                ("unit", models.CharField(blank=True, max_length=16)),
                ("display_order", models.PositiveIntegerField(default=1)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="target_metrics",
                        to="accounts.department",
                    ),
                ),
            ],
            options={
                "ordering": ["department__code", "display_order", "id"],
                "unique_together": {("department", "code")},
            },
        ),
        migrations.CreateModel(
            name="MonthTargetMetricValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_month", models.DateField()),
                ("value", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="month_metric_values",
                        to="accounts.department",
                    ),
                ),
                (
                    "metric",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="month_values",
                        to="targets.targetmetric",
                    ),
                ),
            ],
            options={
                "ordering": ["-target_month", "department__code", "metric__display_order", "id"],
                "unique_together": {("department", "target_month", "metric")},
            },
        ),
        migrations.CreateModel(
            name="PeriodTargetMetricValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="period_metric_values",
                        to="accounts.department",
                    ),
                ),
                (
                    "metric",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="period_values",
                        to="targets.targetmetric",
                    ),
                ),
                (
                    "period",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metric_values",
                        to="targets.period",
                    ),
                ),
            ],
            options={
                "ordering": ["period__month", "department__code", "metric__display_order", "id"],
                "unique_together": {("period", "department", "metric")},
            },
        ),
    ]
