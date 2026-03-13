from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dairymetrics", "0004_member_target_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="return_postal_amount",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="return_postal_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="return_qr_amount",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="return_qr_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="metricadjustment",
            name="return_postal_amount",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="metricadjustment",
            name="return_postal_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="metricadjustment",
            name="return_qr_amount",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="metricadjustment",
            name="return_qr_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
