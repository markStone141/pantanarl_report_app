from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dairymetrics", "0016_wvmetriccancellation"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="activity_reminder_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
