from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.organizations.models import Organization
from apps.planning.models import ProjectStage, StageProgressDeclaration, StageProgressVerification, StageTechnicalReview, StageDigitalVerification, StageSiteVisit, StageSiteVerification, StageInspectionRiskRule
from apps.planning.services import review_stage_progress, run_stage_digital_verification, verify_stage_progress, record_stage_site_visit, complete_stage_site_verification, create_inspection_risk_rule, evaluate_stage_inspection_risk, inspection_requirement_is_satisfied
from apps.collaboration.models import EvidenceRecord
from apps.audit.models import AuditEvent
from apps.projects.models import Project, ProjectMembership


class ProjectStageTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Planning Corp", slug="planning-corp")
        self.other_organization = Organization.objects.create(name="Other Corp", slug="other-corp")
        self.engineer = get_user_model().objects.create_user(
            username="planning-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.manager = get_user_model().objects.create_user(
            username="planning-manager",
            organization=self.organization,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.client_user = get_user_model().objects.create_user(
            username="planning-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.foreign_engineer = get_user_model().objects.create_user(
            username="foreign-planning-engineer",
            organization=self.other_organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet planifié",
            location="Douala",
            project_date=date.today(),
        )
        for user in (self.manager, self.client_user):
            ProjectMembership.objects.create(
                organization=self.organization,
                project=self.project,
                user=user,
                project_role=(
                    ProjectMembership.Role.OWNER
                    if user.role == user.Role.CLIENT
                    else ProjectMembership.Role.SITE_MANAGER
                ),
            )
        self.create_url = reverse("planning:stage-create", kwargs={"project_pk": self.project.pk})
        self.valid_data = {
            "title": "Fondations",
            "description": "Terrassement et fondations",
            "start_date": "2026-09-01",
            "end_date": "2026-09-15",
            "estimated_cost": "2500000",
            "actual_cost": "0",
            "status": ProjectStage.Status.PENDING,
        }

    def create_stage(self):
        return ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            created_by=self.engineer,
            title="Fondations",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 15),
            estimated_cost=Decimal("2500000"),
        )

    def test_engineer_can_create_stage(self):
        self.client.force_login(self.engineer)

        response = self.client.post(self.create_url, self.valid_data)

        self.assertEqual(response.status_code, 302)
        stage = ProjectStage.objects.get()
        self.assertEqual(stage.organization, self.organization)
        self.assertEqual(stage.created_by, self.engineer)

    def test_assigned_site_manager_can_create_and_update_stage(self):
        self.client.force_login(self.manager)
        self.client.post(self.create_url, self.valid_data)
        stage = ProjectStage.objects.get()

        data = {**self.valid_data, "title": "Fondations terminées", "status": "complete"}
        response = self.client.post(
            reverse(
                "planning:stage-update", kwargs={"project_pk": self.project.pk, "pk": stage.pk}
            ),
            data,
        )

        self.assertEqual(response.status_code, 302)
        stage.refresh_from_db()
        self.assertEqual(stage.title, "Fondations terminées")
        self.assertEqual(stage.status, ProjectStage.Status.COMPLETE)

    def test_project_engineer_can_update_an_existing_stage(self):
        stage = self.create_stage()
        self.client.force_login(self.engineer)
        data = {
            **self.valid_data,
            "title": "Fondations modifiées",
            "description": "Étape corrigée depuis la fiche du projet.",
            "actual_cost": "1750000",
            "status": ProjectStage.Status.ACTIVE,
        }

        response = self.client.post(
            reverse(
                "planning:stage-update", kwargs={"project_pk": self.project.pk, "pk": stage.pk}
            ),
            data,
        )

        self.assertRedirects(
            response, f'{reverse("projects:detail", kwargs={"pk": self.project.pk})}?tab=stages'
        )
        stage.refresh_from_db()
        self.assertEqual(stage.title, "Fondations modifiées")
        self.assertEqual(stage.description, "Étape corrigée depuis la fiche du projet.")
        self.assertEqual(stage.actual_cost, Decimal("1750000"))
        self.assertEqual(stage.status, ProjectStage.Status.ACTIVE)

    def test_client_can_consult_but_cannot_create_stage(self):
        self.create_stage()
        self.client.force_login(self.client_user)

        detail = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}), {"tab": "stages"}
        )
        denied = self.client.post(self.create_url, self.valid_data)

        self.assertContains(detail, "Fondations")
        self.assertContains(detail, "Consultation")
        self.assertNotContains(detail, "Nouvelle étape")
        self.assertEqual(denied.status_code, 403)

    def test_end_date_before_start_date_is_rejected(self):
        self.client.force_login(self.engineer)
        invalid_data = {**self.valid_data, "end_date": "2026-08-31"}

        self.client.post(self.create_url, invalid_data)

        self.assertFalse(ProjectStage.objects.exists())

    def test_negative_cost_is_rejected(self):
        self.client.force_login(self.engineer)
        invalid_data = {**self.valid_data, "estimated_cost": "-1"}

        self.client.post(self.create_url, invalid_data)

        self.assertFalse(ProjectStage.objects.exists())

    def test_model_rejects_cross_organization_project(self):
        foreign_project = Project.objects.create(
            organization=self.other_organization,
            engineer=self.foreign_engineer,
            name="Projet externe",
            location="Yaoundé",
            project_date=date.today(),
        )
        stage = ProjectStage(
            organization=self.organization,
            project=foreign_project,
            created_by=self.engineer,
            title="Étape invalide",
            start_date=date.today(),
            end_date=date.today(),
        )

        with self.assertRaises(ValidationError):
            stage.full_clean()

    def test_foreign_engineer_cannot_access_stage_endpoint(self):
        self.client.force_login(self.foreign_engineer)

        response = self.client.post(self.create_url, self.valid_data)

        self.assertEqual(response.status_code, 404)

    def test_unassigned_site_manager_cannot_manage_stages(self):
        unassigned = get_user_model().objects.create_user(
            username="unassigned-manager",
            organization=self.organization,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.client.force_login(unassigned)

        response = self.client.post(self.create_url, self.valid_data)

        self.assertEqual(response.status_code, 404)

    def test_timeline_shows_progress_costs_and_overdue_state(self):
        stage = self.create_stage()
        stage.start_date = date(2020, 1, 1)
        stage.end_date = date(2020, 1, 2)
        stage.status = ProjectStage.Status.ACTIVE
        stage.save(update_fields=("start_date", "end_date", "status"))
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}), {"tab": "stages"}
        )

        self.assertContains(response, "Chronologie du chantier")
        self.assertContains(response, "50 %")
        self.assertContains(response, "En retard")
        self.assertContains(response, "2500000")
        self.assertContains(response, "Ouvrir")

    def test_valid_image_can_be_associated_with_stage(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), color="blue").save(buffer, format="PNG")
        image = SimpleUploadedFile("chantier.png", buffer.getvalue(), content_type="image/png")
        self.client.force_login(self.engineer)

        self.client.post(self.create_url, {**self.valid_data, "image": image})

        self.assertTrue(ProjectStage.objects.get().image.name.endswith(".png"))

    def test_declared_and_verified_progress_are_distinct_and_sourced(self):
        stage = self.create_stage()
        evidence = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, stage=stage,
            author=self.manager, evidence_type=EvidenceRecord.Type.PHOTO, title="Avancement terrain",
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("planning:stage-progress-declare", kwargs={"project_pk": self.project.pk, "pk": stage.pk}),
            {"percent": 70, "note": "Avancement déclaré sur site", "evidence": evidence.pk},
        )
        self.assertEqual(response.status_code, 302)
        declaration = StageProgressDeclaration.objects.get()
        self.assertEqual(declaration.author, self.manager)
        self.assertEqual(declaration.percent, 70)
        self.assertIsNotNone(declaration.created_at)
        self.assertFalse(StageProgressVerification.objects.exists())

        review_stage_progress(
            actor=self.engineer, declaration=declaration, decision="approved",
            reason="Preuve conforme",
        )
        run_stage_digital_verification(actor=self.engineer, declaration=declaration)

        self.client.force_login(self.engineer)
        self.client.post(
            reverse("planning:stage-progress-verify", kwargs={"project_pk": self.project.pk, "pk": stage.pk}),
            {"percent": 55, "note": "Mesure technique"},
        )
        verification = StageProgressVerification.objects.get()
        self.assertEqual(verification.author, self.engineer)
        self.assertEqual(stage.declared_progress_percent, 70)
        self.assertEqual(stage.verified_progress_percent, 55)

    def test_site_manager_cannot_create_verified_progress(self):
        stage = self.create_stage()
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("planning:stage-progress-verify", kwargs={"project_pk": self.project.pk, "pk": stage.pk}),
            {"percent": 80, "note": "Tentative"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(StageProgressVerification.objects.exists())

    def test_stage_page_labels_both_progress_sources(self):
        stage = self.create_stage()
        StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, author=self.manager, percent=75,
        )
        StageProgressVerification.objects.create(
            organization=self.organization, stage=stage, author=self.engineer, percent=50,
        )
        self.client.force_login(self.client_user)
        response = self.client.get(self.project.get_absolute_url(), {"tab": "stages"})
        self.assertContains(response, "Progression terrain")
        self.assertContains(response, "Déclarée")
        self.assertContains(response, "Vérifiée")
        self.assertContains(response, "75 %")
        self.assertContains(response, "50 %")

    def test_engineer_records_all_technical_decisions_with_reason_and_correctives(self):
        for decision in StageTechnicalReview.Decision.values:
            declaration = StageProgressDeclaration.objects.create(
                organization=self.organization, stage=self.create_stage(),
                author=self.manager, percent=40,
            )
            review = review_stage_progress(
                actor=self.engineer, declaration=declaration, decision=decision,
                reason="Contrôle terrain documenté",
                corrective_actions=("Reprendre les réserves" if decision != "approved" else ""),
            )
            self.assertEqual(review.decision, decision)
            self.assertEqual(review.reviewer, self.engineer)
            self.assertIsNotNone(review.created_at)

    def test_conditional_or_rejected_review_requires_corrective_actions(self):
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=self.create_stage(), author=self.manager, percent=40,
        )
        with self.assertRaises(ValidationError):
            review_stage_progress(
                actor=self.engineer, declaration=declaration,
                decision=StageTechnicalReview.Decision.CONDITIONAL,
                reason="Réserves", corrective_actions="",
            )

    def test_new_evidence_declaration_opens_a_new_review(self):
        stage = self.create_stage()
        first = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, author=self.manager, percent=40,
        )
        review_stage_progress(
            actor=self.engineer, declaration=first, decision="rejected",
            reason="Preuve insuffisante", corrective_actions="Ajouter une photo datée",
        )
        evidence = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, stage=stage,
            author=self.manager, evidence_type=EvidenceRecord.Type.PHOTO, title="Correction terrain",
        )
        second = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, author=self.manager,
            percent=45, evidence=evidence,
        )
        self.assertNotEqual(first.pk, second.pk)
        self.assertFalse(hasattr(second, "technical_review"))
        self.assertTrue(hasattr(first, "technical_review"))

    def test_digital_verified_checks_and_references_every_examined_item(self):
        stage = self.create_stage()
        evidence = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, stage=stage,
            author=self.manager, evidence_type=EvidenceRecord.Type.PHOTO, title="Photo numérique",
        )
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, author=self.manager,
            percent=65, evidence=evidence,
        )
        review = review_stage_progress(
            actor=self.engineer, declaration=declaration, decision="approved", reason="Conforme",
        )
        result = run_stage_digital_verification(actor=self.engineer, declaration=declaration)
        self.assertEqual(result.result, StageDigitalVerification.Result.PASSED)
        self.assertTrue(all(result.checks.values()))
        self.assertEqual(result.examined_items["declaration"]["id"], str(declaration.pk))
        self.assertEqual(result.examined_items["evidence"]["id"], str(evidence.pk))
        self.assertEqual(result.examined_items["technical_review"]["id"], str(review.pk))

    def test_failed_digital_verification_blocks_verified_progress(self):
        stage = self.create_stage()
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, author=self.manager, percent=65,
        )
        result = run_stage_digital_verification(actor=self.engineer, declaration=declaration)
        self.assertEqual(result.result, StageDigitalVerification.Result.FAILED)
        self.assertFalse(result.checks["evidence_present"])
        with self.assertRaises(ValidationError):
            verify_stage_progress(actor=self.engineer, stage=stage, percent=65)

    def test_authorized_replacement_engineer_signs_structured_technical_verification(self):
        stage = self.create_stage()
        evidence = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, stage=stage,
            author=self.manager, evidence_type=EvidenceRecord.Type.PHOTO, title="Mesure technique",
        )
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, author=self.manager,
            percent=72, evidence=evidence,
        )
        review_stage_progress(actor=self.engineer, declaration=declaration, decision="approved", reason="Conforme")
        run_stage_digital_verification(actor=self.engineer, declaration=declaration)
        replacement = get_user_model().objects.create_user(
            username="replacement-engineer", organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        ProjectMembership.objects.create(
            organization=self.organization, project=self.project, user=replacement,
            project_role=ProjectMembership.Role.ENGINEER,
        )
        verification = verify_stage_progress(
            actor=replacement, stage=stage, percent=68,
            quantities=[{"label": "Béton coulé", "quantity": 12, "unit": "m³"}],
            reservations=[{"description": "Reprise d'un joint", "status": "open"}],
            note="Mesure contradictoire",
        )
        self.assertEqual(verification.author, replacement)
        self.assertEqual(verification.declaration, declaration)
        self.assertEqual(len(verification.logical_signature), 64)
        self.assertIsNotNone(verification.signed_at)
        self.assertEqual(verification.quantities[0]["unit"], "m³")
        self.assertEqual(verification.reservations[0]["status"], "open")
        audit = AuditEvent.objects.get(action="stage.progress_verified", target_id=str(verification.pk))
        self.assertEqual(audit.metadata["logical_signature"], verification.logical_signature)

    def test_project_role_engineer_sees_and_can_use_progress_review_actions(self):
        stage = self.create_stage()
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization,
            stage=stage,
            author=self.manager,
            percent=64,
        )
        replacement = get_user_model().objects.create_user(
            username="membership-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=replacement,
            project_role=ProjectMembership.Role.ENGINEER,
        )

        self.client.force_login(replacement)
        response = self.client.get(self.project.get_absolute_url(), {"tab": "stages"})

        self.assertEqual(response.status_code, 200)
        displayed_stage = next(item for item in response.context["stages"] if item.pk == stage.pk)
        self.assertIsNotNone(displayed_stage.technical_review_form)
        self.assertIsNone(displayed_stage.verification_form)

        review = review_stage_progress(
            actor=replacement,
            declaration=declaration,
            decision=StageTechnicalReview.Decision.APPROVED,
            reason="Preuve conforme",
        )
        self.assertEqual(review.reviewer, replacement)

    def test_verify_action_appears_only_after_successful_digital_verification(self):
        stage = self.create_stage()
        evidence = EvidenceRecord.objects.create(
            organization=self.organization,
            project=self.project,
            stage=stage,
            author=self.manager,
            evidence_type=EvidenceRecord.Type.PHOTO,
            title="Preuve de progression",
        )
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization,
            stage=stage,
            author=self.manager,
            percent=64,
            evidence=evidence,
        )
        self.client.force_login(self.engineer)

        before = self.client.get(self.project.get_absolute_url(), {"tab": "stages"})
        displayed_stage = next(item for item in before.context["stages"] if item.pk == stage.pk)
        self.assertIsNone(displayed_stage.verification_form)

        review_stage_progress(
            actor=self.engineer,
            declaration=declaration,
            decision=StageTechnicalReview.Decision.APPROVED,
            reason="Preuve conforme",
        )
        run_stage_digital_verification(actor=self.engineer, declaration=declaration)

        after = self.client.get(self.project.get_absolute_url(), {"tab": "stages"})
        displayed_stage = next(item for item in after.context["stages"] if item.pk == stage.pk)
        self.assertIsNotNone(displayed_stage.verification_form)

        verify_stage_progress(actor=self.engineer, stage=stage, percent=60)
        completed = self.client.get(self.project.get_absolute_url(), {"tab": "stages"})
        displayed_stage = next(item for item in completed.context["stages"] if item.pk == stage.pk)
        self.assertIsNone(displayed_stage.verification_form)

    def test_unassigned_engineer_cannot_sign_technical_verification(self):
        stage = self.create_stage()
        outsider = get_user_model().objects.create_user(
            username="unassigned-technical", organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        with self.assertRaises(PermissionDenied):
            verify_stage_progress(actor=outsider, stage=stage, percent=10)

    def test_pivot_site_verified_preserves_all_inspection_data(self):
        stage = self.create_stage()
        reviewer = get_user_model().objects.create_user(username="site-inspector", organization=self.organization, role=get_user_model().Role.ADMIN)
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=reviewer, project_role=ProjectMembership.Role.PIVOT_REVIEWER)
        evidence = EvidenceRecord.objects.create(organization=self.organization, project=self.project, stage=stage, author=self.manager, evidence_type=EvidenceRecord.Type.PHOTO, title="Photo inspection")
        declaration = StageProgressDeclaration.objects.create(organization=self.organization, stage=stage, author=self.manager, percent=80, evidence=evidence)
        review_stage_progress(actor=self.engineer, declaration=declaration, decision="approved", reason="Conforme")
        run_stage_digital_verification(actor=self.engineer, declaration=declaration)
        technical = verify_stage_progress(actor=self.engineer, stage=stage, percent=75, quantities=[{"label": "Poteaux", "quantity": 8, "unit": "u"}], reservations=[])
        visit = record_stage_site_visit(actor=reviewer, stage=stage, visited_at=timezone.now(), location_label="Chantier Bonamoussadi", latitude="4.090000", longitude="9.740000", notes="Visite contradictoire")
        inspection = complete_stage_site_verification(actor=reviewer, visit=visit, technical_verification=technical, checklist=[{"item": "Implantation", "result": "ok", "comment": "Conforme"}], evidence=[evidence], reservations=[], result=StageSiteVerification.Result.PASSED)
        self.assertEqual(inspection.inspector, reviewer)
        self.assertEqual(inspection.visit.location_label, "Chantier Bonamoussadi")
        self.assertEqual(inspection.checklist[0]["result"], "ok")
        self.assertEqual(list(inspection.evidence.all()), [evidence])
        self.assertTrue(AuditEvent.objects.filter(action="stage.site_visit_recorded", target_id=str(visit.pk)).exists())
        self.assertTrue(AuditEvent.objects.filter(action="stage.site_verified", target_id=str(inspection.pk)).exists())

    def test_site_verification_cannot_be_declared_without_recorded_visit(self):
        self.client.force_login(self.engineer)
        response = self.client.post(reverse("planning:stage-site-verification-create", kwargs={"project_pk": self.project.pk, "pk": self.create_stage().pk, "visit_pk": "00000000-0000-0000-0000-000000000000"}), {})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(StageSiteVerification.objects.exists())

    def test_non_pivot_actor_cannot_record_site_visit(self):
        with self.assertRaises(PermissionDenied):
            record_stage_site_visit(actor=self.engineer, stage=self.create_stage(), visited_at=timezone.now(), location_label="Chantier")

    def test_risk_rule_imposes_inspection_for_critical_milestone_or_anomaly(self):
        stage = self.create_stage()
        stage.stage_type = ProjectStage.Type.FOUNDATION
        stage.save(update_fields=("stage_type",))
        evidence = EvidenceRecord.objects.create(organization=self.organization, project=self.project, stage=stage, author=self.manager, evidence_type=EvidenceRecord.Type.PHOTO, title="Risque")
        declaration = StageProgressDeclaration.objects.create(organization=self.organization, stage=stage, author=self.manager, percent=90, evidence=evidence)
        review_stage_progress(actor=self.engineer, declaration=declaration, decision="approved", reason="Conforme")
        run_stage_digital_verification(actor=self.engineer, declaration=declaration)
        technical = verify_stage_progress(actor=self.engineer, stage=stage, percent=50, quantities=[], reservations=[{"description": "Écart", "status": "open"}])
        admin = get_user_model().objects.create_superuser(username="risk-admin", email="risk@pivot.test", password="pass")
        first = create_inspection_risk_rule(actor=admin, organization=self.organization, data={"stage_types": [ProjectStage.Type.FOUNDATION]})
        second = create_inspection_risk_rule(actor=admin, organization=self.organization, data={"stage_types": [ProjectStage.Type.FOUNDATION]})
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(second.version, first.version + 1)
        assessment = evaluate_stage_inspection_risk(actor=self.engineer, technical_verification=technical)
        self.assertTrue(assessment.inspection_required)
        self.assertEqual(set(assessment.reasons), {"type_de_jalon", "anomalie"})
        self.assertFalse(inspection_requirement_is_satisfied(stage))
        self.assertTrue(AuditEvent.objects.filter(action="stage.inspection_risk_evaluated").exists())

    def test_calendar_and_json_only_include_accessible_projects(self):
        own_stage = self.create_stage()
        foreign_project = Project.objects.create(
            organization=self.other_organization,
            engineer=self.foreign_engineer,
            name="Projet calendrier externe",
            location="Yaoundé",
            project_date=date.today(),
        )
        ProjectStage.objects.create(
            organization=self.other_organization,
            project=foreign_project,
            created_by=self.foreign_engineer,
            title="Étape secrète",
            start_date=date.today(),
            end_date=date.today(),
        )
        self.client.force_login(self.engineer)

        page = self.client.get(reverse("planning:calendar"))
        payload = self.client.get(reverse("planning:calendar-events")).json()

        self.assertContains(page, own_stage.title)
        self.assertNotContains(page, "Étape secrète")
        titles = [event["title"] for event in payload["events"]]
        self.assertEqual(titles, [self.project.name, own_stage.title])
        self.assertNotIn("Projet calendrier externe", titles)

    def test_project_without_stage_still_appears_in_calendar(self):
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("planning:calendar"))
        payload = self.client.get(reverse("planning:calendar-events")).json()

        self.assertContains(response, self.project.name)
        self.assertEqual(payload["events"][0]["type"], "project")

    def test_calendar_json_refuses_anonymous_and_foreign_project_filter(self):
        foreign_project = Project.objects.create(
            organization=self.other_organization,
            engineer=self.foreign_engineer,
            name="Projet externe JSON",
            location="Yaoundé",
            project_date=date.today(),
        )
        anonymous = self.client.get(reverse("planning:calendar-events"))
        self.client.force_login(self.engineer)
        foreign = self.client.get(
            reverse("planning:calendar-events"), {"project": str(foreign_project.pk)}
        )

        self.assertEqual(anonymous.status_code, 302)
        self.assertEqual(foreign.status_code, 404)

    def test_assigned_client_can_export_project_stages_csv(self):
        self.create_stage()
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("planning:stages-export", kwargs={"project_pk": self.project.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Fondations", response.content.decode("utf-8-sig"))

    def test_csv_export_refuses_foreign_project(self):
        foreign_project = Project.objects.create(
            organization=self.other_organization,
            engineer=self.foreign_engineer,
            name="Projet export externe",
            location="Yaoundé",
            project_date=date.today(),
        )
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("planning:stages-export", kwargs={"project_pk": foreign_project.pk})
        )

        self.assertEqual(response.status_code, 404)
