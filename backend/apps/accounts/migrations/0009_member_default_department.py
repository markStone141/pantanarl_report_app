from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_remove_member_login_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="default_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="default_members",
                to="accounts.department",
            ),
        ),
    ]
