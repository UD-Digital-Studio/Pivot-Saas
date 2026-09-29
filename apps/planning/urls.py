from django.urls import path

from .views import calendar_events, calendar_view, stage_create, stage_update, stage_progress_declare, stage_progress_verify, stage_progress_review, stage_progress_digital_verify, stage_site_visit_create, stage_site_verification_create, inspection_risk_rule_create, stage_inspection_risk_evaluate, stages_export_csv

app_name = "planning"

urlpatterns = [
    path("calendrier/", calendar_view, name="calendar"),
    path("calendrier/evenements/", calendar_events, name="calendar-events"),
    path("projets/<uuid:project_pk>/etapes/nouvelle/", stage_create, name="stage-create"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/modifier/", stage_update, name="stage-update"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/progression/declarer/", stage_progress_declare, name="stage-progress-declare"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/progression/verifier/", stage_progress_verify, name="stage-progress-verify"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/progression/<uuid:declaration_pk>/avis/", stage_progress_review, name="stage-progress-review"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/progression/<uuid:declaration_pk>/digital-verified/", stage_progress_digital_verify, name="stage-progress-digital-verify"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/visites/nouvelle/", stage_site_visit_create, name="stage-site-visit-create"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/visites/<uuid:visit_pk>/conclure/", stage_site_verification_create, name="stage-site-verification-create"),
    path("projets/<uuid:project_pk>/risques/regles/nouvelle/", inspection_risk_rule_create, name="inspection-risk-rule-create"),
    path("projets/<uuid:project_pk>/etapes/<uuid:pk>/risques/evaluer/", stage_inspection_risk_evaluate, name="stage-inspection-risk-evaluate"),
    path("projets/<uuid:project_pk>/etapes/export.csv", stages_export_csv, name="stages-export"),
]
