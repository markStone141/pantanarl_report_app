from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dairymetrics", "0006_remove_entry_return_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="memberdailymetricentry",
            name="input_source",
            field=models.CharField(
                choices=[("member", "本人入力"), ("admin", "管理者編集")],
                default="member",
                max_length=16,
            ),
        ),
    ]
