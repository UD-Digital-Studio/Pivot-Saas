from django.urls import path

from . import views

app_name = "finance"
urlpatterns = [
    path("projets/<uuid:project_pk>/demandes-depense/nouvelle/", views.expense_create, name="expense-create"),
    path("projets/<uuid:project_pk>/demandes-depense/<uuid:pk>/transition/", views.expense_transition, name="expense-transition"),
    path("projets/<uuid:project_pk>/demandes-depense/<uuid:pk>/pieces/ajouter/", views.expense_attachment_add, name="expense-attachment-add"),
    path("projets/<uuid:project_pk>/demandes-depense/pieces/<uuid:pk>/rejeter/", views.expense_attachment_reject, name="expense-attachment-reject"),
    path("projets/<uuid:project_pk>/demandes-depense/pieces/<uuid:pk>/remplacer/", views.expense_attachment_replace, name="expense-attachment-replace"),
    path("projets/<uuid:project_pk>/demandes-depense/<uuid:pk>/avis-technique/", views.expense_technical_opinion, name="expense-technical-opinion"),
    path("projets/<uuid:project_pk>/demandes-depense/<uuid:pk>/verification-pivot/", views.expense_pivot_verification, name="expense-pivot-verification"),
    path("projets/<uuid:project_pk>/demandes-depense/<uuid:pk>/decision-proprietaire/", views.expense_owner_decision, name="expense-owner-decision"),
    path("projets/<uuid:project_pk>/demandes-depense/<uuid:pk>/payer/", views.expense_pay, name="expense-pay"),
    path("projets/<uuid:project_pk>/payer/", views.pay, name="pay"),
    path(
        "projets/<uuid:project_pk>/paiements/<uuid:pk>/actualiser/",
        views.payment_refresh,
        name="payment-refresh",
    ),
    path("projets/<uuid:project_pk>/retraits/nouveau/", views.withdraw, name="withdraw"),
    path(
        "projets/<uuid:project_pk>/retraits/<uuid:pk>/decider/",
        views.withdrawal_decide,
        name="withdrawal-decide",
    ),
    path("projets/<uuid:project_pk>/export.csv", views.export, name="export"),
]
