from django.urls import path

from .views import center, project_csv, project_pdf, stage_verification_pdf

app_name = "reporting"
urlpatterns = [
    path("", center, name="center"),
    path("projets/<uuid:pk>/pdf/", project_pdf, name="pdf"),
    path("projets/<uuid:pk>/csv/", project_csv, name="csv"),
    path("projets/<uuid:project_pk>/etapes/<uuid:stage_pk>/verification.pdf", stage_verification_pdf, name="stage-verification-pdf"),
]
