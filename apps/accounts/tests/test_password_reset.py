import re

from django.contrib.auth import authenticate, get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.organizations.models import Organization


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Reset Corp", slug="reset-corp")
        self.user = get_user_model().objects.create_user(
            username="reset-user",
            email="reset@example.test",
            password="old-reset-password-42",
            organization=organization,
            role=get_user_model().Role.CLIENT,
        )

    def test_password_reset_interface_is_available(self):
        response = self.client.get(reverse("accounts:password-reset"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Réinitialiser le mot de passe")

    def test_known_email_receives_reset_link(self):
        response = self.client.post(
            reverse("accounts:password-reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("accounts:password-reset-done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/comptes/mot-de-passe/confirmer/", mail.outbox[0].body)
        self.assertIn("images/Logo.png", mail.outbox[0].alternatives[0][0])

    def test_unknown_email_uses_same_confirmation_without_email(self):
        response = self.client.post(
            reverse("accounts:password-reset"),
            {"email": "unknown@example.test"},
        )

        self.assertRedirects(response, reverse("accounts:password-reset-done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_allows_setting_new_password(self):
        self.client.post(reverse("accounts:password-reset"), {"email": self.user.email})
        reset_path = re.search(r"http://testserver([^\s]+)", mail.outbox[0].body).group(1)

        redirect_response = self.client.get(reset_path)
        self.assertEqual(redirect_response.status_code, 302)
        set_password_path = redirect_response.url
        form_response = self.client.get(set_password_path)
        self.assertEqual(form_response.status_code, 200)

        new_password = "new-reset-password-84"
        response = self.client.post(
            set_password_path,
            {"new_password1": new_password, "new_password2": new_password},
        )

        self.assertRedirects(response, reverse("accounts:password-reset-complete"))
        self.assertIsNotNone(authenticate(username=self.user.username, password=new_password))
