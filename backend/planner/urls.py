from django.urls import path

from planner import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("geocode/", views.geocode, name="geocode"),
    path("plan/", views.plan, name="plan"),
    path("heatmap/", views.heatmap, name="heatmap"),
]
