import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Invitation
from apps.organizations.models import Organization


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitationFlowTests(TestCase):
    password = "member-acceptance-password-42"

    def setUp(self):
        self.organization = Organization.objects.create(name="Invite Corp", slug="invite-corp")
        self.engineer = get_user_model().objects.create_user(
            username="inviting-engineer",
            password="engineer-test-password",
            email="engineer@invite.test",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )

    def send_invitation(self, email="client@invite.test", role=None):
        self.client.force_login(self.engineer)
        response = self.client.post(
            reverse("accounts:invite-member"),
            {
                "email": email,
                "role": role or get_user_model().Role.CLIENT,
            },
        )
        token_match = re.search(r"/comptes/invitation/([^/\s]+)/", mail.outbox[-1].body)
        self.assertIsNotNone(token_match)
        return response, token_match.group(1)

    def test_engineer_can_open_invitation_interface(self):
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("accounts:invite-member"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inviter un membre")
        self.assertContains(response, self.organization.name)

    def test_client_cannot_open_invitation_interface(self):
        client_user = get_user_model().objects.create_user(
            username="ordinary-client-invite",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(client_user)

        response = self.client.get(reverse("accounts:invite-member"))

        self.assertEqual(response.status_code, 403)

    def test_invitation_sends_email_without_storing_raw_token(self):
        response, raw_token = self.send_invitation()

        self.assertRedirects(
            response,
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER}),
        )
        invitation = Invitation.objects.get(email="client@invite.test")
        self.assertEqual(invitation.organization, self.organization)
        self.assertEqual(invitation.role, get_user_model().Role.CLIENT)
        self.assertNotEqual(invitation.token_hash, raw_token)
        self.assertNotIn(raw_token, invitation.token_hash)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("images/Logo.png", mail.outbox[0].alternatives[0][0])

    def test_invited_client_accepts_and_joins_correct_organization(self):
        _, raw_token = self.send_invitation()
        self.client.logout()

        response = self.client.post(
            reverse("accounts:accept-invitation", kwargs={"token": raw_token}),
            {
                "username": "accepted-client",
                "password1": self.password,
                "password2": self.password,
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user = get_user_model().objects.get(username="accepted-client")
        self.assertEqual(user.email, "client@invite.test")
        self.assertEqual(user.organization, self.organization)
        self.assertEqual(user.role, get_user_model().Role.CLIENT)
        self.assertTrue(user.is_active)
        invitation = Invitation.objects.get(email="client@invite.test")
        self.assertIsNotNone(invitation.accepted_at)

    def test_used_invitation_cannot_be_reused(self):
        _, raw_token = self.send_invitation()
        acceptance_url = reverse("accounts:accept-invitation", kwargs={"token": raw_token})
        self.client.post(
            acceptance_url,
            {
                "username": "first-member",
                "password1": self.password,
                "password2": self.password,
            },
        )

        response = self.client.get(acceptance_url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(get_user_model().objects.filter(email="client@invite.test").count(), 1)

    def test_expired_invitation_is_rejected(self):
        _, raw_token = self.send_invitation()
        Invitation.objects.filter(email="client@invite.test").update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        response = self.client.get(
            reverse("accounts:accept-invitation", kwargs={"token": raw_token})
        )

        self.assertEqual(response.status_code, 404)

    def test_expired_invitation_is_closed_and_visible_in_history(self):
        self.send_invitation()
        Invitation.objects.filter(email="client@invite.test").update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        invitation = Invitation.objects.get(email="client@invite.test")

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": self.engineer.role})
        )

        self.assertEqual(invitation.state, Invitation.State.EXPIRED)
        self.assertFalse(invitation.is_usable)
        self.assertFalse(Invitation.objects.active().filter(pk=invitation.pk).exists())
        self.assertTrue(Invitation.objects.closed().filter(pk=invitation.pk).exists())
        self.assertContains(response, "Historique des invitations")
        self.assertContains(response, "Expirée")
        self.assertNotContains(response, f'modal-cancel-invitation-{invitation.pk}')

    def test_new_invitation_is_allowed_after_expiration(self):
        self.send_invitation()
        Invitation.objects.filter(email="client@invite.test").update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        response, _ = self.send_invitation()

        self.assertRedirects(
            response,
            reverse("accounts:dashboard", kwargs={"role": self.engineer.role}),
        )
        self.assertEqual(Invitation.objects.filter(email="client@invite.test").count(), 2)

    def test_active_duplicate_invitation_is_not_sent(self):
        self.send_invitation()

        response = self.client.post(
            reverse("accounts:invite-member"),
            {"email": "client@invite.test", "role": get_user_model().Role.CLIENT},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Une invitation active existe déjà")
        self.assertEqual(Invitation.objects.filter(email="client@invite.test").count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_engineer_can_cancel_invitation_and_invalidate_link(self):
        _, raw_token = self.send_invitation()
        invitation = Invitation.objects.get(email="client@invite.test")

        response = self.client.post(
            reverse("accounts:cancel-invitation", kwargs={"pk": invitation.pk}),
            {"confirmed": "yes"},
        )

        self.assertRedirects(
            response,
            reverse("accounts:dashboard", kwargs={"role": self.engineer.role}),
        )
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.canceled_at)
        self.assertFalse(invitation.is_usable)
        self.client.logout()
        response = self.client.get(
            reverse("accounts:accept-invitation", kwargs={"token": raw_token})
        )
        self.assertEqual(response.status_code, 404)

    def test_new_invitation_is_allowed_after_cancellation(self):
        self.send_invitation()
        invitation = Invitation.objects.get(email="client@invite.test")
        self.client.post(
            reverse("accounts:cancel-invitation", kwargs={"pk": invitation.pk}),
            {"confirmed": "yes"},
        )

        response, _ = self.send_invitation()

        self.assertRedirects(
            response,
            reverse("accounts:dashboard", kwargs={"role": self.engineer.role}),
        )
        self.assertEqual(Invitation.objects.filter(email="client@invite.test").count(), 2)
