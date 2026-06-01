from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_member_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="show_in_dashboard_progress",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="department",
            name="show_in_dashboard_submission",
            field=models.BooleanField(default=True),
        ),
    ]
