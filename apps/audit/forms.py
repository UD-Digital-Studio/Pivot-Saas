from django.utils.translation import gettext_lazy as _
from django import forms
from django.contrib.auth import get_user_model
from apps.collaboration.models import EvidenceRecord

from .models import (
    PilotPricingHypothesis, PilotRecommendation, PilotReviewDecision, PlatformConfiguration,
)
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectConciergeFollowUp, ProjectMembership
from apps.projects.models import ProjectDispute, ProjectDisputeObservation


class PivotOnboardingForm(forms.ModelForm):
    organization = forms.ModelChoiceField(
        label=_("Organisation"), queryset=Organization.objects.order_by("name")
    )
    financial_conditions = forms.CharField(
        label=_("Conditions financières proposées"), max_length=3000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    owner_email = forms.EmailField(label=_("E-mail du propriétaire"), required=False)
    stage_title = forms.CharField(label=_("Premier jalon"), max_length=200)
    stage_start_date = forms.DateField(label=_("Début du jalon"), widget=forms.DateInput(attrs={"type": "date"}))
    stage_end_date = forms.DateField(label=_("Fin du jalon"), widget=forms.DateInput(attrs={"type": "date"}))
    stage_estimated_cost = forms.DecimalField(label=_("Budget du jalon"), min_value=0, decimal_places=0)
    document_title = forms.CharField(label=_("Titre du document"), max_length=200, required=False)
    document_file = forms.FileField(label=_("Document initial"), required=False)

    class Meta:
        model = Project
        fields = ("organization", "name", "description", "location", "project_date", "budget_amount")
        widgets = {
            "project_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        data = super().clean()
        if data.get("stage_start_date") and data.get("stage_end_date") and data["stage_end_date"] < data["stage_start_date"]:
            self.add_error("stage_end_date", "La fin du jalon doit suivre son début.")
        if bool(data.get("document_title")) != bool(data.get("document_file")):
            raise forms.ValidationError(_("Le titre et le fichier du document doivent être renseignés ensemble."))
        return data


class PivotProjectInvitationForm(forms.Form):
    email = forms.EmailField(label=_("Adresse e-mail"))
    role = forms.ChoiceField(
        label=_("Rôle"),
        choices=(
            ("client", "Client propriétaire"),
            ("contractor", "Entrepreneur"),
            ("engineer", "Ingénieur"),
            ("site_manager", "Responsable de chantier"),
        ),
    )


class PivotReviewerAssignmentForm(forms.Form):
    reviewer = forms.ModelChoiceField(
        label=_("Vérificateur PIVOT"),
        queryset=get_user_model().objects.none(),
        widget=forms.Select(attrs={"class": "h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm"}),
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reviewer"].queryset = get_user_model().objects.filter(
            is_active=True, is_superuser=True
        ).order_by("first_name", "last_name", "username")
        if project is not None:
            current = project.memberships.filter(
                project_role="pivot_reviewer"
            ).values_list("user_id", flat=True).first()
            self.fields["reviewer"].initial = current


class ProjectConciergeFollowUpForm(forms.ModelForm):
    class Meta:
        model = ProjectConciergeFollowUp
        fields = (
            "pivot_agent", "training_completed", "friction", "next_action",
            "next_action_due_at",
        )
        widgets = {
            "friction": forms.Textarea(attrs={"rows": 3}),
            "next_action": forms.Textarea(attrs={"rows": 3}),
            "next_action_due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pivot_agent"].queryset = get_user_model().objects.filter(
            is_superuser=True, is_active=True
        ).order_by("username")
        for name, field in self.fields.items():
            if name == "training_completed":
                field.widget.attrs.update({"class": "size-4 rounded border-slate-300"})
            else:
                field.widget.attrs.update({
                    "class": "mt-2 w-full rounded-xl border border-slate-300 bg-slate-50 px-3 py-2.5 text-sm dark:border-slate-700 dark:bg-slate-800"
                })


class ProjectDisputeForm(forms.Form):
    target = forms.ChoiceField(label=_("Objet contesté"))
    subject = forms.CharField(max_length=200)
    reason = forms.CharField(max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))
    freezes_decision = forms.BooleanField(required=False)
    evidence = forms.ModelMultipleChoiceField(
        queryset=EvidenceRecord.objects.none(), required=False,
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        choices = []
        for item in project.documents.order_by("title"):
            choices.append((f"document:{item.pk}", f"Document · {item.title}"))
        for item in project.expense_requests.order_by("-created_at"):
            choices.append((f"expense_request:{item.pk}", f"Dépense · {item.purpose}"))
        for item in project.evidence_records.order_by("-captured_at"):
            choices.append((f"evidence:{item.pk}", f"Preuve · {item.title}"))
        for item in project.inventory_anomalies.select_related("item"):
            choices.append((f"inventory_anomaly:{item.pk}", f"Anomalie · {item.item.name}"))
        self.fields["target"].choices = choices
        self.fields["evidence"].queryset = project.evidence_records.order_by("-captured_at")


class ProjectDisputeObservationForm(forms.Form):
    position = forms.ChoiceField(choices=ProjectDisputeObservation.Position.choices)
    body = forms.CharField(max_length=3000, widget=forms.Textarea(attrs={"rows": 2}))


class ProjectDisputeResolutionForm(forms.Form):
    resolution = forms.CharField(max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))


class PilotRecommendationForm(forms.ModelForm):
    class Meta:
        model = PilotRecommendation
        fields = ("organization", "respondent_role", "score", "note")
        labels = {
            "organization": "Organisation", "respondent_role": "Profil interrogé",
            "score": "Note de recommandation (0 à 10)", "note": "Commentaire",
        }
        widgets = {"score": forms.NumberInput(attrs={"min": 0, "max": 10})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.order_by("name")
        for field in self.fields.values():
            field.widget.attrs["class"] = "mt-1 h-11 w-full rounded-xl border border-slate-300 bg-slate-50 px-3 text-sm dark:border-slate-700 dark:bg-slate-800"


class PilotPricingHypothesisForm(forms.ModelForm):
    class Meta:
        model = PilotPricingHypothesis
        fields = (
            "segment", "plan", "proposed_monthly_price", "sample_size",
            "positive_responses", "status", "assumptions",
        )
        labels = {
            "segment": "Segment testé", "plan": "Forfait",
            "proposed_monthly_price": "Prix mensuel proposé (XAF)",
            "sample_size": "Nombre de réponses", "positive_responses": "Réponses positives",
            "status": "Décision", "assumptions": "Hypothèses et observations",
        }
        widgets = {"assumptions": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "mt-1 h-11 w-full rounded-xl border border-slate-300 bg-slate-50 px-3 text-sm dark:border-slate-700 dark:bg-slate-800"
        self.fields["assumptions"].widget.attrs["class"] += " h-24 py-3"


class PilotReviewDecisionForm(forms.ModelForm):
    class Meta:
        model = PilotReviewDecision
        fields = ("decision", "rationale", "product_decisions")
        labels = {
            "decision": "Décision", "rationale": "Justification factuelle",
            "product_decisions": "Décisions produit et prochaines actions",
        }
        widgets = {
            "rationale": forms.Textarea(attrs={"rows": 4}),
            "product_decisions": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "mt-1 w-full rounded-xl border border-slate-300 bg-slate-50 px-3 py-3 text-sm dark:border-slate-700 dark:bg-slate-800"


class OrganizationCreateForm(forms.Form):
    name = forms.CharField(label=_("Nom de l’organisation"), max_length=160)
    slug = forms.SlugField(label=_("Identifiant technique"), max_length=180)
    first_username = forms.CharField(label=_("Username du responsable"), max_length=150)
    first_email = forms.EmailField(label=_("E-mail du responsable"))
    first_name = forms.CharField(label=_("Prénom"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Nom"), max_length=150, required=False)
    first_role = forms.ChoiceField(
        label=_("Rôle initial"),
        choices=(("admin", "Administrateur"), ("engineer", "Ingénieur")),
    )

    def clean_name(self):
        value = self.cleaned_data["name"].strip()
        if Organization.objects.filter(name__iexact=value).exists():
            raise forms.ValidationError(_("Une organisation utilise déjà ce nom."))
        return value

    def clean_slug(self):
        value = self.cleaned_data["slug"].strip().lower()
        if Organization.objects.filter(slug__iexact=value).exists():
            raise forms.ValidationError(_("Cet identifiant est déjà utilisé."))
        return value

    def clean_first_username(self):
        value = self.cleaned_data["first_username"].strip()
        if get_user_model().objects.filter(username__iexact=value).exists():
            raise forms.ValidationError(_("Ce username est déjà utilisé."))
        return value

    def clean_first_email(self):
        value = self.cleaned_data["first_email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise forms.ValidationError(_("Cette adresse e-mail est déjà utilisée."))
        return value


class OrganizationUpdateForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ("name", "slug")

    def clean_name(self):
        value = self.cleaned_data["name"].strip()
        if Organization.objects.filter(name__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Une organisation utilise déjà ce nom."))
        return value

    def clean_slug(self):
        value = self.cleaned_data["slug"].strip().lower()
        if Organization.objects.filter(slug__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Cet identifiant est déjà utilisé."))
        return value


class PlatformUserCreateForm(forms.Form):
    organization = forms.ModelChoiceField(queryset=Organization.objects.none())
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    role = forms.ChoiceField(choices=get_user_model().Role.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.filter(
            status=Organization.Status.ACTIVE
        ).order_by("name")

    def clean_username(self):
        value = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=value).exists():
            raise forms.ValidationError(_("Ce username est déjà utilisé."))
        return value

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise forms.ValidationError(_("Cette adresse e-mail est déjà utilisée."))
        return value


class PlatformUserUpdateForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email", "role")

    def clean_username(self):
        value = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Ce username est déjà utilisé."))
        return value

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Cette adresse e-mail est déjà utilisée."))
        return value

    def clean_role(self):
        role = self.cleaned_data["role"]
        user = self.instance
        if user.is_superuser and role != user.role:
            raise forms.ValidationError(_("Le rôle d’un super-administrateur ne se modifie pas ici."))
        if user.managed_projects.exists() and role != get_user_model().Role.ENGINEER:
            raise forms.ValidationError(
                _("Cet utilisateur gère des projets et doit rester ingénieur avant leur réaffectation.")
            )
        membership_roles = set(user.project_memberships.values_list("project_role", flat=True))
        if membership_roles and membership_roles != {role}:
            raise forms.ValidationError(
                _("Le rôle est incompatible avec les affectations projet existantes.")
            )
        return role


class PlatformUserTransferForm(forms.Form):
    target_organization = forms.ModelChoiceField(queryset=Organization.objects.none())
    project_replacement = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(), required=False
    )
    membership_replacement = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(), required=False
    )
    reason = forms.CharField(max_length=500, widget=forms.Textarea)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["target_organization"].queryset = Organization.objects.filter(
            status=Organization.Status.ACTIVE
        ).exclude(pk=user.organization_id).order_by("name")
        self.fields["project_replacement"].queryset = get_user_model().objects.filter(
            organization_id=user.organization_id,
            role=get_user_model().Role.ENGINEER,
            is_active=True,
        ).exclude(pk=user.pk).order_by("username")
        self.fields["membership_replacement"].queryset = get_user_model().objects.filter(
            organization_id=user.organization_id,
            role=user.role,
            is_active=True,
        ).exclude(pk=user.pk).order_by("username")

    def clean(self):
        data = super().clean()
        if self.user.is_superuser or self.user.organization_id is None:
            raise forms.ValidationError(_("Un super-administrateur ne peut pas être transféré."))
        engineering_memberships = self.user.project_memberships.filter(
            project_role=ProjectMembership.Role.ENGINEER
        )
        if engineering_memberships.exists() and not data.get("project_replacement"):
            self.add_error(
                "project_replacement",
                "Choisissez l’ingénieur qui reprendra les projets gérés.",
            )
        other_memberships = self.user.project_memberships.exclude(
            project_role=ProjectMembership.Role.ENGINEER,
        )
        if other_memberships.exists() and not data.get("membership_replacement"):
            self.add_error(
                "membership_replacement",
                "Choisissez l’utilisateur qui reprendra les affectations projet.",
            )
        return data


class ProjectInterventionForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        label=_("Clients et responsables de chantier"),
        queryset=get_user_model().objects.none(),
        required=False,
    )
    engineers = forms.ModelMultipleChoiceField(
        label=_("Ingénieurs affectés"),
        queryset=get_user_model().objects.none(),
        required=False,
    )
    reason = forms.CharField(
        label=_("Motif obligatoire"), max_length=500, widget=forms.Textarea
    )

    class Meta:
        model = Project
        fields = (
            "name",
            "description",
            "location",
            "project_date",
            "budget_amount",
            "status",
            "engineer",
        )
        widgets = {"project_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization_id = self.instance.organization_id
        users = get_user_model().objects.filter(
            organization_id=organization_id, is_active=True
        )
        self.fields["engineer"].queryset = users.filter(
            role=get_user_model().Role.ENGINEER
        ).order_by("username")
        self.fields["engineer"].label = _("Ingénieur principal (ancienne donnée)")
        self.fields["engineers"].queryset = get_user_model().objects.filter(
            role=get_user_model().Role.ENGINEER,
            is_active=True,
        ).order_by("organization__name", "username")
        self.fields["members"].queryset = users.filter(
            role__in=(get_user_model().Role.CLIENT, get_user_model().Role.SITE_MANAGER)
        ).order_by("role", "username")
        if self.instance.pk and not self.is_bound:
            self.initial["members"] = self.instance.memberships.values_list("user_id", flat=True)
            self.initial["engineers"] = self.instance.memberships.filter(
                project_role=ProjectMembership.Role.ENGINEER
            ).values_list("user_id", flat=True)

    def clean_reason(self):
        value = self.cleaned_data["reason"].strip()
        if not value:
            raise forms.ValidationError(_("Le motif de l’intervention est obligatoire."))
        return value

    def clean_project_date(self):
        value = self.cleaned_data["project_date"]
        first_stage = self.instance.stages.order_by("start_date").first()
        if first_stage and value > first_stage.start_date:
            raise forms.ValidationError(
                _("La date du projet ne peut pas être postérieure au début de la première étape.")
            )
        return value

class PlatformConfigurationForm(forms.ModelForm):
    class Meta:
        model = PlatformConfiguration
        fields = (
            "platform_name",
            "support_email",
            "engineer_registration_enabled",
            "client_registration_enabled",
            "platform_notice",
            "notification_retention_days",
            "evidence_download_requires_approval",
            "evidence_location_restricted",
        )

    def clean_platform_name(self):
        value = self.cleaned_data["platform_name"].strip()
        if not value:
            raise forms.ValidationError(_("Le nom de la plateforme est obligatoire."))
        return value

    def clean_platform_notice(self):
        return self.cleaned_data["platform_notice"].strip()


class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        from apps.subscriptions.models import SubscriptionPlan

        model = SubscriptionPlan
        fields = (
            "name", "code", "description", "monthly_price", "yearly_price", "currency",
            "max_active_projects", "max_internal_members", "storage_limit_mb",
            "advanced_reports_enabled", "ai_assistant_enabled", "is_active", "is_public",
            "display_order",
        )


class SubscriptionInterventionForm(forms.Form):
    ACTIONS = (
        ("extend", "Accorder une prolongation"),
        ("change_plan", "Changer immédiatement le forfait"),
        ("suspend", "Suspendre l’organisation"),
        ("reactivate", "Réactiver l’organisation"),
    )
    action = forms.ChoiceField(choices=ACTIONS)
    plan = forms.ModelChoiceField(queryset=Organization.objects.none(), required=False)
    extension_days = forms.IntegerField(min_value=1, max_value=730, required=False)
    reason = forms.CharField(max_length=500, widget=forms.Textarea)
    expected_updated_at = forms.CharField()

    def __init__(self, *args, **kwargs):
        from apps.subscriptions.models import SubscriptionPlan

        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = SubscriptionPlan.objects.filter(is_active=True).order_by("display_order", "name")

    def clean(self):
        data = super().clean()
        if data.get("action") == "change_plan" and not data.get("plan"):
            self.add_error("plan", "Choisissez le nouveau forfait.")
        if data.get("action") == "extend" and not data.get("extension_days"):
            self.add_error("extension_days", "Indiquez la durée de prolongation.")
        if not (data.get("reason") or "").strip():
            self.add_error("reason", "Le motif est obligatoire.")
        return data
