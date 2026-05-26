from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dairymetrics", "0013_alter_membermetrictransaction_wv_result_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="membermonthmetrictarget",
            name="target_cs_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="membermonthmetrictarget",
            name="target_refugee_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="memberperiodmetrictarget",
            name="target_cs_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="memberperiodmetrictarget",
            name="target_refugee_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
