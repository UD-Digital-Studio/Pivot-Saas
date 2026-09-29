from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Invitation, User
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPlan
from apps.subscriptions.quotas import (
    ensure_internal_member_capacity,
    ensure_project_capacity,
    quota_usage,
)


class QuotaTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Quota", slug="quota")
        self.plan = SubscriptionPlan.objects.create(
            name="Limité", code="limited-test", monthly_price=1, yearly_price=10,
            max_active_projects=1, max_internal_members=2,
        )
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=self.plan,
            status=OrganizationSubscription.Status.TRIAL,
            trial_started_at=now, trial_ends_at=now + timezone.timedelta(days=90),
            plan_snapshot=self.plan.snapshot(),
        )
        self.engineer = User.objects.create_user(
            username="quota-engineer", password="password123", organization=self.organization,
            role=User.Role.ENGINEER,
        )

    def test_completed_projects_and_clients_do_not_consume_quotas(self):
        User.objects.create_user(username="quota-client", organization=self.organization, role=User.Role.CLIENT)
        Project.objects.create(
            organization=self.organization, engineer=self.engineer, name="Terminé",
            location="Yaoundé", project_date=date.today(), status=Project.Status.COMPLETE,
        )
        usage = quota_usage(self.organization)
        self.assertEqual(usage["projects"].used, 0)
        self.assertEqual(usage["members"].used, 1)

    def test_active_project_limit_is_enforced_and_completion_releases_slot(self):
        project = Project.objects.create(
            organization=self.organization, engineer=self.engineer, name="Actif",
            location="Douala", project_date=date.today(), status=Project.Status.ONGOING,
        )
        with self.assertRaises(ValidationError):
            ensure_project_capacity(self.organization)
        project.status = Project.Status.COMPLETE
        project.save(update_fields=("status",))
        ensure_project_capacity(self.organization)

    def test_internal_invitation_reserves_capacity(self):
        Invitation.objects.create(
            organization=self.organization, invited_by=self.engineer,
            email="manager@example.com", role=User.Role.SITE_MANAGER, token_hash="a" * 64,
        )
        usage = quota_usage(self.organization)
        self.assertEqual(usage["members"].used, 2)
        self.assertTrue(usage["members"].reached)
        with self.assertRaises(ValidationError):
            ensure_internal_member_capacity(self.organization, User.Role.SITE_MANAGER)
        ensure_internal_member_capacity(self.organization, User.Role.CLIENT)
