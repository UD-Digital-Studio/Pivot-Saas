from django.db import migrations


def seed_initial_plans(apps, schema_editor):
    plan_model = apps.get_model("subscriptions", "SubscriptionPlan")
    plans = (
        {
            "code": "essential",
            "name": "Essentiel",
            "description": "Pour l’ingénieur indépendant qui démarre ses premiers chantiers.",
            "monthly_price": 10_000,
            "yearly_price": 100_000,
            "max_active_projects": 3,
            "max_internal_members": 5,
            "storage_limit_mb": 5_120,
            "advanced_reports_enabled": False,
            "ai_assistant_enabled": False,
            "display_order": 10,
        },
        {
            "code": "professional",
            "name": "Professionnel",
            "description": "Pour une entreprise qui pilote plusieurs équipes et chantiers.",
            "monthly_price": 25_000,
            "yearly_price": 250_000,
            "max_active_projects": 15,
            "max_internal_members": 30,
            "storage_limit_mb": 20_480,
            "advanced_reports_enabled": True,
            "ai_assistant_enabled": True,
            "display_order": 20,
        },
        {
            "code": "enterprise",
            "name": "Entreprise",
            "description": "Pour les structures nécessitant des capacités et un accompagnement dédiés.",
            "monthly_price": 0,
            "yearly_price": 0,
            "max_active_projects": None,
            "max_internal_members": None,
            "storage_limit_mb": None,
            "advanced_reports_enabled": True,
            "ai_assistant_enabled": True,
            "display_order": 30,
        },
    )
    for values in plans:
        code = values.pop("code")
        plan_model.objects.update_or_create(code=code, defaults=values)


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0001_initial")]

    operations = [migrations.RunPython(seed_initial_plans, migrations.RunPython.noop)]
