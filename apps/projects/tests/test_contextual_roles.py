from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization
from apps.accounts.services import create_invitation
from apps.projects.access import has_project_role, project_engineers, projects_visible_to
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import can_manage_project


class ContextualProjectRoleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.org = Organization.objects.create(name="PIVOT A", slug="pivot-a")
        self.other_org = Organization.objects.create(name="PIVOT B", slug="pivot-b")
        self.engineer = User.objects.create_user(
            username="context-engineer", organization=self.org, role=User.Role.ENGINEER
        )
        self.member = User.objects.create_user(
            username="context-member", organization=self.org, role=User.Role.CLIENT
        )
        self.foreign = User.objects.create_user(
            username="foreign-member", organization=self.other_org, role=User.Role.CLIENT
        )
        self.project_a = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Projet A",
            location="Douala",
            project_date=date.today(),
        )
        self.project_b = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Projet B",
            location="Yaoundé",
            project_date=date.today(),
        )

    def assign(self, project, user, role):
        return ProjectMembership.objects.update_or_create(
            organization=self.org,
            project=project,
            user=user,
            defaults={"project_role": role},
        )[0]

    def test_one_account_can_have_different_roles_per_project(self):
        self.assign(self.project_a, self.member, ProjectMembership.Role.OWNER)
        self.assign(self.project_b, self.member, ProjectMembership.Role.CONTRACTOR)

        self.assertTrue(
            has_project_role(
                user=self.member,
                project=self.project_a,
                roles={ProjectMembership.Role.OWNER},
            )
        )
        self.assertFalse(can_manage_project(actor=self.member, project=self.project_b))
        self.assertEqual(projects_visible_to(self.member).count(), 2)

    def test_global_client_can_invite_as_contextual_project_engineer(self):
        self.assign(self.project_a, self.member, ProjectMembership.Role.OWNER)
        self.assign(self.project_b, self.member, ProjectMembership.Role.ENGINEER)

        invitation, _ = create_invitation(
            actor=self.member,
            email="nouveau-responsable@example.com",
            role=get_user_model().Role.SITE_MANAGER,
            project=self.project_b,
            project_role=ProjectMembership.Role.SITE_MANAGER,
        )

        self.assertEqual(invitation.project, self.project_b)
        self.assertEqual(invitation.project_role, ProjectMembership.Role.SITE_MANAGER)

        self.client.force_login(self.member)
        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project_b.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["actor_invitation_form"])
        self.assertContains(response, "Inviter un intervenant")

    def test_external_member_sees_only_the_project_explicitly_shared_with_them(self):
        membership = ProjectMembership(
            organization=self.org,
            project=self.project_a,
            user=self.foreign,
            project_role=ProjectMembership.Role.ENGINEER,
        )
        membership.full_clean()
        membership.save()
        self.assertTrue(
            has_project_role(
                user=self.foreign,
                project=self.project_a,
                roles={ProjectMembership.Role.ENGINEER},
            )
        )
        self.assertEqual(list(projects_visible_to(self.foreign)), [self.project_a])
        self.assertNotIn(self.project_b, projects_visible_to(self.foreign))

    def test_independent_client_can_access_projects_from_multiple_organizations(self):
        client = get_user_model().objects.create_user(
            username="independent-owner", role=get_user_model().Role.CLIENT
        )
        other_project = Project.objects.create(
            organization=self.other_org,
            name="Projet externe",
            location="Bafoussam",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.org,
            project=self.project_a,
            user=client,
            project_role=ProjectMembership.Role.OWNER,
        )
        ProjectMembership.objects.create(
            organization=self.other_org,
            project=other_project,
            user=client,
            project_role=ProjectMembership.Role.OWNER,
        )

        self.assertIsNone(client.organization)
        self.assertEqual(
            set(projects_visible_to(client)),
            {self.project_a, other_project},
        )

    def test_sensitive_management_matrix(self):
        expected = {
            ProjectMembership.Role.OWNER: False,
            ProjectMembership.Role.CONTRACTOR: False,
            ProjectMembership.Role.SITE_MANAGER: False,
            ProjectMembership.Role.ENGINEER: True,
            ProjectMembership.Role.PIVOT_REVIEWER: False,
        }
        for role, allowed in expected.items():
            with self.subTest(role=role):
                self.assign(self.project_a, self.member, role)
                self.assertEqual(
                    can_manage_project(actor=self.member, project=self.project_a), allowed
                )

    def test_project_creation_registers_responsible_engineer_membership(self):
        self.assertTrue(
            self.project_a.memberships.filter(
                user=self.engineer, project_role=ProjectMembership.Role.ENGINEER
            ).exists()
        )

    def test_legacy_engineer_field_no_longer_grants_access_by_itself(self):
        self.project_a.memberships.filter(user=self.engineer).delete()

        self.assertEqual(self.project_a.engineer, self.engineer)
        self.assertFalse(can_manage_project(actor=self.engineer, project=self.project_a))
        self.assertNotIn(self.project_a, projects_visible_to(self.engineer))

    def test_project_can_have_multiple_contextual_engineers(self):
        second_engineer = get_user_model().objects.create_user(
            username="second-context-engineer",
            organization=self.other_org,
            role=get_user_model().Role.ENGINEER,
        )
        self.assign(self.project_a, second_engineer, ProjectMembership.Role.ENGINEER)

        self.assertEqual(
            set(project_engineers(self.project_a)),
            {self.engineer, second_engineer},
        )
        self.assertTrue(can_manage_project(actor=second_engineer, project=self.project_a))
