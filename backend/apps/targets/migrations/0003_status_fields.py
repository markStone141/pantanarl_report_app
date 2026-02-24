from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("targets", "0002_metric_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthtargetmetricvalue",
            name="status",
            field=models.CharField(
                choices=[("active", "active"), ("planned", "planned"), ("finished", "finished")],
                default="planned",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="period",
            name="status",
            field=models.CharField(
                choices=[("active", "active"), ("planned", "planned"), ("finished", "finished")],
                default="planned",
                max_length=16,
            ),
        ),
    ]
