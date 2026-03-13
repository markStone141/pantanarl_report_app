from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("targets", "0003_status_fields"),
        ("dairymetrics", "0003_memberdailymetricentry_activity_closed"),
    ]

    operations = [
        migrations.CreateModel(
            name="MemberMonthMetricTarget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_month", models.DateField()),
                ("target_count", models.PositiveIntegerField(default=0)),
                ("target_amount", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_month_metric_targets", to="accounts.department")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="month_metric_targets", to="accounts.member")),
            ],
            options={
                "ordering": ["-target_month", "member__name", "department__code"],
            },
        ),
        migrations.CreateModel(
            name="MemberPeriodMetricTarget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_count", models.PositiveIntegerField(default=0)),
                ("target_amount", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_period_metric_targets", to="accounts.department")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="period_metric_targets", to="accounts.member")),
                ("period", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="member_metric_targets", to="targets.period")),
            ],
            options={
                "ordering": ["-period__start_date", "member__name", "department__code"],
            },
        ),
        migrations.AddConstraint(
            model_name="membermonthmetrictarget",
            constraint=models.UniqueConstraint(fields=("member", "department", "target_month"), name="unique_member_department_month_target"),
        ),
        migrations.AddConstraint(
            model_name="memberperiodmetrictarget",
            constraint=models.UniqueConstraint(fields=("member", "department", "period"), name="unique_member_department_period_target"),
        ),
    ]
