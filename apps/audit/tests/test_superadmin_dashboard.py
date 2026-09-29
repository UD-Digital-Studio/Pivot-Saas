import uuid
import os
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Invitation
from apps.collaboration.models import ProjectComment, ProjectDocument, ProjectImage
from apps.finance.models import PaymentTransaction, Withdrawal
from apps.organizations.models import Organization
from apps.projects.models import (
    Project, ProjectConciergeFollowUp, ProjectMembership, ProjectOnboarding, ProjectOwnership,
)
from apps.audit.control_room import adoption_metrics
from apps.audit.models import AuditEvent, PlatformConfiguration
from apps.planning.models import ProjectStage
from apps.inventory.models import StockItem, StockMovement


class SuperAdminDashboardTests(TestCase):
    password = "admin12345"

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Genius", slug="genius")
        cls.other_organization = Organization.objects.create(
            name="Pivot BTP", slug="pivot-btp", status=Organization.Status.SUSPENDED
        )
        users = get_user_model()
        cls.superuser = users.objects.create_superuser(
            username="platform-admin", password=cls.password, role=users.Role.ADMIN
        )
        cls.organization_admin = users.objects.create_user(
            username="organization-admin",
            password=cls.password,
            organization=cls.organization,
            role=users.Role.ADMIN,
            is_staff=True,
        )
        cls.engineer = users.objects.create_user(
            username="engineer-e11",
            password=cls.password,
            email="engineer-e11@example.com",
            organization=cls.organization,
            role=users.Role.ENGINEER,
        )
        cls.other_engineer = users.objects.create_user(
            username="other-engineer-e11",
            password=cls.password,
            organization=cls.other_organization,
            role=users.Role.ENGINEER,
        )
        cls.project = Project.objects.create(
            organization=cls.organization,
            engineer=cls.engineer,
            name="Tour Horizon",
            location="Douala",
            project_date=date(2026, 8, 25),
            status=Project.Status.ONGOING,
            budget_amount=20_000_000,
        )
        Project.objects.create(
            organization=cls.other_organization,
            engineer=cls.other_engineer,
            name="Résidence Littoral",
            location="Kribi",
            project_date=date(2026, 9, 1),
            status=Project.Status.PENDING,
            budget_amount=10_000_000,
        )
        ProjectDocument.objects.create(
            organization=cls.organization,
            project=cls.project,
            title="Plan à valider",
            file=SimpleUploadedFile("plan.pdf", b"%PDF-1.4 demo"),
            uploaded_by=cls.engineer,
            status=ProjectDocument.Status.VERIFIED,
        )
        PaymentTransaction.objects.create(
            organization=cls.organization,
            project=cls.project,
            user=cls.engineer,
            amount=500_000,
            currency="XAF",
            operator="MTN",
            payer_phone="690000000",
            idempotency_key=uuid.uuid4(),
            status=PaymentTransaction.Status.SUCCESS,
        )
        Withdrawal.objects.create(
            organization=cls.organization,
            project=cls.project,
            amount=100_000,
            reason="Achat ciment",
            requested_by=cls.engineer,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        url = reverse("superadmin:dashboard")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_organization_admin_is_forbidden(self):
        self.client.force_login(self.organization_admin)
        response = self.client.get(reverse("superadmin:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_open_custom_dashboard(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "superadmin/dashboard.html")
        self.assertContains(response, "Pilotage de la plateforme")
        self.assertNotContains(response, reverse("admin:index"))

    def test_dashboard_aggregates_all_organizations(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:dashboard"))
        self.assertEqual(response.context["platform_stats"]["organizations"], 2)
        self.assertEqual(response.context["platform_stats"]["active_organizations"], 1)
        self.assertEqual(response.context["platform_stats"]["users"], 3)
        self.assertEqual(response.context["platform_stats"]["projects"], 2)
        self.assertEqual(response.context["platform_stats"]["pending_validations"], 2)
        self.assertEqual(response.context["payment_totals"]["XAF"], 500_000)
        self.assertEqual(response.context["pending_withdrawal_total"], 100_000)
        self.assertContains(response, "Tour Horizon")
        self.assertContains(response, "Résidence Littoral")

    def test_organization_list_can_search_filter_and_sort(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("superadmin:organization-list"),
            {"q": "Pivot", "status": Organization.Status.SUSPENDED, "sort": "projects"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pivot BTP")
        self.assertNotContains(response, ">Genius<")
        organization = response.context["organization_page"].object_list[0]
        self.assertEqual(organization.project_count, 1)
        self.assertEqual(response.context["selected_status"], Organization.Status.SUSPENDED)

    def test_organization_detail_exposes_only_selected_tenant_data(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["organization_stats"]["users"], 2)
        self.assertEqual(response.context["organization_stats"]["projects"], 1)
        self.assertContains(response, "Tour Horizon")
        self.assertNotContains(response, "Résidence Littoral")

    def test_superuser_can_suspend_and_reactivate_an_organization_with_audit(self):
        self.client.force_login(self.superuser)
        url = reverse("superadmin:organization-status", args=(self.organization.pk,))
        response = self.client.post(url, {"status": Organization.Status.SUSPENDED})
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.SUSPENDED)
        event = AuditEvent.objects.get(action="organization.status_changed")
        self.assertEqual(event.actor, self.superuser)
        self.assertEqual(event.organization, self.organization)
        self.assertEqual(event.metadata["previous_status"], Organization.Status.ACTIVE)
        self.assertEqual(event.metadata["new_status"], Organization.Status.SUSPENDED)

        self.client.post(url, {"status": Organization.Status.ACTIVE})
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ACTIVE)
        self.assertEqual(AuditEvent.objects.filter(action="organization.status_changed").count(), 2)

    def test_organization_admin_cannot_change_organization_status(self):
        self.client.force_login(self.organization_admin)
        response = self.client.post(
            reverse("superadmin:organization-status", args=(self.organization.pk,)),
            {"status": Organization.Status.SUSPENDED},
        )
        self.assertEqual(response.status_code, 403)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ACTIVE)

    def test_suspended_organization_session_cannot_use_business_pages(self):
        self.organization.status = Organization.Status.SUSPENDED
        self.organization.save(update_fields=("status",))
        self.client.force_login(self.organization_admin)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 403)

    def test_status_endpoint_rejects_invalid_status(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:organization-status", args=(self.organization.pk,)),
            {"status": "deleted"},
        )
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ACTIVE)
        self.assertFalse(AuditEvent.objects.filter(action="organization.status_changed").exists())

    def test_user_list_can_filter_by_role_organization_and_status(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("superadmin:user-list"),
            {
                "q": "engineer-e11",
                "role": get_user_model().Role.ENGINEER,
                "organization": self.organization.pk,
                "status": "active",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "engineer-e11@example.com")
        self.assertNotContains(response, "other-engineer-e11")

    def test_user_detail_never_displays_password_hash(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:user-detail", args=(self.engineer.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "engineer-e11@example.com")
        self.assertNotContains(response, self.engineer.password)
        self.assertEqual(response.context["user_stats"]["managed_projects"], 1)

    def test_superuser_can_suspend_and_activate_user_with_audit(self):
        self.client.force_login(self.superuser)
        url = reverse("superadmin:user-status", args=(self.engineer.pk,))
        response = self.client.post(url, {"status": "inactive"})
        self.assertRedirects(response, reverse("superadmin:user-detail", args=(self.engineer.pk,)))
        self.engineer.refresh_from_db()
        self.assertFalse(self.engineer.is_active)
        event = AuditEvent.objects.get(action="user.status_changed")
        self.assertEqual(event.metadata["new_status"], "inactive")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"status": "active"})
        self.engineer.refresh_from_db()
        self.assertTrue(self.engineer.is_active)
        self.assertTrue(any(message.to == [self.engineer.email] for message in mail.outbox))

    def test_superuser_cannot_suspend_own_account(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:user-status", args=(self.superuser.pk,)),
            {"status": "inactive"},
        )
        self.assertRedirects(response, reverse("superadmin:user-detail", args=(self.superuser.pk,)))
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)
        self.assertFalse(AuditEvent.objects.filter(action="user.status_changed").exists())

    def test_password_reset_sends_secure_link_and_creates_audit(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:user-password-reset", args=(self.engineer.pk,))
        )
        self.assertRedirects(response, reverse("superadmin:user-detail", args=(self.engineer.pk,)))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/comptes/mot-de-passe/confirmer/", mail.outbox[0].body)
        event = AuditEvent.objects.get(action="user.password_reset_requested")
        self.assertEqual(event.target_id, str(self.engineer.pk))
        self.assertEqual(event.metadata, {})

    def test_password_reset_is_refused_without_email(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:user-password-reset", args=(self.organization_admin.pk,))
        )
        self.assertRedirects(
            response, reverse("superadmin:user-detail", args=(self.organization_admin.pk,))
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(AuditEvent.objects.filter(action="user.password_reset_requested").exists())

    def test_project_list_can_filter_across_organizations(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("superadmin:project-list"),
            {
                "q": "Tour",
                "organization": self.organization.pk,
                "status": Project.Status.ONGOING,
                "engineer": self.engineer.pk,
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tour Horizon")
        self.assertNotContains(response, "Résidence Littoral")
        self.assertEqual(response.context["project_page"].paginator.count, 1)

    def test_control_room_filters_route_state_city_and_blockage(self):
        ProjectOnboarding.objects.create(
            organization=self.organization,
            project=self.project,
            route=ProjectOnboarding.Route.CLIENT_LED,
            status=ProjectOnboarding.Status.DRAFT,
            financial_conditions="Paiement par jalons.",
            initiated_by=self.engineer,
        )
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse("superadmin:project-list"),
            {
                "route": ProjectOnboarding.Route.CLIENT_LED,
                "onboarding_status": ProjectOnboarding.Status.DRAFT,
                "city": "Douala",
                "blockage": "blocked",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tour Horizon")
        self.assertContains(response, "Propriétaire non confirmé")
        self.assertEqual(response.context["project_page"].paginator.count, 1)
        self.assertEqual(response.context["selected_route"], "client_led")
        self.assertEqual(response.context["selected_onboarding_status"], "draft")
        self.assertEqual(response.context["selected_city"], "Douala")

    def test_adoption_metrics_are_periodized_and_conversion_is_confirmed(self):
        client_user = get_user_model().objects.create_user(
            username="owner-e22", organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        ProjectMembership.objects.create(
            organization=self.organization, project=self.project, user=client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        ProjectOwnership.objects.create(
            organization=self.organization, project=self.project, owner=client_user,
            is_confirmed=True, confirmed_at=timezone.now(), confirmed_by=client_user,
            terms_version="v1", terms_accepted=True,
        )
        onboarding = ProjectOnboarding.objects.create(
            organization=self.organization, project=self.project,
            route=ProjectOnboarding.Route.CONTRACTOR_LED,
            status=ProjectOnboarding.Status.ACTIVE,
            financial_conditions="Conditions acceptées", initiated_by=self.engineer,
            activated_by=client_user, activated_at=timezone.now(),
        )
        invitation = Invitation.objects.create(
            organization=self.organization, invited_by=self.engineer,
            email="owner-e22@example.com", role=get_user_model().Role.CLIENT,
            project=self.project, project_role=ProjectMembership.Role.OWNER,
            token_hash="e22-token", accepted_at=timezone.now(),
        )
        yesterday = timezone.localdate() - timedelta(days=1)
        tomorrow = timezone.localdate() + timedelta(days=1)

        metrics = adoption_metrics(date_from=yesterday, date_to=tomorrow)

        self.assertEqual(metrics["active_projects"], 1)
        self.assertEqual(metrics["routes"]["contractor_led"], 1)
        self.assertEqual(metrics["invitations_created"], 1)
        self.assertEqual(metrics["invitations_accepted"], 1)
        self.assertEqual(metrics["contractor_converted"], 1)
        self.assertEqual(metrics["contractor_conversion_rate"], 100.0)
        self.assertTrue(onboarding.pk)
        self.assertTrue(invitation.pk)

        future_metrics = adoption_metrics(
            date_from=timezone.localdate() + timedelta(days=2),
            date_to=timezone.localdate() + timedelta(days=3),
        )
        self.assertEqual(future_metrics["active_projects"], 0)
        self.assertEqual(future_metrics["invitations_created"], 0)

    def test_concierge_follow_up_is_displayed_and_audited(self):
        ProjectOnboarding.objects.create(
            organization=self.organization, project=self.project,
            route=ProjectOnboarding.Route.PIVOT_LED,
            financial_conditions="Accompagnement concierge", initiated_by=self.superuser,
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("superadmin:project-concierge-update", args=(self.project.pk,)),
            {
                "confirmed": "yes", "pivot_agent": self.superuser.pk,
                "training_completed": "on", "friction": "Client peu disponible",
                "next_action": "Organiser la validation du propriétaire",
                "next_action_due_at": "2026-09-15T10:00",
            },
        )

        self.assertRedirects(response, reverse("superadmin:project-detail", args=(self.project.pk,)))
        follow_up = ProjectConciergeFollowUp.objects.get(onboarding__project=self.project)
        self.assertEqual(follow_up.pivot_agent, self.superuser)
        self.assertTrue(follow_up.training_completed)
        self.assertEqual(follow_up.updated_by, self.superuser)
        self.assertTrue(AuditEvent.objects.filter(
            action="project.pivot_concierge_updated", target_id=str(self.project.pk)
        ).exists())
        detail = self.client.get(reverse("superadmin:project-detail", args=(self.project.pk,)))
        self.assertContains(detail, "Onboarding concierge")
        self.assertContains(detail, "Client peu disponible")
        self.assertContains(detail, "Formation · fait")

    def test_project_supervision_detail_calculates_progress_and_counts(self):
        ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Fondations",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 15),
            status=ProjectStage.Status.COMPLETE,
            created_by=self.engineer,
        )
        ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Élévation",
            start_date=date(2026, 8, 16),
            end_date=date(2026, 9, 15),
            status=ProjectStage.Status.ACTIVE,
            created_by=self.engineer,
        )
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:project-detail", args=(self.project.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["project_progress"], 75)
        self.assertEqual(response.context["project_counts"]["stages"], 2)
        self.assertEqual(response.context["project_counts"]["documents"], 1)
        self.assertEqual(response.context["project_counts"]["pending_documents"], 1)
        self.assertEqual(response.context["payment_totals"]["XAF"], 500_000)
        self.assertContains(response, "Super-administration · lecture de contrôle")
        self.assertContains(response, "Fondations")

    def test_project_supervision_does_not_expose_business_mutation_links(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:project-detail", args=(self.project.pk,)))
        self.assertNotContains(response, reverse("projects:update", args=(self.project.pk,)))
        self.assertNotContains(response, reverse("projects:status-update", args=(self.project.pk,)))
        self.assertNotContains(response, reverse("projects:members", args=(self.project.pk,)))
        self.assertNotContains(response, self.project.documents.first().file.url)

    def test_organization_admin_cannot_open_global_project_supervision(self):
        self.client.force_login(self.organization_admin)
        self.assertEqual(self.client.get(reverse("superadmin:project-list")).status_code, 403)
        self.assertEqual(
            self.client.get(
                reverse("superadmin:project-detail", args=(self.project.pk,))
            ).status_code,
            403,
        )

    def test_validation_queue_combines_documents_and_withdrawals(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:validation-queue"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["validation_page"].paginator.count, 2)
        self.assertEqual(response.context["pending_document_count"], 1)
        self.assertEqual(response.context["pending_withdrawal_count"], 1)
        self.assertContains(response, "Plan à valider")
        self.assertContains(response, "100000")

    def test_validation_queue_filters_withdrawals_by_amount_and_organization(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("superadmin:validation-queue"),
            {
                "type": "withdrawal",
                "organization": self.organization.pk,
                "status": "pending",
                "min_amount": "90000",
                "max_amount": "110000",
            },
        )
        self.assertEqual(response.context["validation_page"].paginator.count, 1)
        item = response.context["validation_page"].object_list[0]
        self.assertEqual(item["kind"], "withdrawal")
        self.assertEqual(item["object"].amount, 100_000)

    def test_superuser_approves_document_with_reason_notification_and_audit(self):
        document = self.project.documents.get()
        self.client.force_login(self.superuser)
        url = reverse("superadmin:validation-document-decide", args=(document.pk,))
        self.client.get(reverse("superadmin:validation-document-preview", args=(document.pk,)))
        response = self.client.post(
            url, {"decision": ProjectDocument.Status.APPROVED, "reason": "Plan conforme."}
        )
        self.assertRedirects(response, reverse("superadmin:validation-queue"))
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.APPROVED)
        self.assertEqual(document.review_reason, "Plan conforme.")
        self.assertEqual(document.reviewed_by, self.superuser)
        event = AuditEvent.objects.get(action="document.approved")
        self.assertEqual(event.metadata["reason"], "Plan conforme.")
        self.assertTrue(self.engineer.notifications.filter(kind="document").exists())

        self.client.post(
            url, {"decision": ProjectDocument.Status.REJECTED, "reason": "Deuxième décision."}
        )
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.APPROVED)
        self.assertEqual(AuditEvent.objects.filter(action="document.approved").count(), 1)

    def test_validation_approval_is_blocked_until_document_preview(self):
        document = self.project.documents.get()
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:validation-queue"))
        self.assertContains(response, "data-validation-preview-modal")
        self.assertContains(response, "Aperçu obligatoire")
        self.client.post(
            reverse("superadmin:validation-document-decide", args=(document.pk,)),
            {"decision": ProjectDocument.Status.APPROVED, "reason": "Sans aperçu."},
        )
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.VERIFIED)
        preview = self.client.get(
            reverse("superadmin:validation-document-preview", args=(document.pk,))
        )
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview["Content-Disposition"].startswith("inline;"))

    def test_document_decision_requires_reason(self):
        document = self.project.documents.get()
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:validation-document-decide", args=(document.pk,)),
            {"decision": ProjectDocument.Status.APPROVED, "reason": "   "},
        )
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.VERIFIED)
        self.assertFalse(AuditEvent.objects.filter(action="document.approved").exists())

    def test_superuser_accounts_withdrawal_with_reason_notification_and_audit(self):
        withdrawal = self.project.withdrawals.get()
        self.client.force_login(self.superuser)
        url = reverse("superadmin:validation-withdrawal-decide", args=(withdrawal.pk,))
        self.client.post(
            url, {"decision": Withdrawal.Status.ACCOUNTED, "reason": "Justificatif vérifié."}
        )
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, Withdrawal.Status.ACCOUNTED)
        self.assertEqual(withdrawal.decided_by, self.superuser)
        event = AuditEvent.objects.get(action="withdrawal.decided")
        self.assertEqual(event.metadata["reason"], "Justificatif vérifié.")
        self.assertTrue(self.engineer.notifications.filter(kind="finance").exists())

        self.client.post(
            url, {"decision": Withdrawal.Status.REJECTED, "reason": "Deuxième décision."}
        )
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, Withdrawal.Status.ACCOUNTED)
        self.assertEqual(AuditEvent.objects.filter(action="withdrawal.decided").count(), 1)

    def test_organization_admin_cannot_process_central_validation(self):
        document = self.project.documents.get()
        withdrawal = self.project.withdrawals.get()
        self.client.force_login(self.organization_admin)
        self.assertEqual(self.client.get(reverse("superadmin:validation-queue")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("superadmin:validation-document-decide", args=(document.pk,)),
                {"decision": "approved", "reason": "Interdit"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("superadmin:validation-withdrawal-decide", args=(withdrawal.pk,)),
                {"decision": "accounted", "reason": "Interdit"},
            ).status_code,
            403,
        )

    def test_audit_list_searches_and_filters_global_events(self):
        matching = AuditEvent.objects.create(
            organization=self.organization,
            actor=self.engineer,
            action="project.status_changed",
            target_type="project",
            target_id=str(self.project.pk),
            metadata={"new_status": "ongoing"},
        )
        AuditEvent.objects.create(
            organization=self.other_organization,
            actor=self.other_engineer,
            action="stock.approved",
            target_type="stock_item",
            target_id="foreign-item",
            metadata={},
        )
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("superadmin:audit-list"),
            {
                "q": str(self.project.pk),
                "actor": self.engineer.pk,
                "action": "project.status_changed",
                "organization": self.organization.pk,
                "target_type": "project",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["audit_page"].paginator.count, 1)
        self.assertEqual(response.context["audit_page"].object_list[0], matching)

    def test_audit_detail_masks_sensitive_metadata(self):
        event = AuditEvent.objects.create(
            organization=self.organization,
            actor=self.superuser,
            action="security.test",
            target_type="user",
            target_id=str(self.engineer.pk),
            metadata={
                "status": "ok",
                "password": "never-display-this-password",
                "nested": {"api_token": "never-display-this-token"},
                "file_name": "private-plan.pdf",
            },
        )
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("superadmin:audit-detail", args=(event.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["safe_metadata"]["status"], "ok")
        self.assertEqual(response.context["safe_metadata"]["password"], "[MASQUÉ]")
        self.assertEqual(response.context["safe_metadata"]["nested"]["api_token"], "[MASQUÉ]")
        self.assertEqual(response.context["safe_metadata"]["file_name"], "[MASQUÉ]")
        self.assertNotContains(response, "never-display-this-password")
        self.assertNotContains(response, "never-display-this-token")
        self.assertNotContains(response, "private-plan.pdf")

    def test_audit_detail_is_read_only(self):
        event = AuditEvent.objects.create(
            actor=self.superuser,
            action="account.login",
            target_type="user",
            target_id=str(self.superuser.pk),
        )
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("superadmin:audit-detail", args=(event.pk,)))
        self.assertEqual(response.status_code, 405)
        event.refresh_from_db()
        self.assertEqual(event.action, "account.login")

    def test_login_and_logout_are_recorded_without_sensitive_metadata(self):
        self.assertTrue(self.client.login(username=self.superuser.username, password=self.password))
        login_event = AuditEvent.objects.get(action="account.login", actor=self.superuser)
        self.assertEqual(login_event.metadata, {})
        self.assertIsNone(login_event.organization)
        self.client.logout()
        logout_event = AuditEvent.objects.get(action="account.logout", actor=self.superuser)
        self.assertEqual(logout_event.metadata, {})

    def test_organization_admin_cannot_access_global_audit(self):
        event = AuditEvent.objects.create(
            organization=self.organization,
            actor=self.engineer,
            action="test.event",
            target_type="project",
            target_id=str(self.project.pk),
        )
        self.client.force_login(self.organization_admin)
        self.assertEqual(self.client.get(reverse("superadmin:audit-list")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("superadmin:audit-detail", args=(event.pk,))).status_code,
            403,
        )

    def test_platform_settings_show_service_health_without_secrets(self):
        self.client.force_login(self.superuser)
        with patch.dict(
            os.environ,
            {
                "PAYMENT_GATEWAY": "mesomb",
                "MESOMB_APPLICATION_KEY": "application-secret-e11",
                "MESOMB_ACCESS_KEY": "access-secret-e11",
                "MESOMB_SECRET_KEY": "private-secret-e11",
            },
        ):
            response = self.client.get(reverse("superadmin:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Base de données")
        self.assertContains(response, "MeSomb")
        self.assertContains(response, "••••••••")
        self.assertNotContains(response, "application-secret-e11")
        self.assertNotContains(response, "access-secret-e11")
        self.assertNotContains(response, "private-secret-e11")

    def test_platform_settings_require_explicit_confirmation(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:settings"),
            {
                "platform_name": "PIVOT Cloud",
                "support_email": "support@example.com",
                "engineer_registration_enabled": "on",
                "client_registration_enabled": "on",
                "notification_retention_days": 120,
                "confirmed": "no",
            },
        )
        self.assertEqual(response.status_code, 200)
        configuration = PlatformConfiguration.load()
        self.assertEqual(configuration.platform_name, "PIVOT")
        self.assertFalse(AuditEvent.objects.filter(action="platform.settings_updated").exists())

    def test_superuser_updates_settings_and_creates_minimal_audit(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:settings"),
            {
                "platform_name": "PIVOT Cloud",
                "support_email": "support@example.com",
                "platform_notice": "Maintenance planifiée samedi.",
                "notification_retention_days": 120,
                "confirmed": "yes",
            },
        )
        self.assertRedirects(response, reverse("superadmin:settings"))
        configuration = PlatformConfiguration.load()
        self.assertEqual(configuration.pk, 1)
        self.assertEqual(configuration.platform_name, "PIVOT Cloud")
        self.assertEqual(configuration.support_email, "support@example.com")
        self.assertFalse(configuration.engineer_registration_enabled)
        self.assertFalse(configuration.client_registration_enabled)
        self.assertEqual(configuration.updated_by, self.superuser)
        event = AuditEvent.objects.get(action="platform.settings_updated")
        self.assertIn("platform_name", event.metadata["changed_fields"])
        self.assertNotIn("support@example.com", str(event.metadata))

    def test_invalid_platform_settings_are_not_saved(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:settings"),
            {
                "platform_name": "PIVOT",
                "notification_retention_days": 2,
                "confirmed": "yes",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "notification_retention_days",
            "Assurez-vous que cette valeur est supérieure ou égale à 7.",
        )
        self.assertFalse(AuditEvent.objects.filter(action="platform.settings_updated").exists())

    def test_registration_switches_take_effect_immediately(self):
        configuration = PlatformConfiguration.load()
        configuration.engineer_registration_enabled = False
        configuration.client_registration_enabled = False
        configuration.save()
        engineer_response = self.client.get(reverse("accounts:engineer-registration"))
        client_response = self.client.get(reverse("accounts:client-registration"))
        self.assertRedirects(engineer_response, reverse("accounts:login"))
        self.assertRedirects(client_response, reverse("accounts:login"))

    def test_organization_admin_cannot_open_or_update_platform_settings(self):
        self.client.force_login(self.organization_admin)
        self.assertEqual(self.client.get(reverse("superadmin:settings")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("superadmin:settings"),
                {
                    "platform_name": "Hacked",
                    "notification_retention_days": 90,
                    "confirmed": "yes",
                },
            ).status_code,
            403,
        )
        self.assertEqual(PlatformConfiguration.load().platform_name, "PIVOT")

    def test_superuser_creates_organization_and_first_admin_from_confirmed_modal(self):
        self.client.force_login(self.superuser)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("superadmin:organization-create"),
                {
                    "name": "Nouvelle Construction",
                    "slug": "nouvelle-construction",
                    "first_username": "nouvel-admin",
                    "first_email": "nouvel-admin@example.com",
                    "first_name": "Marie",
                    "last_name": "Pilot",
                    "first_role": get_user_model().Role.ADMIN,
                    "confirmed": "yes",
                },
            )
        organization = Organization.objects.get(slug="nouvelle-construction")
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(organization.pk,))
        )
        account = get_user_model().objects.get(username="nouvel-admin")
        self.assertEqual(account.organization, organization)
        self.assertEqual(account.role, get_user_model().Role.ADMIN)
        self.assertTrue(account.is_staff)
        self.assertTrue(account.is_active)
        self.assertFalse(account.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/comptes/mot-de-passe/confirmer/", mail.outbox[0].body)
        event = AuditEvent.objects.get(action="organization.created")
        self.assertEqual(event.target_id, str(organization.pk))
        self.assertEqual(event.metadata, {"first_user_role": "admin"})
        self.assertNotIn("nouvel-admin", str(event.metadata))
        self.assertNotIn("nouvel-admin@example.com", str(event.metadata))

    def test_organization_creation_requires_confirmation(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:organization-create"),
            {
                "name": "Non confirmée",
                "slug": "non-confirmee",
                "first_username": "non-confirme",
                "first_email": "non-confirme@example.com",
                "first_role": "engineer",
                "confirmed": "no",
            },
        )
        self.assertRedirects(response, reverse("superadmin:organization-list"))
        self.assertFalse(Organization.objects.filter(slug="non-confirmee").exists())
        self.assertFalse(get_user_model().objects.filter(username="non-confirme").exists())

    def test_organization_creation_rejects_duplicate_identifiers_atomically(self):
        self.client.force_login(self.superuser)
        initial_organizations = Organization.objects.count()
        initial_users = get_user_model().objects.count()
        self.client.post(
            reverse("superadmin:organization-create"),
            {
                "name": "Genius",
                "slug": "genius",
                "first_username": "engineer-e11",
                "first_email": "engineer-e11@example.com",
                "first_role": "engineer",
                "confirmed": "yes",
            },
        )
        self.assertEqual(Organization.objects.count(), initial_organizations)
        self.assertEqual(get_user_model().objects.count(), initial_users)
        self.assertFalse(AuditEvent.objects.filter(action="organization.created").exists())

    def test_superuser_updates_organization_after_confirmation(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:organization-update", args=(self.organization.pk,)),
            {"name": "Genius Engineering", "slug": "genius-engineering", "confirmed": "yes"},
        )
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Genius Engineering")
        self.assertEqual(self.organization.slug, "genius-engineering")
        event = AuditEvent.objects.get(action="organization.updated")
        self.assertEqual(set(event.metadata["changed_fields"]), {"name", "slug"})
        self.assertNotIn("Genius Engineering", str(event.metadata))

    def test_organization_update_rejects_duplicate_slug(self):
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:organization-update", args=(self.organization.pk,)),
            {"name": "Genius", "slug": self.other_organization.slug, "confirmed": "yes"},
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.slug, "genius")
        self.assertFalse(AuditEvent.objects.filter(action="organization.updated").exists())

    def test_organization_admin_cannot_create_or_modify_organizations(self):
        self.client.force_login(self.organization_admin)
        self.assertEqual(
            self.client.post(
                reverse("superadmin:organization-create"),
                {
                    "name": "Interdite",
                    "slug": "interdite",
                    "first_username": "interdit",
                    "first_email": "interdit@example.com",
                    "first_role": "admin",
                    "confirmed": "yes",
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("superadmin:organization-update", args=(self.organization.pk,)),
                {"name": "Interdite", "slug": "interdite", "confirmed": "yes"},
            ).status_code,
            403,
        )
        self.assertFalse(Organization.objects.filter(slug="interdite").exists())

    def test_superuser_archives_organization_with_audit_and_blocks_access(self):
        self.client.force_login(self.superuser)
        url = reverse("superadmin:organization-lifecycle", args=(self.organization.pk,))
        response = self.client.post(url, {"action": "archive", "confirmed": "yes"})
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ARCHIVED)
        event = AuditEvent.objects.get(action="organization.archived")
        self.assertEqual(event.metadata["previous_status"], Organization.Status.ACTIVE)
        self.client.force_login(self.organization_admin)
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 403)

    def test_superuser_restores_archived_organization(self):
        self.organization.status = Organization.Status.ARCHIVED
        self.organization.save(update_fields=("status",))
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:organization-lifecycle", args=(self.organization.pk,)),
            {"action": "restore", "confirmed": "yes"},
        )
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ACTIVE)
        self.assertTrue(AuditEvent.objects.filter(action="organization.restored").exists())

    def test_organization_with_history_cannot_be_deleted(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:organization-lifecycle", args=(self.organization.pk,)),
            {
                "action": "delete",
                "confirmed": "yes",
                "confirmation_name": self.organization.name,
            },
        )
        self.assertRedirects(
            response, reverse("superadmin:organization-detail", args=(self.organization.pk,))
        )
        self.assertTrue(Organization.objects.filter(pk=self.organization.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(action="organization.deleted").exists())

    def test_empty_organization_deletion_requires_exact_name_and_is_audited(self):
        empty = Organization.objects.create(name="Organisation Vide", slug="organisation-vide")
        empty_id = empty.pk
        self.client.force_login(self.superuser)
        url = reverse("superadmin:organization-lifecycle", args=(empty.pk,))
        wrong = self.client.post(
            url,
            {"action": "delete", "confirmed": "yes", "confirmation_name": "Mauvais nom"},
        )
        self.assertRedirects(wrong, reverse("superadmin:organization-detail", args=(empty.pk,)))
        self.assertTrue(Organization.objects.filter(pk=empty.pk).exists())

        response = self.client.post(
            url,
            {"action": "delete", "confirmed": "yes", "confirmation_name": empty.name},
        )
        self.assertRedirects(response, reverse("superadmin:organization-list"))
        self.assertFalse(Organization.objects.filter(pk=empty_id).exists())
        event = AuditEvent.objects.get(action="organization.deleted")
        self.assertIsNone(event.organization)
        self.assertEqual(event.target_id, str(empty_id))
        self.assertEqual(event.metadata, {})

    def test_lifecycle_action_requires_confirmation(self):
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:organization-lifecycle", args=(self.organization.pk,)),
            {"action": "archive", "confirmed": "no"},
        )
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ACTIVE)
        self.assertFalse(AuditEvent.objects.filter(action="organization.archived").exists())

    def test_organization_admin_cannot_manage_organization_lifecycle(self):
        self.client.force_login(self.organization_admin)
        response = self.client.post(
            reverse("superadmin:organization-lifecycle", args=(self.organization.pk,)),
            {"action": "archive", "confirmed": "yes"},
        )
        self.assertEqual(response.status_code, 403)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.status, Organization.Status.ACTIVE)

    def test_superuser_creates_user_and_sends_secure_activation_link(self):
        self.client.force_login(self.superuser)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("superadmin:user-create"),
                {
                    "organization": self.organization.pk,
                    "username": "client-e12",
                    "email": "client-e12@example.com",
                    "first_name": "Alice",
                    "last_name": "Client",
                    "role": get_user_model().Role.CLIENT,
                    "confirmed": "yes",
                },
            )
        account = get_user_model().objects.get(username="client-e12")
        self.assertRedirects(response, reverse("superadmin:user-detail", args=(account.pk,)))
        self.assertEqual(account.organization, self.organization)
        self.assertEqual(account.role, get_user_model().Role.CLIENT)
        self.assertTrue(account.is_active)
        self.assertFalse(account.is_staff)
        self.assertFalse(account.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/comptes/mot-de-passe/confirmer/", mail.outbox[0].body)
        event = AuditEvent.objects.get(action="user.created")
        self.assertEqual(event.metadata, {"role": "client"})
        self.assertNotIn("client-e12@example.com", str(event.metadata))

    def test_user_creation_requires_confirmation_and_unique_identity(self):
        self.client.force_login(self.superuser)
        payload = {
            "organization": self.organization.pk,
            "username": "blocked-e12",
            "email": "blocked-e12@example.com",
            "role": "client",
            "confirmed": "no",
        }
        self.client.post(reverse("superadmin:user-create"), payload)
        self.assertFalse(get_user_model().objects.filter(username="blocked-e12").exists())
        payload.update(
            {
                "confirmed": "yes",
                "username": self.engineer.username,
                "email": self.engineer.email,
            }
        )
        initial_count = get_user_model().objects.count()
        self.client.post(reverse("superadmin:user-create"), payload)
        self.assertEqual(get_user_model().objects.count(), initial_count)
        self.assertFalse(AuditEvent.objects.filter(action="user.created").exists())

    def test_superuser_modifies_user_identity_and_role_with_audit(self):
        account = get_user_model().objects.create_user(
            username="editable-e12",
            email="editable-old@example.com",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:user-update", args=(account.pk,)),
            {
                "username": "edited-e12",
                "email": "editable-new@example.com",
                "first_name": "Nouveau",
                "last_name": "Nom",
                "role": get_user_model().Role.SITE_MANAGER,
                "confirmed": "yes",
            },
        )
        self.assertRedirects(response, reverse("superadmin:user-detail", args=(account.pk,)))
        account.refresh_from_db()
        self.assertEqual(account.username, "edited-e12")
        self.assertEqual(account.email, "editable-new@example.com")
        self.assertEqual(account.role, get_user_model().Role.SITE_MANAGER)
        event = AuditEvent.objects.get(action="user.updated")
        self.assertEqual(
            set(event.metadata["changed_fields"]),
            {"username", "email", "first_name", "last_name", "role"},
        )
        self.assertNotIn("editable-new@example.com", str(event.metadata))

    def test_user_role_change_cannot_break_managed_projects(self):
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:user-update", args=(self.engineer.pk,)),
            {
                "username": self.engineer.username,
                "email": self.engineer.email,
                "first_name": self.engineer.first_name,
                "last_name": self.engineer.last_name,
                "role": get_user_model().Role.CLIENT,
                "confirmed": "yes",
            },
        )
        self.engineer.refresh_from_db()
        self.assertEqual(self.engineer.role, get_user_model().Role.ENGINEER)
        self.assertFalse(AuditEvent.objects.filter(action="user.updated").exists())

    def test_user_update_rejects_duplicate_username_and_email(self):
        account = get_user_model().objects.create_user(
            username="unique-e12",
            email="unique-e12@example.com",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:user-update", args=(account.pk,)),
            {
                "username": self.engineer.username,
                "email": self.engineer.email,
                "role": account.role,
                "confirmed": "yes",
            },
        )
        account.refresh_from_db()
        self.assertEqual(account.username, "unique-e12")
        self.assertEqual(account.email, "unique-e12@example.com")

    def test_organization_admin_cannot_create_or_modify_users_globally(self):
        self.client.force_login(self.organization_admin)
        self.assertEqual(
            self.client.post(
                reverse("superadmin:user-create"),
                {
                    "organization": self.organization.pk,
                    "username": "forbidden-e12",
                    "email": "forbidden-e12@example.com",
                    "role": "client",
                    "confirmed": "yes",
                },
            ).status_code,
            403,
        )

    def test_engineer_transfer_reassigns_projects_atomically(self):
        target = Organization.objects.create(name="Target E12", slug="target-e12")
        replacement = get_user_model().objects.create_user(
            username="replacement-engineer-e12",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:user-transfer", args=(self.engineer.pk,)),
            {
                "target_organization": target.pk,
                "project_replacement": replacement.pk,
                "reason": "Réorganisation des équipes.",
                "confirmed": "yes",
            },
        )
        self.assertRedirects(response, reverse("superadmin:user-detail", args=(self.engineer.pk,)))
        self.engineer.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(self.engineer.organization, target)
        self.assertEqual(self.project.engineer, replacement)
        event = AuditEvent.objects.get(action="user.transferred")
        self.assertEqual(event.metadata["source_organization_id"], self.organization.pk)
        self.assertEqual(event.metadata["target_organization_id"], target.pk)
        self.assertEqual(event.metadata["reassigned_projects"], 1)
        notification = self.engineer.notifications.get(kind="account")
        self.assertEqual(notification.organization, target)

    def test_engineer_transfer_without_replacement_changes_nothing(self):
        target = Organization.objects.create(name="Target Refused", slug="target-refused")
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:user-transfer", args=(self.engineer.pk,)),
            {
                "target_organization": target.pk,
                "reason": "Remplaçant absent.",
                "confirmed": "yes",
            },
        )
        self.engineer.refresh_from_db()
        self.project.refresh_from_db()
        self.assertEqual(self.engineer.organization, self.organization)
        self.assertEqual(self.project.engineer, self.engineer)
        self.assertFalse(AuditEvent.objects.filter(action="user.transferred").exists())

    def test_client_transfer_reassigns_project_memberships(self):
        target = Organization.objects.create(name="Client Target", slug="client-target")
        client_user = get_user_model().objects.create_user(
            username="moving-client-e12",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        replacement = get_user_model().objects.create_user(
            username="replacement-client-e12",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        membership = ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:user-transfer", args=(client_user.pk,)),
            {
                "target_organization": target.pk,
                "membership_replacement": replacement.pk,
                "reason": "Changement de portefeuille client.",
                "confirmed": "yes",
            },
        )
        client_user.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(client_user.organization, target)
        self.assertEqual(membership.user, replacement)
        event = AuditEvent.objects.get(action="user.transferred")
        self.assertEqual(event.metadata["reassigned_memberships"], 1)

    def test_transfer_requires_confirmation_and_active_different_target(self):
        account = get_user_model().objects.create_user(
            username="simple-transfer-e12",
            organization=self.organization,
            role=get_user_model().Role.ADMIN,
        )
        target = Organization.objects.create(name="Simple Target", slug="simple-target")
        self.client.force_login(self.superuser)
        url = reverse("superadmin:user-transfer", args=(account.pk,))
        self.client.post(
            url,
            {
                "target_organization": target.pk,
                "reason": "Sans confirmation.",
                "confirmed": "no",
            },
        )
        account.refresh_from_db()
        self.assertEqual(account.organization, self.organization)
        self.client.post(
            url,
            {
                "target_organization": self.other_organization.pk,
                "reason": "Cible suspendue.",
                "confirmed": "yes",
            },
        )
        account.refresh_from_db()
        self.assertEqual(account.organization, self.organization)

    def test_superuser_and_organization_admin_cannot_use_transfer_incorrectly(self):
        target = Organization.objects.create(name="Security Target", slug="security-target")
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:user-transfer", args=(self.superuser.pk,)),
            {
                "target_organization": target.pk,
                "reason": "Interdit.",
                "confirmed": "yes",
            },
        )
        self.superuser.refresh_from_db()
        self.assertIsNone(self.superuser.organization)
        self.client.force_login(self.organization_admin)
        response = self.client.post(
            reverse("superadmin:user-transfer", args=(self.engineer.pk,)),
            {
                "target_organization": target.pk,
                "reason": "Interdit.",
                "confirmed": "yes",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("superadmin:user-update", args=(self.engineer.pk,)),
                {
                    "username": "forbidden-name",
                    "email": self.engineer.email,
                    "role": self.engineer.role,
                    "confirmed": "yes",
                },
            ).status_code,
            403,
        )

    def test_superuser_intervenes_on_project_and_audits_safe_changes(self):
        replacement = get_user_model().objects.create_user(
            username="replacement-project-e12",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        member = get_user_model().objects.create_user(
            username="client-project-e12",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:project-intervene", args=(self.project.pk,)),
            {
                "name": "Tour Horizon corrigée",
                "description": "Correction administrative",
                "location": "Yaoundé",
                "project_date": "2026-08-25",
                "budget_amount": "21000000",
                "status": Project.Status.COMPLETE,
                "engineer": replacement.pk,
                "members": [member.pk],
                "reason": "Correction validée après contrôle du dossier.",
                "confirmed": "yes",
            },
        )
        self.assertRedirects(
            response, reverse("superadmin:project-detail", args=(self.project.pk,))
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Tour Horizon corrigée")
        self.assertEqual(self.project.engineer, replacement)
        self.assertEqual(self.project.status, Project.Status.COMPLETE)
        self.assertTrue(self.project.memberships.filter(user=member).exists())
        history = self.project.status_history.get()
        self.assertEqual(history.actor, self.superuser)
        event = AuditEvent.objects.get(action="project.intervened")
        self.assertEqual(event.metadata["reason"], "Correction validée après contrôle du dossier.")
        self.assertEqual(event.metadata["previous"]["engineer_id"], self.engineer.pk)
        self.assertEqual(event.metadata["new"]["engineer_id"], replacement.pk)
        self.assertNotIn("email", str(event.metadata).lower())

    def test_project_intervention_requires_reason_and_confirmation(self):
        self.client.force_login(self.superuser)
        url = reverse("superadmin:project-intervene", args=(self.project.pk,))
        payload = {
            "name": "Nom refusé",
            "description": "",
            "location": "Douala",
            "project_date": "2026-08-25",
            "budget_amount": "20000000",
            "status": self.project.status,
            "engineer": self.engineer.pk,
            "reason": "",
            "confirmed": "yes",
        }
        self.client.post(url, payload)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Tour Horizon")
        payload.update(reason="Motif présent", confirmed="no")
        self.client.post(url, payload)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Tour Horizon")
        self.assertFalse(AuditEvent.objects.filter(action="project.intervened").exists())

    def test_project_intervention_rejects_foreign_engineer_atomically(self):
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:project-intervene", args=(self.project.pk,)),
            {
                "name": "Nom étranger",
                "description": "",
                "location": "Douala",
                "project_date": "2026-08-25",
                "budget_amount": "20000000",
                "status": Project.Status.COMPLETE,
                "engineer": self.other_engineer.pk,
                "reason": "Test de cohérence organisationnelle.",
                "confirmed": "yes",
            },
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Tour Horizon")
        self.assertEqual(self.project.engineer, self.engineer)
        self.assertEqual(self.project.status, Project.Status.ONGOING)

    def test_project_intervention_rejects_date_after_first_stage(self):
        ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Fondations",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 20),
            created_by=self.engineer,
        )
        self.client.force_login(self.superuser)
        self.client.post(
            reverse("superadmin:project-intervene", args=(self.project.pk,)),
            {
                "name": self.project.name,
                "description": "",
                "location": "Douala",
                "project_date": "2026-09-05",
                "budget_amount": "20000000",
                "status": self.project.status,
                "engineer": self.engineer.pk,
                "reason": "Décalage demandé.",
                "confirmed": "yes",
            },
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.project_date, date(2026, 8, 25))

    def test_organization_admin_cannot_intervene_on_project(self):
        self.client.force_login(self.organization_admin)
        response = self.client.post(
            reverse("superadmin:project-intervene", args=(self.project.pk,)),
            {"confirmed": "yes"},
        )
        self.assertEqual(response.status_code, 403)

    def test_content_admin_deletes_only_pending_stage_with_audit(self):
        stage = ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Étape provisoire",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            created_by=self.engineer,
        )
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:project-content-action", args=(self.project.pk, "stage", stage.pk)),
            {"action": "delete", "reason": "Étape créée par erreur.", "confirmed": "yes"},
        )
        self.assertRedirects(
            response, reverse("superadmin:project-detail", args=(self.project.pk,))
        )
        self.assertFalse(ProjectStage.objects.filter(pk=stage.pk).exists())
        event = AuditEvent.objects.get(action="project_content.stage_deleted")
        self.assertEqual(event.metadata["reason"], "Étape créée par erreur.")

    def test_content_admin_preserves_stage_not_pending_and_stock_history(self):
        stage = ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Étape active",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            status=ProjectStage.Status.ACTIVE,
            created_by=self.engineer,
        )
        item = StockItem.objects.create(
            organization=self.organization,
            project=self.project,
            name="Ciment",
            unit="sac",
            unit_price=5000,
            quantity=20,
            created_by=self.engineer,
        )
        StockMovement.objects.create(
            organization=self.organization,
            project=self.project,
            item=item,
            variation=20,
            resulting_quantity=20,
            reason="Initial",
            actor=self.engineer,
            idempotency_key=uuid.uuid4(),
        )
        self.client.force_login(self.superuser)
        for kind, target in (("stage", stage), ("stock", item)):
            self.client.post(
                reverse(
                    "superadmin:project-content-action", args=(self.project.pk, kind, target.pk)
                ),
                {"action": "delete", "reason": "Tentative refusée.", "confirmed": "yes"},
            )
        self.assertTrue(ProjectStage.objects.filter(pk=stage.pk).exists())
        self.assertTrue(StockItem.objects.filter(pk=item.pk).exists())

    def test_content_admin_rejects_document_and_withdrawal_without_deleting(self):
        document = self.project.documents.get()
        withdrawal = self.project.withdrawals.get()
        self.client.force_login(self.superuser)
        for kind, target in (("document", document), ("withdrawal", withdrawal)):
            self.client.post(
                reverse(
                    "superadmin:project-content-action", args=(self.project.pk, kind, target.pk)
                ),
                {"action": "reject", "reason": "Pièce non conforme.", "confirmed": "yes"},
            )
        document.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.REJECTED)
        self.assertEqual(withdrawal.status, Withdrawal.Status.REJECTED)
        self.assertTrue(
            AuditEvent.objects.filter(action="project_content.document_intervened").exists()
        )
        event = AuditEvent.objects.get(action="project_content.withdrawal_intervened")
        self.assertEqual(event.metadata["reason"], "Pièce non conforme.")

    def test_content_admin_soft_deletes_comment_and_deletes_photo(self):
        comment = ProjectComment.objects.create(
            organization=self.organization,
            project=self.project,
            author=self.engineer,
            content="Contenu à modérer",
        )
        photo = ProjectImage.objects.create(
            organization=self.organization,
            project=self.project,
            uploaded_by=self.engineer,
            caption="Photo erronée",
            image=SimpleUploadedFile("photo.jpg", b"fake-image"),
        )
        self.client.force_login(self.superuser)
        self.client.post(
            reverse(
                "superadmin:project-content-action", args=(self.project.pk, "comment", comment.pk)
            ),
            {"action": "moderate", "reason": "Contenu inapproprié.", "confirmed": "yes"},
        )
        self.client.post(
            reverse("superadmin:project-content-action", args=(self.project.pk, "photo", photo.pk)),
            {"action": "delete", "reason": "Mauvaise photo.", "confirmed": "yes"},
        )
        comment.refresh_from_db()
        self.assertTrue(comment.is_deleted)
        self.assertEqual(comment.content, "")
        self.assertEqual(comment.deleted_by, self.superuser)
        self.assertFalse(ProjectImage.objects.filter(pk=photo.pk).exists())

    def test_content_action_requires_confirmation_reason_and_same_project(self):
        stage = ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Protégée",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            created_by=self.engineer,
        )
        other_project = Project.objects.exclude(pk=self.project.pk).first()
        self.client.force_login(self.superuser)
        url = reverse(
            "superadmin:project-content-action", args=(self.project.pk, "stage", stage.pk)
        )
        self.client.post(url, {"action": "delete", "reason": "", "confirmed": "yes"})
        self.client.post(url, {"action": "delete", "reason": "Motif", "confirmed": "no"})
        self.assertTrue(ProjectStage.objects.filter(pk=stage.pk).exists())
        mismatch = self.client.post(
            reverse(
                "superadmin:project-content-action", args=(other_project.pk, "stage", stage.pk)
            ),
            {"action": "delete", "reason": "Mauvais projet", "confirmed": "yes"},
        )
        self.assertEqual(mismatch.status_code, 404)

    def test_payment_is_immutable_and_org_admin_is_forbidden(self):
        payment = self.project.payment_transactions.get()
        url = reverse(
            "superadmin:project-content-action", args=(self.project.pk, "payment", payment.pk)
        )
        self.client.force_login(self.superuser)
        self.client.post(url, {"action": "delete", "reason": "Interdit", "confirmed": "yes"})
        self.assertTrue(PaymentTransaction.objects.filter(pk=payment.pk).exists())
        self.client.force_login(self.organization_admin)
        self.assertEqual(
            self.client.post(
                url, {"action": "delete", "reason": "Interdit", "confirmed": "yes"}
            ).status_code,
            403,
        )

    def test_superadmin_can_preview_and_approve_document(self):
        document = self.project.documents.get()
        self.client.force_login(self.superuser)
        preview = self.client.get(
            reverse(
                "superadmin:project-content-preview",
                args=(self.project.pk, "document", document.pk),
            )
        )
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview["Content-Disposition"].startswith("inline;"))
        self.assertEqual(preview["X-Content-Type-Options"], "nosniff")
        response = self.client.post(
            reverse(
                "superadmin:project-content-action",
                args=(self.project.pk, "document", document.pk),
            ),
            {
                "action": "approve",
                "reason": "Aperçu contrôlé et document conforme.",
                "confirmed": "yes",
            },
        )
        self.assertRedirects(
            response, reverse("superadmin:project-detail", args=(self.project.pk,))
        )
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.APPROVED)

    def test_superadmin_can_preview_pending_document_without_approving_it(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Document encore en attente ingénieur",
            file=SimpleUploadedFile("pending.pdf", b"%PDF-1.4 pending"),
            uploaded_by=self.engineer,
        )
        self.client.force_login(self.superuser)

        detail = self.client.get(reverse("superadmin:project-detail", args=(self.project.pk,)))
        preview = self.client.get(
            reverse(
                "superadmin:project-content-preview",
                args=(self.project.pk, "document", document.pk),
            )
        )

        self.assertContains(detail, document.title)
        self.assertEqual(preview.status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.PENDING)

    def test_photo_preview_is_secured_and_scoped_to_project(self):
        photo = ProjectImage.objects.create(
            organization=self.organization,
            project=self.project,
            uploaded_by=self.engineer,
            caption="Aperçu chantier",
            image=SimpleUploadedFile("preview.jpg", b"fake-image"),
        )
        url = reverse(
            "superadmin:project-content-preview",
            args=(self.project.pk, "photo", photo.pk),
        )
        self.client.force_login(self.organization_admin)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(url).status_code, 200)
        other_project = Project.objects.exclude(pk=self.project.pk).first()
        mismatch = reverse(
            "superadmin:project-content-preview",
            args=(other_project.pk, "photo", photo.pk),
        )
        self.assertEqual(self.client.get(mismatch).status_code, 404)

    def test_admin_modals_use_shared_accessible_responsive_behaviors(self):
        self.client.force_login(self.superuser)
        for url in (
            reverse("superadmin:organization-list"),
            reverse("superadmin:organization-detail", args=(self.organization.pk,)),
            reverse("superadmin:user-detail", args=(self.engineer.pk,)),
            reverse("superadmin:project-detail", args=(self.project.pk,)),
            reverse("superadmin:settings"),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "data-admin-modal-policy-template")
            self.assertContains(response, "aria-modal")
            self.assertContains(response, "dataset.submitting")
            self.assertContains(response, "max-h-[92vh]")

    def test_e12_mutating_endpoints_reject_get_requests(self):
        stage = ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="GET protégé",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            created_by=self.engineer,
        )
        self.client.force_login(self.superuser)
        urls = (
            reverse("superadmin:organization-create"),
            reverse("superadmin:organization-update", args=(self.organization.pk,)),
            reverse("superadmin:organization-lifecycle", args=(self.organization.pk,)),
            reverse("superadmin:user-create"),
            reverse("superadmin:user-update", args=(self.engineer.pk,)),
            reverse("superadmin:user-transfer", args=(self.engineer.pk,)),
            reverse("superadmin:project-intervene", args=(self.project.pk,)),
            reverse(
                "superadmin:project-content-action",
                args=(self.project.pk, "stage", stage.pk),
            ),
        )
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405, url)
