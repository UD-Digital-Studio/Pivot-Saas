from django.urls import path

from .views import (
    anomaly_resolution_decide,
    anomaly_resolution_propose,
    import_template,
    item_adjust,
    item_create,
    item_expected_range,
    item_verify,
    stock_export,
    stock_import,
)

app_name = "inventory"

urlpatterns = [
    path("projets/<uuid:project_pk>/anomalies/<uuid:pk>/resoudre/", anomaly_resolution_propose, name="anomaly-resolution-propose"),
    path("projets/<uuid:project_pk>/resolutions-anomalie/<uuid:pk>/decider/", anomaly_resolution_decide, name="anomaly-resolution-decide"),
    path("modele-import.csv", import_template, name="import-template"),
    path("projets/<uuid:project_pk>/articles/nouveau/", item_create, name="item-create"),
    path("projets/<uuid:project_pk>/articles/<uuid:pk>/ajuster/", item_adjust, name="item-adjust"),
    path("projets/<uuid:project_pk>/articles/<uuid:pk>/verifier/", item_verify, name="item-verify"),
    path("projets/<uuid:project_pk>/articles/<uuid:pk>/plage-attendue/", item_expected_range, name="item-expected-range"),
    path("projets/<uuid:project_pk>/importer/", stock_import, name="import"),
    path("projets/<uuid:project_pk>/historique.csv", stock_export, name="export"),
]
