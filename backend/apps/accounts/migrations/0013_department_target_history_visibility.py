from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_member_un_activity_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="department",
            name="show_in_target_history",
            field=models.BooleanField(default=True),
        ),
    ]
