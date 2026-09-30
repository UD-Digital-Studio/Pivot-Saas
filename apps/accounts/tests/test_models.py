from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.organizations.models import Organization


class UserOrganizationTests(TestCase):
    def setUp(self):
        self.alpha = Organization.objects.create(name="Alpha Construction", slug="alpha")
        self.beta = Organization.objects.create(name="Beta Construction", slug="beta")

    def test_business_user_belongs_to_an_organization(self):
        user = get_user_model().objects.create_user(
            username="engineer-alpha",
            organization=self.alpha,
            role=get_user_model().Role.ENGINEER,
        )

        self.assertEqual(user.organization, self.alpha)
        self.assertEqual(user.role, get_user_model().Role.ENGINEER)

    def test_non_client_without_organization_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create_user(
                username="orphan-user", role=get_user_model().Role.ENGINEER
            )

    def test_client_can_exist_without_organization(self):
        client = get_user_model().objects.create_user(
            username="independent-client", role=get_user_model().Role.CLIENT
        )
        self.assertIsNone(client.organization)

    def test_organization_filter_does_not_return_other_tenant_users(self):
        user_alpha = get_user_model().objects.create_user(
            username="alpha-user",
            organization=self.alpha,
        )
        get_user_model().objects.create_user(
            username="beta-user",
            organization=self.beta,
        )

        alpha_users = get_user_model().objects.filter(organization=self.alpha)

        self.assertQuerySetEqual(alpha_users, [user_alpha], transform=lambda user: user)

    def test_superuser_can_exist_without_business_organization(self):
        superuser = get_user_model().objects.create_superuser(
            username="platform-admin",
            email="admin@example.test",
            password="test-only-password",
        )

        self.assertIsNone(superuser.organization)
