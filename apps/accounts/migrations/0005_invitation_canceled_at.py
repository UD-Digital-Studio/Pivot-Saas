from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_notification")]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="canceled_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="annulée le"),
        ),
    ]
