from django.db import migrations, models


def set_existing_entries_to_admin(apps, schema_editor):
    MemberDailyMetricEntry = apps.get_model("dairymetrics", "MemberDailyMetricEntry")
    MemberDailyMetricEntry.objects.all().update(input_source="admin")


class Migration(migrations.Migration):
    dependencies = [
        ("dairymetrics", "0007_memberdailymetricentry_input_source"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memberdailymetricentry",
            name="input_source",
            field=models.CharField(
                choices=[("member", "本人入力"), ("admin", "管理者編集")],
                default="admin",
                max_length=16,
            ),
        ),
        migrations.RunPython(set_existing_entries_to_admin, migrations.RunPython.noop),
    ]
