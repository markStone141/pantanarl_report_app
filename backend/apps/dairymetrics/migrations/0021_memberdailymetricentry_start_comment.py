from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dairymetrics", "0020_membermetrictransactionnotificationstate"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="start_comment",
            field=models.TextField(blank=True, default=""),
        ),
    ]
