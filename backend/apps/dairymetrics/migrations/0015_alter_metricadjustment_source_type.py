from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dairymetrics", "0014_member_scope_target_wv_counts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="metricadjustment",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("postal", "郵送"),
                    ("qr", "QR"),
                    ("increase", "増額"),
                    ("cs", "CS"),
                    ("refugee", "難民"),
                    ("cs_plus_refugee", "CS+難民"),
                    ("other", "その他"),
                ],
                default="other",
                max_length=24,
            ),
        ),
    ]
