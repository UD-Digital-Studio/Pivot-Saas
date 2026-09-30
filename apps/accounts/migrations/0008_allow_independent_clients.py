from django.db import migrations, models


def detach_clients_from_organizations(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="client").update(organization=None)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0007_contractor_led_owner_invitation")]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="account_business_user_has_organization",
        ),
        migrations.RunPython(
            detach_clients_from_organizations,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("organization__isnull", False))
                    | models.Q(("is_superuser", True))
                    | models.Q(("role", "client"))
                ),
                name="account_business_user_has_organization",
            ),
        ),
    ]
