from datetime import date
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.ai_assistant.policy import SAFE_DENIAL
from apps.ai_assistant.tools import (
    ToolPermissionDenied,
    deterministic_tool_answer,
    run_read_tools,
    tool_context_json,
)
from apps.collaboration.models import ProjectComment, ProjectDocument, ProjectImage
from apps.finance.models import PaymentTransaction, Withdrawal
from apps.inventory.models import StockItem
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPlan


class ReadOnlyAssistantToolsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.org = Organization.objects.create(name="Tools Corp", slug="tools-corp")
        self.other_org = Organization.objects.create(name="Secret Corp", slug="secret-corp")
        self.engineer = user_model.objects.create_user(
            username="tools-engineer",
            organization=self.org,
            role=user_model.Role.ENGINEER,
        )
        self.other_engineer = user_model.objects.create_user(
            username="secret-engineer",
            organization=self.other_org,
            role=user_model.Role.ENGINEER,
        )
        self.client_user = user_model.objects.create_user(
            username="tools-client",
            organization=self.org,
            role=user_model.Role.CLIENT,
        )
        self.manager = user_model.objects.create_user(
            username="tools-manager",
            organization=self.org,
            role=user_model.Role.SITE_MANAGER,
        )
        self.organization_admin = user_model.objects.create_user(
            username="tools-admin",
            organization=self.org,
            role=user_model.Role.ADMIN,
        )
        self.superuser = user_model.objects.create_superuser(
            username="tools-superuser", password="test-password-42"
        )
        common = {
            "location": "Douala",
            "project_date": date(2026, 8, 26),
            "budget_amount": 1_000_000,
        }
        self.project = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Résidence Visible",
            **common,
        )
        self.secret_project = Project.objects.create(
            organization=self.other_org,
            engineer=self.other_engineer,
            name="Projet Ultra Secret",
            **common,
        )
        for user, role in (
            (self.client_user, ProjectMembership.Role.OWNER),
            (self.manager, ProjectMembership.Role.SITE_MANAGER),
            (self.organization_admin, ProjectMembership.Role.PIVOT_REVIEWER),
        ):
            ProjectMembership.objects.create(
                organization=self.org,
                project=self.project,
                user=user,
                project_role=role,
            )
        ProjectStage.objects.create(
            organization=self.org,
            project=self.project,
            title="Fondations",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 20),
            status=ProjectStage.Status.COMPLETE,
            estimated_cost=200_000,
            actual_cost=190_000,
            created_by=self.engineer,
        )
        StockItem.objects.create(
            organization=self.org,
            project=self.project,
            name="Ciment",
            unit="sac",
            unit_price=6500,
            quantity=5,
            alert_threshold=10,
            status=StockItem.Status.APPROVED,
            created_by=self.engineer,
        )
        ProjectDocument.objects.create(
            organization=self.org,
            project=self.project,
            title="Plan approuvé",
            file="approved.pdf",
            status=ProjectDocument.Status.APPROVED,
            uploaded_by=self.engineer,
        )
        ProjectDocument.objects.create(
            organization=self.org,
            project=self.project,
            title="Document confidentiel en attente",
            file="pending.pdf",
            status=ProjectDocument.Status.PENDING,
            uploaded_by=self.engineer,
        )
        ProjectImage.objects.create(
            organization=self.org,
            project=self.project,
            image="photo.jpg",
            caption="Façade principale",
            uploaded_by=self.engineer,
        )
        ProjectComment.objects.create(
            organization=self.org,
            project=self.project,
            author=self.manager,
            content="Le bétonnage est terminé.",
        )
        self.client_payment = PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client_user,
            amount=100_000,
            operator="orange",
            payer_phone="699000001",
            provider_reference="SECRET-REFERENCE",
            idempotency_key=uuid4(),
            status=PaymentTransaction.Status.SUCCESS,
        )
        PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.manager,
            amount=50_000,
            operator="mtn",
            payer_phone="677000002",
            provider_reference="OTHER-SECRET",
            idempotency_key=uuid4(),
            status=PaymentTransaction.Status.SUCCESS,
        )
        Withdrawal.objects.create(
            organization=self.org,
            project=self.project,
            amount=20_000,
            status=Withdrawal.Status.ACCOUNTED,
            reason="Achat matériaux",
            requested_by=self.engineer,
        )

    def result(self, user, question):
        results = run_read_tools(user, question)
        self.assertEqual(len(results), 1)
        return results[0]

    def test_project_stage_stock_and_collaboration_tools_use_accessible_projects(self):
        questions = (
            "Quels sont mes projets ?",
            "Quelle est la progression des étapes ?",
            "Quels articles sont en stock ?",
            "Quels documents sont disponibles ?",
            "Quelles photos sont disponibles ?",
            "Quels sont les derniers commentaires ?",
        )
        for question in questions:
            serialized = tool_context_json(run_read_tools(self.client_user, question))
            self.assertIn(self.project.name, serialized, question)
            self.assertNotIn(self.secret_project.name, serialized, question)

    def test_client_only_receives_approved_documents(self):
        client_data = self.result(self.client_user, "Liste mes documents").data
        engineer_data = self.result(self.engineer, "Liste mes documents").data

        self.assertEqual([item["title"] for item in client_data["documents"]], ["Plan approuvé"])
        self.assertCountEqual(
            [item["title"] for item in engineer_data["documents"]],
            ["Plan approuvé", "Document confidentiel en attente"],
        )

    def test_stock_values_are_calculated_by_django(self):
        data = self.result(self.client_user, "Quel est le stock ?").data["items"][0]

        self.assertEqual(data["quantity"], "5.00")
        self.assertEqual(data["total_value_xaf"], "32500.0000")
        self.assertTrue(data["is_low_stock"])

    def test_client_finance_tool_contains_only_own_payments_and_no_secrets(self):
        result = self.result(self.client_user, "Montre mes paiements")
        serialized = tool_context_json([result])

        self.assertEqual(result.name, "payments.read_own")
        self.assertEqual(result.data["successful_total_xaf"], "100000")
        self.assertEqual(result.data["successful_payment_count"], 1)
        self.assertEqual(
            deterministic_tool_answer([result]),
            "Vous avez déjà payé un total de 100000 XAF sur 1 paiement(s) réussi(s).",
        )
        self.assertEqual(len(result.data["payments"]), 1)
        self.assertNotIn("699000001", serialized)
        self.assertNotIn("SECRET-REFERENCE", serialized)
        self.assertNotIn("payer_phone", serialized)
        self.assertNotIn("provider_reference", serialized)

    def test_client_natural_payment_total_question_returns_real_total(self):
        result = self.result(self.client_user, "J’ai déjà eu à payer combien sur la plateforme ?")

        self.assertEqual(result.name, "payments.read_own")
        self.assertEqual(result.data["scope"], "own_payments_only")
        self.assertEqual(result.data["successful_total_xaf"], "100000")

    def test_engineer_finance_tool_uses_server_calculated_project_totals(self):
        result = self.result(self.engineer, "Donne les finances du projet")
        row = result.data["projects"][0]

        self.assertEqual(row["paid_xaf"], "150000")
        self.assertEqual(row["withdrawn_xaf"], "20000")
        self.assertEqual(row["available_xaf"], "130000")

    def test_site_manager_cannot_receive_project_finance_data(self):
        with self.assertRaisesRegex(ToolPermissionDenied, SAFE_DENIAL):
            run_read_tools(self.manager, "Donne les finances du projet")

    def test_superuser_can_receive_real_organization_statistics(self):
        result = self.result(self.superuser, "Combien d’organisations y a-t-il sur la plateforme ?")

        self.assertEqual(result.name, "platform.statistics")
        self.assertEqual(result.data["organization_count"], 2)
        self.assertEqual(result.data["active_organization_count"], 2)
        self.assertCountEqual(
            [row["name"] for row in result.data["organizations"]],
            [self.org.name, self.other_org.name],
        )

    def test_organization_statistics_are_denied_to_non_superusers(self):
        for user in (self.client_user, self.manager, self.engineer):
            with self.subTest(role=user.role):
                with self.assertRaisesRegex(ToolPermissionDenied, SAFE_DENIAL):
                    run_read_tools(user, "Combien d’organisations existe-t-il ?")

    def test_business_user_only_receives_current_organization_identity(self):
        for user in (self.client_user, self.manager, self.engineer):
            with self.subTest(role=user.role):
                result = self.result(user, "Quel est le nom de mon organisation ?")
                self.assertEqual(result.data["scope"], "current_organization")
                self.assertEqual(
                    [row["name"] for row in result.data["organizations"]],
                    [self.org.name],
                )
                self.assertNotIn(self.other_org.name, tool_context_json([result]))

    def test_organization_intent_tolerates_common_spelling_errors(self):
        for question in (
            "C’est quoi le nom de cette organisaton ?",
            "Quel est le nom de mon organisator ?",
            "What is my company name?",
        ):
            with self.subTest(question=question):
                result = self.result(self.client_user, question)
                self.assertEqual(result.name, "platform.statistics")
                self.assertEqual(result.data["organizations"][0]["name"], self.org.name)

    def test_superuser_can_list_names_and_roles_for_a_named_organization(self):
        result = self.result(
            self.superuser,
            f"Donne-moi le nom de tous les utilisateurs de l’organisation {self.org.name} "
            "et leurs rôles respectifs",
        )

        self.assertEqual(result.name, "users.directory")
        self.assertEqual(result.data["organization_count"], 1)
        self.assertEqual(result.data["user_count"], 4)
        self.assertTrue(result.data["users"])
        self.assertEqual({row["organization"] for row in result.data["users"]}, {self.org.name})
        self.assertIn("role_label", result.data["users"][0])
        self.assertNotIn(self.other_org.name, tool_context_json([result]))

    def test_organization_admin_directory_is_limited_to_own_organization(self):
        own = self.result(
            self.organization_admin, "Liste les utilisateurs de mon organisation et leurs rôles"
        )
        self.assertEqual(own.data["scope"], "current_organization")
        self.assertEqual({row["organization"] for row in own.data["users"]}, {self.org.name})

        with self.assertRaisesRegex(ToolPermissionDenied, SAFE_DENIAL):
            run_read_tools(
                self.organization_admin,
                f"Liste les utilisateurs de {self.other_org.name}",
            )

    def test_user_directory_is_denied_to_operational_roles(self):
        for user in (self.client_user, self.manager, self.engineer):
            with self.subTest(role=user.role):
                with self.assertRaisesRegex(ToolPermissionDenied, SAFE_DENIAL):
                    run_read_tools(user, "Liste tous les utilisateurs et leurs rôles")

    def test_domain_access_matrix_for_all_roles(self):
        roles = {
            "client": self.client_user,
            "site_manager": self.manager,
            "engineer": self.engineer,
            "admin": self.organization_admin,
            "superuser": self.superuser,
        }
        domains = {
            "platform": ("Quel est le nom de mon organisation ?", set(roles)),
            "users": (
                "Liste les utilisateurs et leurs rôles",
                {"admin", "superuser"},
            ),
            "projects": ("Liste les projets", set(roles)),
            "stages": ("Montre les étapes", set(roles)),
            "stock": ("Quel est le stock ?", set(roles)),
            "documents": ("Liste les documents", set(roles)),
            "photos": ("Montre les photos", set(roles)),
            "comments": ("Lis les commentaires", set(roles)),
            "finance": (
                "Donne les finances",
                {"client", "engineer", "admin", "superuser"},
            ),
            "report": ("Fais un rapport", set(roles)),
        }
        for domain, (question, allowed_roles) in domains.items():
            for role, user in roles.items():
                with self.subTest(domain=domain, role=role):
                    if role in allowed_roles:
                        self.assertTrue(run_read_tools(user, question))
                    else:
                        with self.assertRaises(ToolPermissionDenied):
                            run_read_tools(user, question)

    def test_every_business_tool_has_a_deterministic_answer(self):
        cases = (
            (self.superuser, "Liste les organisations"),
            (self.superuser, f"Utilisateurs de {self.org.name} et leurs rôles"),
            (self.engineer, "Liste les projets"),
            (self.engineer, "Montre les étapes"),
            (self.engineer, "Quel est le stock ?"),
            (self.engineer, "Liste les documents"),
            (self.engineer, "Montre les photos"),
            (self.engineer, "Lis les commentaires"),
            (self.engineer, "Donne les finances"),
            (self.engineer, "Fais un rapport"),
            (self.client_user, "Combien ai-je déjà payé ?"),
        )
        for user, question in cases:
            with self.subTest(question=question):
                answer = deterministic_tool_answer(run_read_tools(user, question))
                self.assertTrue(answer)
                self.assertNotIn("aucun résultat d’outil", answer.casefold())

    def test_client_report_excludes_global_financial_totals(self):
        row = self.result(self.client_user, "Fais un rapport du projet").data["projects"][0]

        self.assertEqual(row["own_successful_payments_xaf"], "100000")
        self.assertNotIn("paid_xaf", row)
        self.assertNotIn("withdrawn_xaf", row)
        self.assertEqual(row["progress_percent"], 100)

    def test_tools_do_not_modify_business_data(self):
        before = {
            "projects": Project.objects.count(),
            "stages": ProjectStage.objects.count(),
            "stock": StockItem.objects.count(),
            "documents": ProjectDocument.objects.count(),
            "payments": PaymentTransaction.objects.count(),
        }

        for question in ("mes projets", "étapes", "stock", "documents", "finances", "rapport"):
            run_read_tools(self.engineer, question)

        after = {
            "projects": Project.objects.count(),
            "stages": ProjectStage.objects.count(),
            "stock": StockItem.objects.count(),
            "documents": ProjectDocument.objects.count(),
            "payments": PaymentTransaction.objects.count(),
        }
        self.assertEqual(before, after)

    def test_subscription_tool_answers_current_plan_without_cross_tenant_leak(self):
        plan = SubscriptionPlan.objects.get(code="professional")
        now = timezone.now()
        OrganizationSubscription.objects.create(
            organization=self.org, plan=plan, status="trial",
            trial_started_at=now, trial_ends_at=now + timezone.timedelta(days=90),
        )
        OrganizationSubscription.objects.create(
            organization=self.other_org, plan=plan, status="trial",
            trial_started_at=now, trial_ends_at=now + timezone.timedelta(days=90),
        )
        results = run_read_tools(self.engineer, "Quel abonnement utilisons-nous présentement ?")
        answer = deterministic_tool_answer(results)
        self.assertIn("Professionnel", answer)
        self.assertIn(self.org.name, answer)
        self.assertNotIn(self.other_org.name, answer)
        client_answer = deterministic_tool_answer(
            run_read_tools(self.client_user, "Quel abonnement utilisons-nous ?")
        )
        self.assertIn("Professionnel", client_answer)
        self.assertNotIn(self.other_org.name, client_answer)
