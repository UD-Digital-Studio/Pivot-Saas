from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.services import activate_engineer
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.subscriptions.models import OrganizationSubscription, SubscriptionEvent


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EngineerRegistrationTests(TestCase):
    registration_data = {
        "organization_name": "Nouvelle Construction",
        "username": "new-engineer",
        "email": "engineer@example.test",
        "password1": "safe-registration-password-42",
        "password2": "safe-registration-password-42",
    }

    def test_registration_page_is_available(self):
        response = self.client.get(reverse("accounts:engineer-registration"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demande d’inscription")

    def test_registration_creates_inactive_engineer_and_organization(self):
        response = self.client.post(
            reverse("accounts:engineer-registration"),
            self.registration_data,
        )

        self.assertRedirects(response, reverse("accounts:registration-pending"))
        user = get_user_model().objects.get(username="new-engineer")
        self.assertFalse(user.is_active)
        self.assertEqual(user.role, get_user_model().Role.ENGINEER)
        self.assertEqual(user.organization.name, "Nouvelle Construction")

    def test_inactive_engineer_cannot_log_in(self):
        self.client.post(reverse("accounts:engineer-registration"), self.registration_data)

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.registration_data["username"],
                "password": self.registration_data["password1"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_email_does_not_create_second_organization(self):
        self.client.post(reverse("accounts:engineer-registration"), self.registration_data)
        second_data = {
            **self.registration_data,
            "organization_name": "Entreprise Orpheline",
            "username": "another-engineer",
        }

        response = self.client.post(reverse("accounts:engineer-registration"), second_data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Un compte utilise déjà cette adresse e-mail")
        self.assertFalse(Organization.objects.filter(name="Entreprise Orpheline").exists())

    def test_registration_emails_engineer_and_active_validation_responsibles(self):
        user_model = get_user_model()
        active_validator = user_model.objects.create_superuser(
            username="validator",
            email="validator@example.test",
            password="test-only-password",
        )
        user_model.objects.create_superuser(
            username="validator-without-email",
            email="",
            password="test-only-password",
        )
        inactive_validator = user_model.objects.create_superuser(
            username="inactive-validator",
            email="inactive@example.test",
            password="test-only-password",
        )
        inactive_validator.is_active = False
        inactive_validator.save(update_fields=("is_active",))

        self.client.post(reverse("accounts:engineer-registration"), self.registration_data)

        self.assertEqual(len(mail.outbox), 2)
        recipients = {message.to[0] for message in mail.outbox}
        self.assertEqual(
            recipients,
            {self.registration_data["email"], active_validator.email},
        )
        validation_email = next(
            message for message in mail.outbox if message.to == [active_validator.email]
        )
        self.assertIn("Nouvelle demande ingénieur", validation_email.subject)
        self.assertTrue(validation_email.alternatives)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    APP_BASE_URL="https://pivot.example.test",
)
class EngineerActivationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Activation", slug="activation")
        self.engineer = get_user_model().objects.create_user(
            username="pending-engineer",
            email="pending@example.test",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
            is_active=False,
        )
        self.platform_admin = get_user_model().objects.create_superuser(
            username="platform-admin-activation",
            password="test-only-password",
        )

    def test_superuser_activation_is_audited(self):
        activate_engineer(actor=self.platform_admin, engineer=self.engineer)

        self.engineer.refresh_from_db()
        self.assertTrue(self.engineer.is_active)
        event = AuditEvent.objects.get(action="account.engineer_activated")
        self.assertEqual(event.actor, self.platform_admin)
        self.assertEqual(event.organization, self.organization)
        self.assertEqual(event.target_id, str(self.engineer.pk))
        subscription = OrganizationSubscription.objects.get(organization=self.organization)
        self.assertEqual(subscription.status, OrganizationSubscription.Status.TRIAL)
        self.assertEqual(subscription.plan.code, "professional")
        self.assertEqual(
            (subscription.trial_ends_at.year - subscription.trial_started_at.year) * 12
            + subscription.trial_ends_at.month
            - subscription.trial_started_at.month,
            3,
        )

    def test_activation_is_idempotent(self):
        activate_engineer(actor=self.platform_admin, engineer=self.engineer)
        activate_engineer(actor=self.platform_admin, engineer=self.engineer)

        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(OrganizationSubscription.objects.count(), 1)
        self.assertEqual(SubscriptionEvent.objects.count(), 1)

    def test_activation_sends_branded_email_once_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            activate_engineer(actor=self.platform_admin, engineer=self.engineer)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.engineer.email])
        self.assertIn("activé", mail.outbox[0].subject)
        self.assertIn("https://pivot.example.test", mail.outbox[0].alternatives[0][0])

    def test_ordinary_user_cannot_activate_engineer(self):
        ordinary_user = get_user_model().objects.create_user(
            username="ordinary-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )

        with self.assertRaises(PermissionDenied):
            activate_engineer(actor=ordinary_user, engineer=self.engineer)

        self.engineer.refresh_from_db()
        self.assertFalse(self.engineer.is_active)
