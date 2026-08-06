from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_member_un_activity_code"),
        ("dairymetrics", "0019_membermetrictransactionreactionnotificationstate"),
    ]

    operations = [
        migrations.CreateModel(
            name="MemberMetricTransactionNotificationState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "member",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metric_transaction_notification_state",
                        to="accounts.member",
                    ),
                ),
            ],
            options={
                "verbose_name": "新規決済通知確認状態",
                "verbose_name_plural": "新規決済通知確認状態",
            },
        ),
    ]
