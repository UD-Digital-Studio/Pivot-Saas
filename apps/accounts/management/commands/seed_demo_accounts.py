from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership
from apps.inventory.models import StockItem
from apps.collaboration.models import ProjectComment, ProjectDocument, ProjectImage


class Command(BaseCommand):
    help = "Crée ou actualise les comptes et projets de démonstration."

    accounts = (
        {
            "username": "client1",
            "password": "client12345",
            "role": "client",
            "email": "client1@pivot.local",
        },
        {
            "username": "chef1",
            "password": "chef12345",
            "role": "site_manager",
            "email": "chef1@pivot.local",
        },
    )

    projects = (
        {
            "name": "Résidence Bonapriso",
            "description": "Construction d'un immeuble résidentiel moderne de quatre niveaux.",
            "location": "Bonapriso, Douala",
            "project_date": date(2026, 9, 5),
            "status": Project.Status.ONGOING,
            "budget_amount": Decimal("85000000"),
        },
        {
            "name": "Centre commercial Akwa",
            "description": "Aménagement et extension d'un espace commercial au centre-ville.",
            "location": "Akwa, Douala",
            "project_date": date(2026, 10, 12),
            "status": Project.Status.PENDING,
            "budget_amount": Decimal("120000000"),
        },
        {
            "name": "Villa contemporaine Bastos",
            "description": "Construction clé en main d'une villa avec piscine et dépendances.",
            "location": "Bastos, Yaoundé",
            "project_date": date(2026, 7, 18),
            "status": Project.Status.ONGOING,
            "budget_amount": Decimal("65000000"),
        },
        {
            "name": "Réhabilitation école primaire",
            "description": "Réfection des salles de classe, sanitaires et réseaux électriques.",
            "location": "Bafoussam",
            "project_date": date(2026, 5, 10),
            "status": Project.Status.COMPLETE,
            "budget_amount": Decimal("32000000"),
        },
    )

    stock_items = (
        ("Ciment CPJ 42.5", "sac", "6500", "180", "35", StockItem.Status.VERIFIED),
        ("Fer à béton 12 mm", "barre", "7200", "95", "20", StockItem.Status.VERIFIED),
        ("Sable carrière", "m³", "18500", "22", "8", StockItem.Status.APPROVED),
        ("Parpaings 15 cm", "unité", "550", "620", "120", StockItem.Status.PENDING),
    )

    @transaction.atomic
    def handle(self, *args, **options):
        organization = Organization.objects.filter(slug="001").first()
        if organization is None:
            organization = Organization.objects.order_by("created_at").first()
        if organization is None:
            organization = Organization.objects.create(name="Genius", slug="001")

        user_model = get_user_model()
        engineer = user_model.objects.filter(
            organization=organization,
            role=user_model.Role.ENGINEER,
            is_active=True,
        ).first()
        if engineer is None:
            self.stdout.write(
                self.style.ERROR("Aucun ingénieur actif disponible pour les projets.")
            )
            return

        existing_project = (
            Project.objects.filter(organization=organization).order_by("created_at").first()
        )
        demo_projects = []
        for seed in self.projects:
            project, created = Project.objects.update_or_create(
                organization=organization,
                name=seed["name"],
                defaults={**seed, "engineer": engineer},
            )
            demo_projects.append(project)
            state = "créé" if created else "actualisé"
            self.stdout.write(self.style.SUCCESS(f"Projet {project.name} {state}."))

        assigned_projects = demo_projects
        if existing_project and existing_project not in assigned_projects:
            assigned_projects.insert(0, existing_project)

        demo_users = {}
        for seed in self.accounts:
            user, created = user_model.objects.update_or_create(
                username=seed["username"],
                defaults={
                    "organization": organization,
                    "role": seed["role"],
                    "email": seed["email"],
                    "is_active": True,
                },
            )
            user.set_password(seed["password"])
            user.save(update_fields=("password",))

            project_role = {
                user_model.Role.CLIENT: ProjectMembership.Role.OWNER,
                user_model.Role.SITE_MANAGER: ProjectMembership.Role.SITE_MANAGER,
                user_model.Role.CONTRACTOR: ProjectMembership.Role.CONTRACTOR,
                user_model.Role.ENGINEER: ProjectMembership.Role.ENGINEER,
            }.get(seed["role"], ProjectMembership.Role.SITE_MANAGER)
            for project in assigned_projects:
                ProjectMembership.objects.update_or_create(
                    organization=organization,
                    project=project,
                    user=user,
                    defaults={"project_role": project_role},
                )

            state = "créé" if created else "actualisé"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{user.username} {state} et affecté à {len(assigned_projects)} projets."
                )
            )
            demo_users[seed["role"]] = user

        client_user = demo_users[user_model.Role.CLIENT]
        manager = demo_users[user_model.Role.SITE_MANAGER]
        image_source = settings.BASE_DIR / "static" / "images" / "auth-construction.png"
        for project in assigned_projects:
            for name, unit, unit_price, quantity, threshold, status in self.stock_items:
                StockItem.objects.update_or_create(
                    organization=organization,
                    project=project,
                    name=name,
                    defaults={
                        "unit": unit,
                        "unit_price": Decimal(unit_price),
                        "quantity": Decimal(quantity),
                        "alert_threshold": Decimal(threshold),
                        "status": status,
                        "created_by": manager,
                        "verified_by": engineer if status != StockItem.Status.PENDING else None,
                    },
                )

            for title, status, uploader in (
                ("Plan architectural", ProjectDocument.Status.APPROVED, client_user),
                ("Procès-verbal de chantier", ProjectDocument.Status.PENDING, manager),
            ):
                if not ProjectDocument.objects.filter(project=project, title=title).exists():
                    document = ProjectDocument(
                        organization=organization,
                        project=project,
                        title=title,
                        status=status,
                        uploaded_by=uploader,
                        reviewed_by=engineer if status == ProjectDocument.Status.APPROVED else None,
                    )
                    document.file.save(
                        f"{project.pk}-{title.lower().replace(' ', '-')}.pdf",
                        ContentFile(
                            b"%PDF-1.4\n% PIVOT demo document\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
                        ),
                        save=True,
                    )

            if not ProjectImage.objects.filter(
                project=project, caption="Vue générale du chantier"
            ).exists():
                with image_source.open("rb") as source:
                    image = ProjectImage(
                        organization=organization,
                        project=project,
                        caption="Vue générale du chantier",
                        is_cover=not ProjectImage.objects.filter(
                            project=project, is_cover=True
                        ).exists(),
                        uploaded_by=manager,
                    )
                    image.image.save(f"chantier-{project.pk}.png", File(source), save=True)

            for author, content in (
                (engineer, "Le planning de la semaine a été actualisé."),
                (manager, "Les matériaux principaux sont disponibles sur le chantier."),
                (client_user, "Merci, j’ai bien consulté les dernières informations."),
            ):
                ProjectComment.objects.get_or_create(
                    organization=organization,
                    project=project,
                    author=author,
                    content=content,
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Données métier ajoutées à {project.name} : stock, documents, photo et commentaires."
                )
            )
