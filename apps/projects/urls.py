from django.urls import path

from .views import (
    member_search,
    project_actor_invite,
    contractor_onboarding_confirm,
    actor_confirmation_respond,
    project_terms_revise,
    project_create,
    project_detail,
    project_list,
    project_members,
    project_onboarding_activate,
    project_owner_change,
    project_ownership_confirm,
    project_status_update,
    project_update,
)

app_name = "projects"

urlpatterns = [
    path("membres/rechercher/", member_search, name="member-search"),
    path("", project_list, name="list"),
    path("nouveau/", project_create, name="create"),
    path("<uuid:pk>/", project_detail, name="detail"),
    path("<uuid:pk>/modifier/", project_update, name="update"),
    path("<uuid:pk>/membres/", project_members, name="members"),
    path("<uuid:pk>/onboarding/inviter/", project_actor_invite, name="actor-invite"),
    path("<uuid:pk>/onboarding/confirmer-par-client/", contractor_onboarding_confirm, name="contractor-onboarding-confirm"),
    path("<uuid:pk>/participation/repondre/", actor_confirmation_respond, name="actor-confirmation-respond"),
    path("<uuid:pk>/conditions/nouvelle-version/", project_terms_revise, name="terms-revise"),
    path("<uuid:pk>/onboarding/activer/", project_onboarding_activate, name="onboarding-activate"),
    path("<uuid:pk>/ownership/confirmer/", project_ownership_confirm, name="ownership-confirm"),
    path("<uuid:pk>/ownership/changer/", project_owner_change, name="owner-change"),
    path("<uuid:pk>/statut/", project_status_update, name="status-update"),
]
