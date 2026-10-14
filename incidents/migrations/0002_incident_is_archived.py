from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("incidents", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="incident",
            name="is_archived",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
