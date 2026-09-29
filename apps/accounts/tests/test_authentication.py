from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization


class AuthenticationFlowTests(TestCase):
    password = "valid-test-password-42"

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Pivot Construction",
            slug="pivot-construction",
        )

    def create_user(self, username, role, **overrides):
        return get_user_model().objects.create_user(
            username=username,
            password=self.password,
            organization=self.organization,
            role=role,
            **overrides,
        )

    def test_login_page_is_available(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertContains(response, "Connexion")

    def test_valid_login_redirects_each_business_role(self):
        for index, (role, _) in enumerate(get_user_model().Role.choices):
            with self.subTest(role=role):
                user = self.create_user(f"user-{index}", role)

                response = self.client.post(
                    reverse("accounts:login"),
                    {"username": user.username, "password": self.password},
                )

                self.assertRedirects(
                    response,
                    reverse("accounts:post-login"),
                    fetch_redirect_response=False,
                )
                role_response = self.client.get(reverse("accounts:post-login"))
                self.assertRedirects(
                    role_response,
                    reverse("accounts:dashboard", kwargs={"role": role}),
                )
                self.client.logout()

    def test_post_login_redirects_to_role_dashboard(self):
        user = self.create_user("engineer", get_user_model().Role.ENGINEER)
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:post-login"))

        self.assertRedirects(
            response,
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER}),
        )

    def test_superuser_uses_custom_platform_dashboard_instead_of_django_admin(self):
        superuser = get_user_model().objects.create_superuser(
            username="application-superuser",
            password=self.password,
            role=get_user_model().Role.ADMIN,
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("core:home"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[-1][0],
            reverse("superadmin:dashboard"),
        )
        self.assertTemplateUsed(response, "superadmin/dashboard.html")
        self.assertNotContains(response, reverse("admin:index"))
        self.assertContains(response, f'action="{reverse("accounts:logout")}"')
        self.assertContains(response, "Déconnexion")

    def test_user_cannot_open_another_role_dashboard(self):
        user = self.create_user("client", get_user_model().Role.CLIENT)
        self.client.force_login(user)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER})
        )

        self.assertEqual(response.status_code, 404)

    def test_invalid_credentials_do_not_open_a_session(self):
        self.create_user("known-user", get_user_model().Role.CLIENT)

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "known-user", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Identifiant ou mot de passe incorrect")

    def test_suspended_organization_cannot_log_in(self):
        self.organization.status = Organization.Status.SUSPENDED
        self.organization.save(update_fields=["status"])
        user = self.create_user("suspended-user", get_user_model().Role.ENGINEER)

        response = self.client.post(
            reverse("accounts:login"),
            {"username": user.username, "password": self.password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Identifiant ou mot de passe incorrect")

    def test_logout_post_invalidates_session(self):
        user = self.create_user("logout-user", get_user_model().Role.CLIENT)
        self.client.force_login(user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_get_is_not_allowed(self):
        user = self.create_user("logout-get-user", get_user_model().Role.CLIENT)
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 405)
