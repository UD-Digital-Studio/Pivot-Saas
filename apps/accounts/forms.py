from uuid import uuid4

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.organizations.models import Organization

from .models import Invitation, User, UserProfile


class OrganizationAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _("Identifiant ou mot de passe incorrect."),
        "organization_inactive": _("Identifiant ou mot de passe incorrect."),
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if (
            not user.is_superuser
            and user.organization_id
            and user.organization.status != Organization.Status.ACTIVE
        ):
            raise ValidationError(
                self.error_messages["organization_inactive"],
                code="organization_inactive",
            )


class EngineerRegistrationForm(UserCreationForm):
    organization_name = forms.CharField(
        label=_("Nom de l'entreprise"),
        max_length=160,
        help_text=_("Cette entreprise constituera votre espace de travail isolé."),
    )
    email = forms.EmailField(label=_("Adresse e-mail"))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("organization_name", "username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = None
        self.fields["organization_name"].help_text = None
        self.fields["password1"].help_text = None
        self.fields["password2"].help_text = None

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_("Un compte utilise déjà cette adresse e-mail."))
        return email

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("L'inscription ingénieur doit être enregistrée atomiquement.")

        organization_name = self.cleaned_data["organization_name"].strip()
        base_slug = slugify(organization_name) or "organisation"
        slug = base_slug
        if Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{uuid4().hex[:8]}"

        organization = Organization.objects.create(name=organization_name, slug=slug)
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.organization = organization
        user.role = User.Role.ENGINEER
        user.is_active = False
        user.save()
        return user


class ClientRegistrationForm(UserCreationForm):
    email = forms.EmailField(label=_("Adresse e-mail"))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = None
        self.fields["password1"].help_text = None
        self.fields["password2"].help_text = None

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_("Un compte utilise déjà cette adresse e-mail."))
        return email

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("L'inscription client doit être enregistrée atomiquement.")
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.organization = None
        user.role = User.Role.CLIENT
        user.is_active = True
        user.save()
        return user


class MemberInvitationForm(forms.Form):
    email = forms.EmailField(label=_("Adresse e-mail"))
    role = forms.ChoiceField(
        label=_("Rôle"),
        choices=(
            (User.Role.CLIENT, User.Role.CLIENT.label),
            (User.Role.SITE_MANAGER, User.Role.SITE_MANAGER.label),
        ),
    )


class InvitationAcceptanceForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def __init__(self, *args, invitation: Invitation, **kwargs):
        super().__init__(*args, **kwargs)
        self.invitation = invitation

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("L'acceptation doit être enregistrée atomiquement.")

        invitation = Invitation.objects.select_for_update().get(pk=self.invitation.pk)
        if not invitation.is_usable:
            raise ValidationError(_("Cette invitation n'est plus valide."))
        if User.objects.filter(email__iexact=invitation.email).exists():
            raise ValidationError(_("Un compte utilise déjà cette adresse e-mail."))

        from apps.subscriptions.quotas import ensure_internal_member_capacity

        ensure_internal_member_capacity(
            invitation.organization,
            invitation.role,
            exclude_invitation=invitation,
        )
        user = super().save(commit=False)
        user.email = invitation.email
        user.organization = (
            None if invitation.role == User.Role.CLIENT else invitation.organization
        )
        user.role = invitation.role
        user.is_active = True
        user.save()
        from .services import _attach_invited_user

        _attach_invited_user(invitation=invitation, user=user)
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["accepted_at"])
        return user


class UserAccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {
            "username": "Nom d'utilisateur",
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Adresse e-mail",
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(_("Un autre compte utilise déjà cette adresse e-mail."))
        return email


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("phone", "location", "bio", "avatar")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
            "avatar": forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
        }
