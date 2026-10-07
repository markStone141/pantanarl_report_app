from django.db import migrations


def add_un_kansai(apps, schema_editor):
    Department = apps.get_model("accounts", "Department")
    # Empty installations are initialized by the supported seed command.
    if not Department.objects.using(schema_editor.connection.alias).exists():
        return
    Department.objects.using(schema_editor.connection.alias).get_or_create(
        code="UN_KANSAI", defaults={"name": "UN関西"}
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_department_target_history_visibility")]

    # Preserve both departments and their reports on rollback as well.
    operations = [migrations.RunPython(add_un_kansai, migrations.RunPython.noop)]
