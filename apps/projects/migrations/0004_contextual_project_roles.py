from django.db import migrations, models


def migrate_existing_roles(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    ProjectMembership = apps.get_model("projects", "ProjectMembership")
    User = apps.get_model("accounts", "User")

    ProjectMembership.objects.filter(project_role="client").update(project_role="owner")
    for project in Project.objects.all().iterator():
        ProjectMembership.objects.update_or_create(
            project_id=project.pk,
            user_id=project.engineer_id,
            defaults={
                "organization_id": project.organization_id,
                "project_role": "engineer",
            },
        )
        for reviewer_id in User.objects.filter(
            organization_id=project.organization_id, role="admin", is_active=True
        ).values_list("pk", flat=True):
            ProjectMembership.objects.update_or_create(
                project_id=project.pk,
                user_id=reviewer_id,
                defaults={
                    "organization_id": project.organization_id,
                    "project_role": "pivot_reviewer",
                },
            )


def reverse_existing_roles(apps, schema_editor):
    ProjectMembership = apps.get_model("projects", "ProjectMembership")
    ProjectMembership.objects.filter(project_role="owner").update(project_role="client")
    ProjectMembership.objects.filter(project_role__in=("engineer", "contractor", "pivot_reviewer")).delete()


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_projectstatushistory")]

    operations = [
        migrations.AlterField(
            model_name="projectmembership",
            name="project_role",
            field=models.CharField(
                choices=[
                    ("owner", "Propriétaire du chantier"),
                    ("contractor", "Entrepreneur"),
                    ("site_manager", "Responsable de chantier"),
                    ("engineer", "Ingénieur"),
                    ("pivot_reviewer", "Vérificateur PIVOT"),
                ],
                max_length=24,
                verbose_name="rôle projet",
            ),
        ),
        migrations.RunPython(migrate_existing_roles, reverse_existing_roles),
    ]
