from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("organizations", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("suspended", "Suspendue"),
                    ("archived", "Archivée"),
                ],
                default="active",
                max_length=16,
                verbose_name="statut",
            ),
        )
    ]
