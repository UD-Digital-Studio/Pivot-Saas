from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Notification
from apps.accounts.services import create_notification
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


class NotificationTests(TestCase):
    def setUp(self):
        self.alpha = Organization.objects.create(name="Notifications Alpha", slug="notif-alpha")
        self.beta = Organization.objects.create(name="Notifications Beta", slug="notif-beta")
        self.user = get_user_model().objects.create_user(
            username="notif-user", organization=self.alpha, role=get_user_model().Role.CLIENT
        )
        self.other = get_user_model().objects.create_user(
            username="notif-other", organization=self.beta, role=get_user_model().Role.CLIENT
        )
        self.notification = create_notification(
            recipient=self.user,
            kind=Notification.Kind.PROJECT,
            title="Projet actualisé",
            message="Une information visible.",
            target_url="/projets/",
        )
        create_notification(
            recipient=self.other,
            kind=Notification.Kind.PROJECT,
            title="Notification secrète",
        )

    def test_center_only_contains_current_users_notifications(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:notifications"))

        self.assertContains(response, "Projet actualisé")
        self.assertNotContains(response, "Notification secrète")
        self.assertEqual(response.context["unread_notification_count"], 1)

    def test_user_can_mark_own_notification_as_read(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:notification-read", kwargs={"pk": self.notification.pk})
        )

        self.assertRedirects(response, "/projets/", fetch_redirect_response=False)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)

    def test_user_cannot_mark_another_users_notification_as_read(self):
        foreign = self.other.notifications.get()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:notification-read", kwargs={"pk": foreign.pk})
        )

        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_read)

    def test_mark_all_only_updates_current_user(self):
        self.client.force_login(self.user)

        self.client.post(reverse("accounts:notifications-read-all"))

        self.assertFalse(self.user.notifications.filter(is_read=False).exists())
        self.assertTrue(self.other.notifications.filter(is_read=False).exists())

    def test_external_project_member_receives_and_opens_project_notification(self):
        project = Project.objects.create(
            organization=self.alpha,
            name="Projet inter-organisations",
            location="Yaoundé",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.alpha,
            project=project,
            user=self.user,
            project_role=ProjectMembership.Role.ENGINEER,
        )
        ProjectMembership.objects.create(
            organization=self.alpha,
            project=project,
            user=self.other,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )

        notification = create_notification(
            recipient=self.other,
            actor=self.user,
            project=project,
            kind=Notification.Kind.PROJECT,
            title="Projet actualisé",
            target_url=project.get_absolute_url(),
        )

        self.assertEqual(notification.organization, self.alpha)
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("accounts:notification-read", kwargs={"pk": notification.pk})
        )
        self.assertRedirects(response, project.get_absolute_url(), fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_non_member_cannot_send_project_notification(self):
        project = Project.objects.create(
            organization=self.alpha,
            name="Projet protégé",
            location="Douala",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.alpha,
            project=project,
            user=self.user,
            project_role=ProjectMembership.Role.ENGINEER,
        )

        with self.assertRaises(PermissionDenied):
            create_notification(
                recipient=self.user,
                actor=self.other,
                project=project,
                kind=Notification.Kind.PROJECT,
                title="Notification interdite",
            )
