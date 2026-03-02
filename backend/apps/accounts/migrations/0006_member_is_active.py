from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_member_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
