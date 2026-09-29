from django.urls import path

from . import views

app_name = "collaboration"
urlpatterns = [
    path("projets/<uuid:project_pk>/preuves/ajouter/", views.evidence_create, name="evidence-create"),
    path("projets/<uuid:project_pk>/preuves/<uuid:pk>/fichier/", views.evidence_file, name="evidence-file"),
    path("projets/<uuid:project_pk>/preuves/<uuid:pk>/apercu/", views.evidence_preview, name="evidence-preview"),
    path("projets/<uuid:project_pk>/preuves/<uuid:pk>/telecharger/", views.evidence_download, name="evidence-download"),
    path("projets/<uuid:project_pk>/preuves/<uuid:pk>/corriger/", views.evidence_correct, name="evidence-correct"),
    path("projets/<uuid:project_pk>/preuves/<uuid:pk>/examiner/", views.evidence_review, name="evidence-review"),
    path(
        "projets/<uuid:project_pk>/documents/deposer/",
        views.document_upload,
        name="document-upload",
    ),
    path(
        "projets/<uuid:project_pk>/documents/<uuid:pk>/telecharger/",
        views.document_download,
        name="document-download",
    ),
    path(
        "projets/<uuid:project_pk>/documents/<uuid:pk>/apercu/",
        views.document_preview,
        name="document-preview",
    ),
    path(
        "projets/<uuid:project_pk>/documents/<uuid:pk>/examiner/",
        views.document_review,
        name="document-review",
    ),
    path("projets/<uuid:project_pk>/photos/ajouter/", views.image_upload, name="image-upload"),
    path(
        "projets/<uuid:project_pk>/photos/<uuid:pk>/voir/",
        views.image_download,
        name="image-download",
    ),
    path(
        "projets/<uuid:project_pk>/photos/<uuid:pk>/couverture/",
        views.image_cover,
        name="image-cover",
    ),
    path(
        "projets/<uuid:project_pk>/photos/<uuid:pk>/supprimer/",
        views.image_delete,
        name="image-delete",
    ),
    path(
        "projets/<uuid:project_pk>/commentaires/ajouter/",
        views.comment_create,
        name="comment-create",
    ),
    path(
        "projets/<uuid:project_pk>/commentaires/<uuid:pk>/modifier/",
        views.comment_update,
        name="comment-update",
    ),
    path(
        "projets/<uuid:project_pk>/commentaires/<uuid:pk>/supprimer/",
        views.comment_delete,
        name="comment-delete",
    ),
]
