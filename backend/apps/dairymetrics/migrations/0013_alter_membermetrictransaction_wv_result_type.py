from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dairymetrics", "0012_memberdailymetricentry_daily_target_cs_count_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="membermetrictransaction",
            name="wv_result_type",
            field=models.CharField(
                blank=True,
                choices=[("cs", "CS"), ("refugee", "難民"), ("both", "CS+難民")],
                max_length=16,
            ),
        ),
    ]
