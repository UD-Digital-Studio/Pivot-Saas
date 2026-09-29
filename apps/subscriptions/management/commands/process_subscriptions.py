from django.core.management.base import BaseCommand

from apps.subscriptions.services import (
    process_subscription_deadlines,
    process_subscription_notices,
    process_uncertain_subscription_payments,
)


class Command(BaseCommand):
    help = "Traite les échéances et changements programmés des abonnements."

    def handle(self, *args, **options):
        notices = process_subscription_notices()
        changed = process_subscription_deadlines()
        payments = process_uncertain_subscription_payments()
        self.stdout.write(self.style.SUCCESS(f"{changed} abonnement(s), {payments} paiement(s) et {notices} notification(s) traités."))
