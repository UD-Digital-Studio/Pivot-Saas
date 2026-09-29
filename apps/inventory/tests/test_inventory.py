import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpenseRequest, ExpenseTechnicalOpinion
from apps.inventory.models import (
    InventoryAnomaly, InventoryAnomalyResolution, InventoryExpectedRange,
    StockItem, StockMovement,
)
from apps.inventory.services import (
    adjust_stock, assign_expected_range, decide_anomaly_resolution,
    detect_expense_inventory_anomalies, propose_anomaly_resolution, record_stock_movement,
)
from apps.organizations.models import Organization
from apps.planning.models import (
    ProjectStage, StageProgressDeclaration, StageProgressVerification,
)
from apps.projects.controlled_value import controlled_value_indicators
from apps.projects.models import Project, ProjectMembership


class InventoryTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Stock Corp", slug="stock-corp")
        self.other_organization = Organization.objects.create(
            name="Foreign Stock", slug="foreign-stock"
        )
        self.engineer = get_user_model().objects.create_user(
            username="stock-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.manager = get_user_model().objects.create_user(
            username="stock-manager",
            organization=self.organization,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.contractor = get_user_model().objects.create_user(
            username="stock-contractor",
            organization=self.organization,
            role=get_user_model().Role.CONTRACTOR,
        )
        self.client_user = get_user_model().objects.create_user(
            username="stock-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.foreign_engineer = get_user_model().objects.create_user(
            username="foreign-stock-engineer",
            organization=self.other_organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.reviewer = get_user_model().objects.create_user(
            username="stock-reviewer", organization=self.organization,
            role=get_user_model().Role.ADMIN,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet stock",
            location="Douala",
            project_date=date.today(),
        )
        self.foreign_project = Project.objects.create(
            organization=self.other_organization,
            engineer=self.foreign_engineer,
            name="Projet stock secret",
            location="Yaoundé",
            project_date=date.today(),
        )
        for user in (self.manager, self.client_user, self.contractor):
            ProjectMembership.objects.create(
                organization=self.organization,
                project=self.project,
                user=user,
                project_role=(
                    ProjectMembership.Role.OWNER
                    if user.role == user.Role.CLIENT
                    else ProjectMembership.Role.CONTRACTOR
                    if user.role == user.Role.CONTRACTOR
                    else ProjectMembership.Role.SITE_MANAGER
                ),
            )
        ProjectMembership.objects.create(
            organization=self.organization, project=self.project, user=self.reviewer,
            project_role=ProjectMembership.Role.PIVOT_REVIEWER,
        )
        self.item_data = {
            "name": "Ciment",
            "unit": "sac",
            "unit_price": "6500",
            "quantity": "100",
            "alert_threshold": "20",
        }

    def create_item(self, *, creator=None, quantity="100"):
        return StockItem.objects.create(
            organization=self.organization,
            project=self.project,
            created_by=creator or self.manager,
            name="Ciment",
            unit="sac",
            unit_price=Decimal("6500"),
            quantity=Decimal(quantity),
            alert_threshold=Decimal("20"),
        )

    def test_engineer_and_assigned_manager_can_create_items(self):
        url = reverse("inventory:item-create", kwargs={"project_pk": self.project.pk})
        for user, name in ((self.engineer, "Ciment"), (self.manager, "Sable")):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.post(url, {**self.item_data, "name": name})
                self.assertEqual(response.status_code, 302)
        self.assertEqual(StockItem.objects.count(), 2)

    def test_total_price_is_derived_and_low_stock_is_visible(self):
        item = self.create_item(quantity="10")
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}), {"tab": "stock"}
        )

        self.assertEqual(item.total_price, Decimal("65000"))
        self.assertContains(response, "Stock faible")
        self.assertNotContains(response, "Nouvel article")

    def test_adjustment_is_atomic_traced_and_idempotent(self):
        item = self.create_item()
        key = uuid.uuid4()

        first, created = adjust_stock(
            actor=self.manager,
            item=item,
            variation=Decimal("-12"),
            reason="Utilisation",
            idempotency_key=key,
        )
        second, created_again = adjust_stock(
            actor=self.manager,
            item=item,
            variation=Decimal("-12"),
            reason="Utilisation",
            idempotency_key=key,
        )

        item.refresh_from_db()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, second)
        self.assertEqual(item.quantity, Decimal("88"))
        self.assertEqual(StockMovement.objects.count(), 2)  # ouverture + correction
        self.assertEqual(first.resulting_quantity, Decimal("88"))
        self.assertEqual(first.actor, self.manager)

    def test_adjustment_cannot_make_stock_negative(self):
        item = self.create_item(quantity="5")

        with self.assertRaises(ValidationError):
            adjust_stock(
                actor=self.manager,
                item=item,
                variation=Decimal("-6"),
                reason="Sortie invalide",
                idempotency_key=uuid.uuid4(),
            )
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("5"))
        self.assertFalse(StockMovement.objects.exists())

    def test_purchased_delivered_consumed_and_remaining_are_distinct(self):
        item = self.create_item(quantity="0")
        common = {"actor": self.manager, "item": item, "source_unit": "palette",
                  "conversion_factor": Decimal("20"), "reason": "Traçabilité E21"}
        record_stock_movement(
            **common, movement_type=StockMovement.Type.PURCHASED,
            source_quantity=Decimal("3"), source_reference="Facture FAC-01",
            idempotency_key=uuid.uuid4(),
        )
        record_stock_movement(
            **common, movement_type=StockMovement.Type.DELIVERED,
            source_quantity=Decimal("2"), source_reference="Bon BL-01",
            idempotency_key=uuid.uuid4(),
        )
        record_stock_movement(
            actor=self.manager, item=item, movement_type=StockMovement.Type.CONSUMED,
            source_quantity=Decimal("5"), source_unit="sac", conversion_factor=Decimal("1"),
            source_reference="Fiche consommation FC-01", reason="Pose",
            idempotency_key=uuid.uuid4(),
        )
        item.refresh_from_db()
        self.assertEqual(item.purchased_quantity, Decimal("60"))
        self.assertEqual(item.delivered_quantity, Decimal("40"))
        self.assertEqual(item.consumed_quantity, Decimal("5"))
        self.assertEqual(item.derived_remaining_quantity, Decimal("35"))
        self.assertEqual(item.quantity, Decimal("35"))
        delivery = item.movements.get(movement_type=StockMovement.Type.DELIVERED)
        self.assertEqual(delivery.source_reference, "Bon BL-01")
        self.assertEqual(delivery.source_unit, "palette")
        self.assertEqual(delivery.conversion_factor, Decimal("20"))

    def test_typed_movement_form_records_source_and_conversion(self):
        item = self.create_item(quantity="0")
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("inventory:item-adjust", kwargs={"project_pk": self.project.pk, "pk": item.pk}),
            {"movement_type": "delivered", "source_quantity": "2", "source_unit": "palette",
             "conversion_factor": "20", "source_reference": "BL-2026-07",
             "reason": "Réception chantier", "idempotency_key": uuid.uuid4()},
        )
        self.assertEqual(response.status_code, 302)
        movement = item.movements.get()
        self.assertEqual(movement.normalized_quantity, Decimal("40"))
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("40"))

    def test_movement_reuses_evidence_and_stage_from_same_project(self):
        item = self.create_item(quantity="0")
        stage = ProjectStage.objects.create(
            organization=self.organization, project=self.project, title="Fondations",
            start_date=date.today(), end_date=date.today(), created_by=self.engineer,
        )
        invoice = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, stage=stage,
            author=self.manager, evidence_type=EvidenceRecord.Type.INVOICE,
            title="Facture ciment",
        )
        movement, _ = record_stock_movement(
            actor=self.manager, item=item, movement_type=StockMovement.Type.PURCHASED,
            source_quantity=10, source_unit="sac", conversion_factor=1,
            source_reference="FAC-10", reason="Achat", idempotency_key=uuid.uuid4(),
            evidence=invoice, stage=stage,
        )
        self.assertEqual(movement.evidence_id, invoice.pk)
        self.assertEqual(movement.stage_id, stage.pk)
        self.assertEqual(EvidenceRecord.objects.filter(pk=invoice.pk).count(), 1)

    def test_cross_project_reconciliation_is_rejected(self):
        item = self.create_item(quantity="0")
        foreign_evidence = EvidenceRecord.objects.create(
            organization=self.other_organization, project=self.foreign_project,
            author=self.foreign_engineer, evidence_type=EvidenceRecord.Type.INVOICE,
            title="Facture étrangère",
        )
        with self.assertRaises(ValidationError):
            record_stock_movement(
                actor=self.manager, item=item, movement_type=StockMovement.Type.PURCHASED,
                source_quantity=1, source_unit="sac", conversion_factor=1,
                source_reference="FAC-X", reason="Interdit", idempotency_key=uuid.uuid4(),
                evidence=foreign_evidence,
            )

    def test_engineer_creates_versioned_expected_ranges_without_automatic_decision(self):
        item = self.create_item(quantity="10")
        first = assign_expected_range(
            actor=self.engineer, item=item, work_type="Mur en blocs", unit="sac",
            minimum_quantity=Decimal("8"), maximum_quantity=Decimal("12"),
            assumptions="Mur de 20 m², dosage standard.",
        )
        second = assign_expected_range(
            actor=self.engineer, item=item, work_type="Mur en blocs", unit="sac",
            minimum_quantity=Decimal("9"), maximum_quantity=Decimal("14"),
            assumptions="Révision pour joints renforcés.",
        )
        item.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(first.version, 1)
        self.assertFalse(first.is_active)
        self.assertEqual(second.version, 2)
        self.assertEqual(second.supersedes, first)
        self.assertEqual(item.expected_range, second)
        self.assertEqual(item.quantity, Decimal("10"))
        self.assertEqual(item.status, StockItem.Status.PENDING)
        self.assertTrue(AuditEvent.objects.filter(action="stock.expected_range_assigned").exists())

    def test_existing_range_can_be_selected_but_cross_project_range_cannot(self):
        item = self.create_item(quantity="0")
        rule = InventoryExpectedRange.objects.create(
            organization=self.organization, project=self.project, work_type="Dalle",
            unit="sac", minimum_quantity=5, maximum_quantity=8,
            assumptions="Dalle de référence.", version=1, created_by=self.engineer,
        )
        self.assertEqual(
            assign_expected_range(actor=self.engineer, item=item, existing_range=rule), rule
        )
        foreign_rule = InventoryExpectedRange.objects.create(
            organization=self.other_organization, project=self.foreign_project,
            work_type="Dalle", unit="sac", minimum_quantity=1, maximum_quantity=2,
            assumptions="Autre projet.", version=1, created_by=self.foreign_engineer,
        )
        with self.assertRaises(ValidationError):
            assign_expected_range(actor=self.engineer, item=item, existing_range=foreign_rule)

    def test_site_manager_cannot_configure_expected_range(self):
        item = self.create_item(quantity="0")
        with self.assertRaises(PermissionDenied):
            assign_expected_range(
                actor=self.manager, item=item, work_type="Mur", unit="sac",
                minimum_quantity=1, maximum_quantity=2, assumptions="Hypothèse.",
            )

    def anomaly_fixture(self, action="flag"):
        stage = ProjectStage.objects.create(
            organization=self.organization, project=self.project, title="Élévation",
            start_date=date.today(), end_date=date.today(), created_by=self.engineer,
        )
        expense = ExpenseRequest.objects.create(
            organization=self.organization, project=self.project, author=self.contractor,
            milestone=stage, amount=50000, purpose="Matériaux", beneficiary="Fournisseur",
            due_date=date.today(), status=ExpenseRequest.Status.AUTHORIZED,
        )
        item = self.create_item(quantity="0")
        assign_expected_range(
            actor=self.engineer, item=item, work_type="Élévation", unit="sac",
            minimum_quantity=10, maximum_quantity=20, assumptions="Ouvrage test.",
            out_of_range_action=action,
        )
        record_stock_movement(
            actor=self.manager, item=item, movement_type=StockMovement.Type.DELIVERED,
            source_quantity=30, source_unit="sac", conversion_factor=1,
            source_reference="BL-30", reason="Livraison", idempotency_key=uuid.uuid4(),
            stage=stage,
        )
        record_stock_movement(
            actor=self.manager, item=item, movement_type=StockMovement.Type.CONSUMED,
            source_quantity=25, source_unit="sac", conversion_factor=1,
            source_reference="FC-25", reason="Consommation", idempotency_key=uuid.uuid4(),
            stage=stage,
        )
        anomaly = detect_expense_inventory_anomalies(actor=self.engineer, expense_request=expense)[0]
        proof = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, stage=stage,
            author=self.manager, evidence_type=EvidenceRecord.Type.INSPECTION,
            title="Preuve corrective",
        )
        return anomaly, proof

    def test_resolution_requires_proof_and_keeps_complete_chronology(self):
        anomaly, proof = self.anomaly_fixture()
        with self.assertRaises(ValidationError):
            propose_anomaly_resolution(
                actor=self.manager, anomaly=anomaly, responsible=self.manager,
                evidence=[], reason="Correction effectuée.",
            )
        resolution = propose_anomaly_resolution(
            actor=self.manager, anomaly=anomaly, responsible=self.manager,
            evidence=[proof], reason="Correction effectuée.",
        )
        decide_anomaly_resolution(
            actor=self.engineer, resolution=resolution, decision="approved",
            reason="Preuve contrôlée et correction conforme.",
        )
        anomaly.refresh_from_db()
        resolution.refresh_from_db()
        self.assertEqual(anomaly.status, InventoryAnomaly.Status.RESOLVED)
        self.assertEqual(resolution.status, InventoryAnomalyResolution.Status.APPROVED)
        self.assertEqual(resolution.evidence.get(), proof)
        actions = set(AuditEvent.objects.filter(target_id=str(resolution.pk)).values_list("action", flat=True))
        self.assertEqual(actions, {
            "inventory.anomaly_resolution_proposed", "inventory.anomaly_resolution_decided",
        })

    def test_blocking_anomaly_requires_pivot_reviewer_validation(self):
        anomaly, proof = self.anomaly_fixture(action="block")
        resolution = propose_anomaly_resolution(
            actor=self.manager, anomaly=anomaly, responsible=self.manager,
            evidence=[proof], reason="Écart justifié et corrigé.",
        )
        with self.assertRaises(PermissionDenied):
            decide_anomaly_resolution(
                actor=self.engineer, resolution=resolution, decision="approved", reason="Interdit.",
            )
        decide_anomaly_resolution(
            actor=self.reviewer, resolution=resolution, decision="approved",
            reason="Validation PIVOT documentée.",
        )
        anomaly.refresh_from_db()
        self.assertEqual(anomaly.status, InventoryAnomaly.Status.RESOLVED)

    def test_engineer_verifies_item_and_audit_is_created(self):
        item = self.create_item()
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("inventory:item-verify", kwargs={"project_pk": self.project.pk, "pk": item.pk})
        )

        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, StockItem.Status.VERIFIED)
        self.assertEqual(item.verified_by, self.engineer)
        self.assertIsNotNone(item.verified_at)
        self.assertTrue(AuditEvent.objects.filter(action="stock.item_verified").exists())

    def test_manager_cannot_verify_own_item_and_approved_has_no_browser_action(self):
        item = self.create_item()
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("inventory:item-verify", kwargs={"project_pk": self.project.pk, "pk": item.pk})
        )

        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.status, StockItem.Status.PENDING)
        self.assertIn(StockItem.Status.APPROVED, StockItem.Status.values)

    def test_csv_import_creates_valid_rows_and_reports_invalid_lines(self):
        content = (
            "nom,unite,prix_unitaire,quantite,seuil_alerte\n"
            "Ciment,sac,6500,100,20\n"
            "Sable,m3,12000,-4,2\n"
        )
        upload = SimpleUploadedFile("stock.csv", content.encode(), content_type="text/csv")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("inventory:import", kwargs={"project_pk": self.project.pk}), {"file": upload}
        )

        self.assertContains(response, "1 article créé")
        self.assertContains(response, "Ligne 3")
        item = StockItem.objects.get()
        self.assertEqual(item.organization, self.organization)
        self.assertEqual(item.project, self.project)

    def test_import_template_is_downloadable(self):
        self.client.force_login(self.engineer)
        response = self.client.get(reverse("inventory:import-template"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("prix_unitaire", response.content.decode("utf-8-sig"))

    def test_history_is_paginated_filterable_and_exported(self):
        item = self.create_item()
        for index in range(12):
            adjust_stock(
                actor=self.manager,
                item=item,
                variation=Decimal("1"),
                reason=f"Entrée {index}",
                idempotency_key=uuid.uuid4(),
            )
        self.client.force_login(self.engineer)

        page = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}),
            {"tab": "stock", "date_from": date.today().isoformat()},
        )
        exported = self.client.get(
            reverse("inventory:export", kwargs={"project_pk": self.project.pk}),
            {"date_from": date.today().isoformat()},
        )

        self.assertEqual(page.context["stock_history_page"].paginator.count, 13)
        self.assertEqual(len(page.context["stock_history_page"]), 10)
        csv_content = exported.content.decode("utf-8-sig")
        self.assertIn("Quantité résultante", csv_content)
        self.assertIn("112.00", csv_content)

    def test_foreign_project_stock_is_never_accessible(self):
        self.client.force_login(self.engineer)
        create = self.client.post(
            reverse("inventory:item-create", kwargs={"project_pk": self.foreign_project.pk}),
            self.item_data,
        )
        export = self.client.get(
            reverse("inventory:export", kwargs={"project_pk": self.foreign_project.pk})
        )
        self.assertEqual(create.status_code, 404)
        self.assertEqual(export.status_code, 404)

    def test_client_cannot_adjust_stock(self):
        item = self.create_item()
        self.client.force_login(self.client_user)
        response = self.client.post(
            reverse("inventory:item-adjust", kwargs={"project_pk": self.project.pk, "pk": item.pk}),
            {"variation": "1", "reason": "Interdit", "idempotency_key": uuid.uuid4()},
        )
        self.assertEqual(response.status_code, 403)

    def test_service_refuses_actor_from_another_organization(self):
        item = self.create_item()
        with self.assertRaises(PermissionDenied):
            adjust_stock(
                actor=self.foreign_engineer,
                item=item,
                variation=Decimal("1"),
                reason="Interdit",
                idempotency_key=uuid.uuid4(),
            )

    def test_controlled_value_uses_only_verified_auditable_records(self):
        stage = ProjectStage.objects.create(
            organization=self.organization, project=self.project, title="Fondations",
            start_date=date.today(), end_date=date.today(), created_by=self.engineer,
        )
        declaration = StageProgressDeclaration.objects.create(
            organization=self.organization, stage=stage, percent=40, author=self.manager,
        )
        StageProgressVerification.objects.create(
            organization=self.organization, stage=stage, declaration=declaration,
            percent=35, author=self.engineer, quantities=[], reservations=[],
        )
        verified = ExpenseRequest.objects.create(
            organization=self.organization, project=self.project, author=self.contractor,
            milestone=stage, amount=Decimal("125000"), purpose="Béton contrôlé",
            beneficiary="Fournisseur", due_date=date.today(),
            status=ExpenseRequest.Status.VERIFIED,
        )
        ExpenseTechnicalOpinion.objects.create(
            organization=self.organization, request=verified, engineer=self.engineer,
            decision=ExpenseTechnicalOpinion.Decision.APPROVED,
            reason="Quantités et pièces contrôlées.", reviewed_status_version=verified.status_version,
        )
        ExpenseRequest.objects.create(
            organization=self.organization, project=self.project, author=self.contractor,
            milestone=stage, amount=Decimal("900000"), purpose="Non contrôlé",
            beneficiary="Fournisseur", due_date=date.today(),
            status=ExpenseRequest.Status.REVIEW,
        )

        indicators = controlled_value_indicators(actor=self.engineer, project=self.project)

        self.assertEqual(indicators["verified_expense_amount"], Decimal("125000"))
        self.assertEqual(indicators["verified_expense_count"], 1)
        self.assertEqual(indicators["verified_stage_count"], 1)
        self.assertEqual(indicators["total_stage_count"], 1)
        self.assertEqual(indicators["verification_delay_count"], 1)
        self.assertGreaterEqual(indicators["average_verification_delay_hours"], 0)

    def test_controlled_value_hides_financial_aggregates_from_site_manager(self):
        indicators = controlled_value_indicators(actor=self.manager, project=self.project)

        self.assertFalse(indicators["can_view_financial_value"])
        self.assertIsNone(indicators["verified_expense_amount"])
        self.assertIsNone(indicators["open_anomaly_count"])

        self.client.force_login(self.manager)
        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertContains(response, "Valeur contrôlée")
        self.assertContains(response, "Accès financier restreint")

    def test_controlled_value_rejects_non_member(self):
        with self.assertRaises(PermissionDenied):
            controlled_value_indicators(actor=self.foreign_engineer, project=self.project)
