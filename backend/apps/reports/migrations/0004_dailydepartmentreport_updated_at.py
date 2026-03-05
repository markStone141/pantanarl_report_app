from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0003_dailydepartmentreportline_cs_count_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailydepartmentreport",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunSQL(
            sql="UPDATE reports_dailydepartmentreport SET updated_at = created_at WHERE updated_at IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="dailydepartmentreport",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
