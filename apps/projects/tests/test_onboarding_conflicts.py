from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Invitation
from apps.organizations.models import Organization
from apps.projects.models import (
    OnboardingConflictReview, Project, ProjectMembership, ProjectOnboarding,
    ProjectOwnership,
)
from apps.projects.services import activate_client_led_project, record_actor_confirmation


class OnboardingConflictTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Conflict Org", slug="conflict-org")
        self.superuser = get_user_model().objects.create_superuser(
            username="conflict-admin", password="Conflict-admin-12345!"
        )

    def make_ready_project(self, route, suffix):
        User = get_user_model()
        owner = User.objects.create_user(username=f"owner-{suffix}", organization=self.organization, role=User.Role.CLIENT)
        contractor = User.objects.create_user(username=f"contractor-{suffix}", organization=self.organization, role=User.Role.CONTRACTOR)
        engineer = User.objects.create_user(username=f"engineer-{suffix}", organization=self.organization, role=User.Role.ENGINEER)
        project = Project.objects.create(
            organization=self.organization, engineer=engineer, name=f"Project {suffix}",
            location="Douala", project_date="2027-01-01", budget_amount=1000000,
        )
        ProjectMembership.objects.create(organization=self.organization, project=project, user=owner, project_role="owner")
        ProjectMembership.objects.create(organization=self.organization, project=project, user=contractor, project_role="contractor")
        ProjectOwnership.objects.create(
            organization=self.organization, project=project, owner=owner,
            is_confirmed=True, confirmed_at=timezone.now(), confirmed_by=owner,
            terms_accepted=True, terms_version="v1",
        )
        ProjectOnboarding.objects.create(
            organization=self.organization, project=project, route=route,
            financial_conditions="Conditions confirmées", initiated_by=owner,
        )
        for user, role in ((owner, "owner"), (contractor, "contractor"), (engineer, "engineer")):
            record_actor_confirmation(user=user, project=project, project_role=role, accepted=True)
        return project, owner

    def test_probable_duplicate_is_flagged_without_automatic_merge(self):
        first, _ = self.make_ready_project(ProjectOnboarding.Route.CLIENT_LED, "same")
        second = Project.objects.create(
            organization=self.organization, name=first.name, location=first.location,
            project_date=first.project_date, budget_amount=1000000,
        )
        ProjectOnboarding.objects.create(
            organization=self.organization, project=second,
            route=ProjectOnboarding.Route.CONTRACTOR_LED,
            financial_conditions="Autre proposition", initiated_by=self.superuser,
        )
        review = second.onboarding_conflicts.get()
        self.assertEqual(review.reason, OnboardingConflictReview.Reason.PROBABLE_DUPLICATE)
        self.assertEqual(Project.objects.filter(pk__in=(first.pk, second.pk)).count(), 2)
        self.assertFalse(review.details["automatic_merge"])

    def test_conflict_requires_pivot_review_and_blocks_activation(self):
        project, owner = self.make_ready_project(ProjectOnboarding.Route.CLIENT_LED, "blocked")
        candidate = Project.objects.create(
            organization=self.organization, name="Candidate", location="Douala",
            project_date="2027-02-01", budget_amount=1,
        )
        review = OnboardingConflictReview.objects.create(
            organization=self.organization, project=project, candidate_project=candidate,
            reason=OnboardingConflictReview.Reason.OWNERSHIP_CONFLICT,
        )
        with self.assertRaisesMessage(Exception, "onboarding_conflict"):
            activate_client_led_project(actor=owner, project=project)
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:onboarding-conflict-resolve", args=(project.pk, review.pk)),
            {"confirmed": "yes", "resolution_note": "Deux chantiers réels distincts vérifiés."},
        )
        self.assertEqual(response.status_code, 302)
        review.refresh_from_db()
        self.assertEqual(review.status, OnboardingConflictReview.Status.RESOLVED)
        activate_client_led_project(actor=owner, project=project)
        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ONGOING)

    def test_all_three_routes_reach_activation_when_conflict_free(self):
        for route in ProjectOnboarding.Route.values:
            with self.subTest(route=route):
                project, owner = self.make_ready_project(route, route)
                activate_client_led_project(actor=owner, project=project)
                project.refresh_from_db()
                self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.ACTIVE)

    def test_invitation_expired_revoked_and_accepted_states(self):
        User = get_user_model()
        inviter = User.objects.create_user(username="inviter-conflicts", organization=self.organization, role=User.Role.ENGINEER)
        base = dict(organization=self.organization, invited_by=inviter, role=User.Role.CLIENT, project_role="", token_hash="a" * 64)
        expired = Invitation.objects.create(email="expired@example.com", expires_at=timezone.now() - timedelta(seconds=1), **base)
        base["token_hash"] = "b" * 64
        revoked = Invitation.objects.create(email="revoked@example.com", canceled_at=timezone.now(), **base)
        base["token_hash"] = "c" * 64
        accepted = Invitation.objects.create(email="accepted@example.com", accepted_at=timezone.now(), **base)
        self.assertFalse(expired.is_usable)
        self.assertFalse(revoked.is_usable)
        self.assertFalse(accepted.is_usable)
