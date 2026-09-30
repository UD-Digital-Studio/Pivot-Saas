from django.utils.translation import gettext_lazy as _
from django import forms

from apps.accounts.models import User

from .models import Project, ProjectMembership


def default_project_role(user):
    return {
        User.Role.CLIENT: ProjectMembership.Role.OWNER,
        User.Role.SITE_MANAGER: ProjectMembership.Role.SITE_MANAGER,
        User.Role.ENGINEER: ProjectMembership.Role.ENGINEER,
        User.Role.ADMIN: ProjectMembership.Role.PIVOT_REVIEWER,
    }[user.role]


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = (
            "name",
            "description",
            "location",
            "project_date",
            "budget_amount",
            "cover_image",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "project_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "budget_amount": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "cover_image": forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project_date"].input_formats = ["%Y-%m-%d"]


class ProjectCreateForm(ProjectForm):
    members = forms.ModelMultipleChoiceField(
        label=_("Clients et chefs de chantier"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
        help_text=_("Sélectionnez une ou plusieurs personnes à affecter dès la création."),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["members"].queryset = User.objects.filter(
                organization=organization,
                role__in=(User.Role.CLIENT, User.Role.SITE_MANAGER),
                is_active=True,
            ).order_by("role", "first_name", "last_name", "username")

    def save_members(self, project):
        memberships = []
        for user in self.cleaned_data["members"]:
            membership = ProjectMembership(
                organization=project.organization,
                project=project,
                user=user,
                project_role=default_project_role(user),
            )
            membership.full_clean()
            memberships.append(membership)
        return ProjectMembership.objects.bulk_create(memberships)


class ClientLedProjectForm(ProjectForm):
    financial_conditions = forms.CharField(
        label=_("Conditions financières initiales"),
        max_length=3000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Décrivez l'enveloppe, les modalités et les conditions initiales du chantier."),
    )


class ContractorLedProjectForm(ClientLedProjectForm):
    financial_conditions = forms.CharField(
        label=_("Conditions proposées au propriétaire"),
        max_length=3000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Ces conditions resteront préliminaires jusqu'à la confirmation du client."),
    )


class ContractorOnboardingConfirmationForm(forms.Form):
    confirm_project = forms.BooleanField(label=_("Je confirme le projet présenté."))
    confirm_ownership = forms.BooleanField(label=_("Je confirme être le propriétaire du chantier."))
    confirm_contractor = forms.BooleanField(label=_("Je confirme l'entrepreneur proposé."))
    confirm_conditions = forms.BooleanField(label=_("J'accepte les conditions initiales présentées."))


class ProjectTermsRevisionForm(forms.Form):
    budget_amount = forms.DecimalField(label=_("Budget"), min_value=0, decimal_places=0)
    currency = forms.ChoiceField(label=_("Devise"), choices=(("XAF", "XAF"), ("EUR", "EUR"), ("USD", "USD")))
    financial_conditions = forms.CharField(label=_("Conditions financières"), max_length=3000, widget=forms.Textarea(attrs={"rows": 4}))
    targeted_roles = forms.MultipleChoiceField(
        label=_("Nouvelles confirmations requises"),
        choices=(("contractor", "Entrepreneur"), ("engineer", "Ingénieur")),
        widget=forms.CheckboxSelectMultiple,
    )


class ProjectActorInvitationForm(forms.Form):
    email = forms.EmailField(label=_("Adresse e-mail"))
    role = forms.ChoiceField(
        label=_("Rôle dans le projet"),
        choices=(
            (User.Role.CLIENT, User.Role.CLIENT.label),
            (User.Role.CONTRACTOR, User.Role.CONTRACTOR.label),
            (User.Role.SITE_MANAGER, User.Role.SITE_MANAGER.label),
            (User.Role.ENGINEER, User.Role.ENGINEER.label),
        ),
    )

    def __init__(self, *args, allowed_roles=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_roles is not None:
            self.fields["role"].choices = [
                choice for choice in self.fields["role"].choices
                if choice[0] in set(allowed_roles)
            ]


class ProjectStatusForm(forms.Form):
    status = forms.ChoiceField(label=_("Nouveau statut"))

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = choices


class ProjectMembersForm(forms.Form):
    members = forms.ModelMultipleChoiceField(
        label=_("Membres affectés"),
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, project: Project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["members"].queryset = User.objects.filter(
            organization=project.organization,
            role__in=(User.Role.CLIENT, User.Role.SITE_MANAGER),
            is_active=True,
        ).order_by("role", "username")
        self.fields["members"].initial = project.memberships.values_list("user_id", flat=True)

    def save(self):
        selected_users = list(self.cleaned_data["members"])
        selected_ids = {user.pk for user in selected_users}
        editable_roles = {
            ProjectMembership.Role.OWNER,
            ProjectMembership.Role.SITE_MANAGER,
        }
        if selected_ids:
            self.project.memberships.filter(project_role__in=editable_roles).exclude(
                user_id__in=selected_ids
            ).delete()
        else:
            self.project.memberships.filter(project_role__in=editable_roles).delete()
        for user in selected_users:
            ProjectMembership.objects.update_or_create(
                project=self.project,
                user=user,
                defaults={
                    "organization": self.project.organization,
                    "project_role": default_project_role(user),
                },
            )
        return self.project.memberships.select_related("user")


class OwnershipConfirmationForm(forms.Form):
    terms_accepted = forms.BooleanField(
        label=_("Je confirme être le propriétaire du chantier et accepter les conditions applicables.")
    )


class ProjectOwnerChangeForm(forms.Form):
    new_owner = forms.ModelChoiceField(label=_("Nouveau propriétaire"), queryset=User.objects.none())
    reason = forms.CharField(label=_("Motif du changement"), max_length=500, widget=forms.Textarea)

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_owner"].queryset = User.objects.filter(
            organization=project.organization,
            role=User.Role.CLIENT,
            is_active=True,
        ).order_by("first_name", "last_name", "username")
