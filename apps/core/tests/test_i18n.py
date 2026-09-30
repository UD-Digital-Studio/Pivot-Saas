from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext, override


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

    def test_recent_product_areas_have_english_translations(self):
        expected = {
            "Nouvelle étape": "New step",
            "Progression vérifiée": "Verified progress",
            "Demander un retrait": "Request a withdrawal",
            "Enregistrer une visite": "Record a site visit",
            "Abonnements": "Subscriptions",
            "Validations et finances": "Validations and Finances",
            "Nouvelle déclaration": "New progress update",
            "Dépenses": "Expenses",
            "Preuves terrain": "Site evidence",
        }
        with override("en"):
            for source, translation in expected.items():
                with self.subTest(source=source):
                    self.assertEqual(gettext(source), translation)
