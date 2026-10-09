from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("incidents/", views.incident_list, name="incident_list"),
    path("incidents/create/", views.incident_create, name="incident_create"),
    path(
        "incidents/<int:incident_id>/",
        views.incident_detail,
        name="incident_detail",
    ),
    path(
        "incidents/<int:incident_id>/assign/",
        views.incident_assign_team,
        name="incident_assign_team",
    ),
    path(
        "incidents/<int:incident_id>/status/",
        views.incident_update_status,
        name="incident_update_status",
    ),
    path("teams/", views.team_list, name="team_list"),
]
