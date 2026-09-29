from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization


class ClientRegistrationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Bâtisseurs", slug="batisseurs")
        self.suspended = Organization.objects.create(
            name="Suspendue", slug="suspendue", status=Organization.Status.SUSPENDED
        )
        self.data = {
            "organization": self.organization.pk,
            "username": "nouveau-client",
            "email": "client@example.test",
            "password1": "safe-client-password-42",
            "password2": "safe-client-password-42",
        }

    def test_page_exposes_only_active_organizations(self):
        response = self.client.get(reverse("accounts:client-registration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Créer un compte client")
        self.assertContains(response, self.organization.name)
        self.assertNotContains(response, self.suspended.name)

    def test_registration_creates_active_client_in_selected_organization(self):
        response = self.client.post(reverse("accounts:client-registration"), self.data)
        self.assertRedirects(response, reverse("accounts:login"))
        user = get_user_model().objects.get(username="nouveau-client")
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, get_user_model().Role.CLIENT)
        self.assertEqual(user.organization, self.organization)
        self.assertTrue(user.check_password(self.data["password1"]))

    def test_suspended_organization_is_rejected(self):
        response = self.client.post(
            reverse("accounts:client-registration"),
            {**self.data, "organization": self.suspended.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="nouveau-client").exists())
