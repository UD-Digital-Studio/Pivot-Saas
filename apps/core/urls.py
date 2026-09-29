from django.urls import path

from .views import health, home, private_health

app_name = "core"

urlpatterns = [
    path("", home, name="home"),
    path("health/", health, name="health"),
    path("health/private/", private_health, name="private-health"),
]
