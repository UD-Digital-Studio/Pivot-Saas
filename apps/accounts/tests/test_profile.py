from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.organizations.models import Organization


class ProfileTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Profile Corp", slug="profile-corp")
        self.user = get_user_model().objects.create_user(
            username="profile-user",
            email="profile@example.test",
            password="profile-test-password",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )

    def test_profile_is_created_automatically_with_user(self):
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_profile_page_requires_authentication(self):
        response = self.client.get(reverse("accounts:profile"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:profile')}",
        )

    def test_user_can_open_profile_interface(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mon profil")
        self.assertContains(response, self.organization.name)

    def test_user_can_update_account_and_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "username": "profile-user-updated",
                "first_name": "Marie",
                "last_name": "Nana",
                "email": "marie@example.test",
                "phone": "+237600000000",
                "location": "Douala",
                "bio": "Ingénieure en génie civil.",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.username, "profile-user-updated")
        self.assertEqual(self.user.first_name, "Marie")
        self.assertEqual(self.user.profile.phone, "+237600000000")
        self.assertEqual(self.user.profile.location, "Douala")

    def test_duplicate_email_is_rejected(self):
        get_user_model().objects.create_user(
            username="other-profile-user",
            email="occupied@example.test",
            organization=self.organization,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:profile"),
            {
                "username": self.user.username,
                "first_name": "",
                "last_name": "",
                "email": "occupied@example.test",
                "phone": "",
                "location": "",
                "bio": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un autre compte utilise déjà cette adresse e-mail")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "profile@example.test")
