from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class LanguageSwitchTests(TestCase):
    def test_english_can_be_selected_from_login_page(self):
        response = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": reverse("accounts:login")},
        )
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "en")

        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, '<html lang="en"', html=False)
        self.assertContains(response, "Access your workspace.")
        self.assertContains(response, "Create an account:")

    def test_french_remains_the_default_language(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, "Accédez à votre espace de travail.")
