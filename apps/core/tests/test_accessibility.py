from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization


class AccessibilityFoundationTests(TestCase):
    def setUp(self):
        organization = Organization.objects.create(name="Accessible Corp", slug="accessible-corp")
        self.user = get_user_model().objects.create_user(
            username="accessible-engineer",
            organization=organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.client.force_login(self.user)

    def test_application_shell_contains_keyboard_and_mobile_landmarks(self):
        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": self.user.role})
        )

        self.assertContains(response, 'href="#contenu"', html=False)
        self.assertContains(response, 'id="contenu"', html=False)
        self.assertContains(response, 'aria-controls="navigation"', html=False)
        self.assertContains(response, 'aria-expanded="false"', html=False)
        self.assertContains(response, 'id="app-header"', html=False)

    def test_shared_modals_have_accessible_naming_and_focus_management(self):
        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": self.user.role})
        )

        self.assertContains(response, 'aria-labelledby="delete-confirm-title"', html=False)
        self.assertContains(response, "modalTrigger = trigger", html=False)
        self.assertContains(response, "modalTrigger?.focus()", html=False)
        self.assertContains(response, "prefers-reduced-motion", html=False)
