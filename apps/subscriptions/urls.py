from django.urls import path

from .views import billing, pay, pricing, receipt, reconcile

app_name = "subscriptions"

urlpatterns = [
    path("", pricing, name="pricing"),
    path("payer/", pay, name="pay"),
    path("paiements/<uuid:pk>/verifier/", reconcile, name="reconcile"),
    path("facturation/", billing, name="billing"),
    path("facturation/recu/<uuid:pk>/", receipt, name="receipt"),
]
