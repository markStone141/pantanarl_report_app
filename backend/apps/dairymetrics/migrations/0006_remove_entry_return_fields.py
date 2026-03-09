from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("dairymetrics", "0005_memberdailymetricentry_return_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="memberdailymetricentry",
            name="return_postal_amount",
        ),
        migrations.RemoveField(
            model_name="memberdailymetricentry",
            name="return_postal_count",
        ),
        migrations.RemoveField(
            model_name="memberdailymetricentry",
            name="return_qr_amount",
        ),
        migrations.RemoveField(
            model_name="memberdailymetricentry",
            name="return_qr_count",
        ),
    ]
