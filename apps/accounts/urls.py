from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import path, reverse_lazy

from .forms import OrganizationAuthenticationForm
from .views import (
    ClientRegistrationView,
    EngineerRegistrationView,
    RegistrationPendingView,
    accept_invitation,
    cancel_invitation,
    dashboard,
    invite_member,
    notification_center,
    notification_read,
    notifications_read_all,
    post_login,
    profile,
)

app_name = "accounts"

urlpatterns = [
    path(
        "mot-de-passe/oublie/",
        PasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/password_reset_email.txt",
            html_email_template_name="emails/password_reset.html",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password-reset-done"),
        ),
        name="password-reset",
    ),
    path(
        "mot-de-passe/message-envoye/",
        PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password-reset-done",
    ),
    path(
        "mot-de-passe/confirmer/<uidb64>/<token>/",
        PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password-reset-complete"),
        ),
        name="password-reset-confirm",
    ),
    path(
        "mot-de-passe/termine/",
        PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"),
        name="password-reset-complete",
    ),
    path("profil/", profile, name="profile"),
    path("notifications/", notification_center, name="notifications"),
    path("notifications/<int:pk>/lire/", notification_read, name="notification-read"),
    path("notifications/tout-lire/", notifications_read_all, name="notifications-read-all"),
    path("inviter/", invite_member, name="invite-member"),
    path("invitation/<int:pk>/annuler/", cancel_invitation, name="cancel-invitation"),
    path("invitation/<str:token>/", accept_invitation, name="accept-invitation"),
    path(
        "inscription/ingenieur/",
        EngineerRegistrationView.as_view(),
        name="engineer-registration",
    ),
    path(
        "inscription/client/",
        ClientRegistrationView.as_view(),
        name="client-registration",
    ),
    path(
        "inscription/en-attente/",
        RegistrationPendingView.as_view(),
        name="registration-pending",
    ),
    path(
        "connexion/",
        LoginView.as_view(
            authentication_form=OrganizationAuthenticationForm,
            template_name="accounts/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("deconnexion/", LogoutView.as_view(), name="logout"),
    path("apres-connexion/", post_login, name="post-login"),
    path("tableau-de-bord/<str:role>/", dashboard, name="dashboard"),
]
