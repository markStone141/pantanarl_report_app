from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dairymetrics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="daily_target_amount",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="daily_target_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
