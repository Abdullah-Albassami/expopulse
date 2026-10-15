from django.urls import path
from . import views, views_equipment, views_live

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/data/", views.dashboard_data, name="dashboard_data"),
    path("incidents/", views.incident_list, name="incident_list"),
    path("incidents/manage/", views.manage_incidents, name="manage_incidents"),
    path("incidents/create/", views.incident_create, name="incident_create"),
    path("incidents/<int:incident_id>/", views.incident_detail, name="incident_detail"),
    path("incidents/<int:incident_id>/assign/", views.incident_assign_team, name="incident_assign_team"),
    path("incidents/<int:incident_id>/status/", views.incident_update_status, name="incident_update_status"),
    path("teams/", views.team_list, name="team_list"),
    path("live/", views_live.live_cameras, name="live_cameras"),
    path("live/status/", views_live.live_status, name="live_status"),
    path("live/<str:camera>/<str:filename>", views_live.live_stream_file, name="live_stream_file"),
    path("api/equipment/readings/", views_equipment.equipment_reading, name="equipment_reading"),
]
