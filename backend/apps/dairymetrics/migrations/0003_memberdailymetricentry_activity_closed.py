from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dairymetrics", "0002_memberdailymetricentry_daily_targets"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="activity_closed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="activity_closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
