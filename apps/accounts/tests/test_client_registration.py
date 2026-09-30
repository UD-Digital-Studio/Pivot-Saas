from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

class ClientRegistrationTests(TestCase):
    def setUp(self):
        self.data = {
            "username": "nouveau-client",
            "email": "client@example.test",
            "password1": "safe-client-password-42",
            "password2": "safe-client-password-42",
        }

    def test_page_does_not_expose_organizations(self):
        response = self.client.get(reverse("accounts:client-registration"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Créer un compte client")
        self.assertNotContains(response, 'name="organization"')

    def test_registration_creates_active_independent_client(self):
        response = self.client.post(reverse("accounts:client-registration"), self.data)
        self.assertRedirects(response, reverse("accounts:login"))
        user = get_user_model().objects.get(username="nouveau-client")
        self.assertTrue(user.is_active)
        self.assertEqual(user.role, get_user_model().Role.CLIENT)
        self.assertIsNone(user.organization)
        self.assertTrue(user.check_password(self.data["password1"]))

    def test_independent_client_can_log_in(self):
        self.client.post(reverse("accounts:client-registration"), self.data)
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.data["username"], "password": self.data["password1"]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:post-login"))

    def test_independent_client_sidebar_does_not_show_administration(self):
        self.client.post(reverse("accounts:client-registration"), self.data)
        user = get_user_model().objects.get(username="nouveau-client")
        self.client.force_login(user)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": user.Role.CLIENT})
        )

        self.assertContains(response, "Compte client indépendant")
        self.assertNotContains(response, ">Administration<")
