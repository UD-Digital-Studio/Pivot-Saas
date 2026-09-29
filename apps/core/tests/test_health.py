from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization


class HealthViewTests(TestCase):
    def test_home_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("core:home"))

        self.assertRedirects(response, reverse("accounts:login"))

    def test_health_endpoint_responds(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "PIVOT-SASS"})

    def test_health_endpoint_rejects_post(self):
        response = self.client.post(reverse("core:health"))

        self.assertEqual(response.status_code, 405)

    def test_private_health_redirects_anonymous_user(self):
        response = self.client.get(reverse("core:private-health"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)

    def test_private_health_accepts_authenticated_user(self):
        organization = Organization.objects.create(name="Test", slug="test")
        user = get_user_model().objects.create_user(
            username="smoke-test",
            password="test-only-password",
            organization=organization,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("core:private-health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "authenticated": True})
