from django.urls import path

from planner.views import health

urlpatterns = [
    path("health/", health, name="health"),
]
