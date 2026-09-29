from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import AuditEvent


def _record_auth_event(user, action):
    if user is None or not user.pk:
        return
    AuditEvent.objects.create(
        organization=user.organization,
        actor=user,
        action=action,
        target_type="user",
        target_id=str(user.pk),
        metadata={},
    )


@receiver(user_logged_in, dispatch_uid="audit_user_logged_in")
def record_login(sender, request, user, **kwargs):
    _record_auth_event(user, "account.login")


@receiver(user_logged_out, dispatch_uid="audit_user_logged_out")
def record_logout(sender, request, user, **kwargs):
    _record_auth_event(user, "account.logout")
