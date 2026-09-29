from io import StringIO

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership
from apps.inventory.models import StockItem
from apps.collaboration.models import ProjectComment, ProjectDocument, ProjectImage


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class SeedDemoAccountsTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Genius", slug="001")
        self.engineer = get_user_model().objects.create_user(
            username="seed-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet seed",
            location="Douala",
            project_date="2026-08-20",
        )

    def test_command_creates_authenticatable_and_assigned_accounts(self):
        call_command("seed_demo_accounts", stdout=StringIO())

        client_user = authenticate(username="client1", password="client12345")
        manager = authenticate(username="chef1", password="chef12345")
        self.assertEqual(client_user.role, get_user_model().Role.CLIENT)
        self.assertEqual(manager.role, get_user_model().Role.SITE_MANAGER)
        self.assertTrue(
            ProjectMembership.objects.filter(project=self.project, user=client_user).exists()
        )
        self.assertTrue(
            ProjectMembership.objects.filter(project=self.project, user=manager).exists()
        )
        self.assertEqual(Project.objects.filter(organization=self.organization).count(), 5)
        self.assertEqual(StockItem.objects.filter(organization=self.organization).count(), 20)
        self.assertEqual(ProjectDocument.objects.filter(organization=self.organization).count(), 10)
        self.assertEqual(ProjectImage.objects.filter(organization=self.organization).count(), 5)
        self.assertEqual(ProjectComment.objects.filter(organization=self.organization).count(), 15)

    def test_command_is_idempotent(self):
        call_command("seed_demo_accounts", stdout=StringIO())
        call_command("seed_demo_accounts", stdout=StringIO())

        self.assertEqual(
            get_user_model().objects.filter(username__in=("client1", "chef1")).count(), 2
        )
        self.assertEqual(Project.objects.filter(organization=self.organization).count(), 5)
        self.assertEqual(
            ProjectMembership.objects.filter(user__username__in=("client1", "chef1")).count(),
            10,
        )
        self.assertEqual(StockItem.objects.filter(organization=self.organization).count(), 20)
        self.assertEqual(ProjectDocument.objects.filter(organization=self.organization).count(), 10)
        self.assertEqual(ProjectImage.objects.filter(organization=self.organization).count(), 5)
        self.assertEqual(ProjectComment.objects.filter(organization=self.organization).count(), 15)
