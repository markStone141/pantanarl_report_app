from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0008_remove_member_login_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="MemberDailyMetricEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entry_date", models.DateField(default=django.utils.timezone.localdate)),
                ("approach_count", models.PositiveIntegerField(default=0)),
                ("communication_count", models.PositiveIntegerField(default=0)),
                ("result_count", models.PositiveIntegerField(default=0)),
                ("support_amount", models.PositiveIntegerField(default=0)),
                ("cs_count", models.PositiveIntegerField(default=0)),
                ("refugee_count", models.PositiveIntegerField(default=0)),
                ("location_name", models.CharField(blank=True, max_length=128)),
                ("memo", models.TextField(blank=True)),
                ("synced_to_report", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metric_entries", to="accounts.department")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metric_entries", to="accounts.member")),
            ],
            options={"ordering": ["-entry_date", "member__name", "department__code"]},
        ),
        migrations.CreateModel(
            name="MetricAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_date", models.DateField(default=django.utils.timezone.localdate)),
                ("source_type", models.CharField(choices=[("postal", "郵送"), ("increase", "増額"), ("other", "その他")], default="other", max_length=24)),
                ("approach_count", models.PositiveIntegerField(default=0)),
                ("communication_count", models.PositiveIntegerField(default=0)),
                ("result_count", models.PositiveIntegerField(default=0)),
                ("support_amount", models.PositiveIntegerField(default=0)),
                ("cs_count", models.PositiveIntegerField(default=0)),
                ("refugee_count", models.PositiveIntegerField(default=0)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_metric_adjustments", to=settings.AUTH_USER_MODEL)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metric_adjustments", to="accounts.department")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metric_adjustments", to="accounts.member")),
            ],
            options={"ordering": ["-target_date", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="memberdailymetricentry",
            constraint=models.UniqueConstraint(fields=("member", "department", "entry_date"), name="unique_member_department_entry_date"),
        ),
    ]
