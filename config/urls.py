from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("super-admin/", include("apps.audit.superadmin_urls")),
    path("admin/", admin.site.urls),
    path("comptes/", include("apps.accounts.urls")),
    path("projets/", include("apps.projects.urls")),
    path("planification/", include("apps.planning.urls")),
    path("stock/", include("apps.inventory.urls")),
    path("collaboration/", include("apps.collaboration.urls")),
    path("finances/", include("apps.finance.urls")),
    path("rapports/", include("apps.reporting.urls")),
    path("assistant/", include("apps.ai_assistant.urls")),
    path("tarifs/", include("apps.subscriptions.urls")),
    path("", include("apps.core.urls")),
]

handler403 = "apps.core.error_views.permission_denied"
handler404 = "apps.core.error_views.page_not_found"
handler500 = "apps.core.error_views.server_error"
