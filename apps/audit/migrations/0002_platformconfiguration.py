import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform_name", models.CharField(default="PIVOT", max_length=80, verbose_name="nom de la plateforme")),
                ("support_email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail de support")),
                ("engineer_registration_enabled", models.BooleanField(default=True, verbose_name="inscription ingénieur autorisée")),
                ("client_registration_enabled", models.BooleanField(default=True, verbose_name="inscription client autorisée")),
                ("platform_notice", models.CharField(blank=True, max_length=300, verbose_name="message d’information")),
                ("notification_retention_days", models.PositiveSmallIntegerField(default=90, validators=[django.core.validators.MinValueValidator(7), django.core.validators.MaxValueValidator(365)], verbose_name="rétention des notifications (jours)")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="platform_configuration_updates", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "configuration de la plateforme", "verbose_name_plural": "configuration de la plateforme"},
        ),
    ]
