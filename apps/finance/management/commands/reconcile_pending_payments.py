from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.finance.models import PaymentTransaction
from apps.finance.services import expire_stale_payment, reconcile_payment


class Command(BaseCommand):
    help = "Rapproche automatiquement les paiements MeSomb en attente."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        limit = max(1, min(options["limit"], 1000))
        stale_cutoff = timezone.now() - timedelta(
            minutes=settings.PAYMENT_PENDING_TTL_MINUTES
        )
        stale_ids = list(
            PaymentTransaction.objects.filter(
                status=PaymentTransaction.Status.PENDING,
                provider_reference="",
                operator_reference="",
                requested_at__lt=stale_cutoff,
            ).values_list("pk", flat=True)[:limit]
        )
        for payment_id in stale_ids:
            payment = PaymentTransaction.objects.select_related("user").get(pk=payment_id)
            expire_stale_payment(
                actor=payment.user,
                transaction_id=payment_id,
                reason="Délai maximal d'attente dépassé sans référence MeSomb.",
            )
        payment_ids = list(
            PaymentTransaction.objects.filter(
                status=PaymentTransaction.Status.PENDING,
                provider="mesomb",
            )
            .order_by("requested_at")
            .values_list("pk", flat=True)[:limit]
        )
        changed = 0
        expired_after_check = 0
        for payment_id in payment_ids:
            payment = PaymentTransaction.objects.select_related("user").get(pk=payment_id)
            payment, was_changed = reconcile_payment(actor=payment.user, transaction_id=payment_id)
            changed += int(was_changed)
            if (
                payment.status == PaymentTransaction.Status.PENDING
                and payment.requested_at < stale_cutoff
            ):
                _, expired = expire_stale_payment(
                    actor=payment.user,
                    transaction_id=payment.pk,
                    reason="Délai maximal de paiement en attente dépassé après vérification MeSomb.",
                    provider_checked=True,
                )
                expired_after_check += int(expired)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(stale_ids) + expired_after_check} paiement(s) expiré(s), "
                f"{len(payment_ids)} paiement(s) vérifié(s), "
                f"{changed} statut(s) rapproché(s)."
            )
        )
