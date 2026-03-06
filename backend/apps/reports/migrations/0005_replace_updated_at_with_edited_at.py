from django.db import migrations, models


def backfill_edited_at(apps, schema_editor):
    DailyDepartmentReport = apps.get_model("reports", "DailyDepartmentReport")
    for report in DailyDepartmentReport.objects.all().only("id", "created_at", "updated_at"):
        if report.updated_at and report.created_at and report.updated_at > report.created_at:
            report.edited_at = report.updated_at
            report.save(update_fields=["edited_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0004_dailydepartmentreport_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailydepartmentreport",
            name="edited_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_edited_at, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="dailydepartmentreport",
            name="updated_at",
        ),
    ]
