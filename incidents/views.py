from django.contrib import messages
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import IncidentForm
from .models import Incident, IncidentSource, Location, Team
from .services.assignment import (
    assign_team_to_incident,
    find_suitable_team,
    release_team_from_incident,
)
from .services.incident_service import create_incident
from .services.monitoring_channels import monitoring_channel
from .services.briefing import incident_briefing
from .services.workflow import update_incident_status


def ordered_incidents():
    return (
        Incident.objects.select_related(
            "source", "location", "assigned_team", "possible_duplicate_of"
        )
        .annotate(
            priority_order=Case(
                When(priority_level=Incident.PriorityLevel.CRITICAL, then=Value(4)),
                When(priority_level=Incident.PriorityLevel.HIGH, then=Value(3)),
                When(priority_level=Incident.PriorityLevel.MEDIUM, then=Value(2)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("-priority_order", "-created_at")
    )


def dashboard_counts():
    active = Incident.objects.exclude(status=Incident.Status.RESOLVED)
    return {
        "critical_count": active.filter(
            priority_level=Incident.PriorityLevel.CRITICAL
        ).count(),
        "high_count": active.filter(
            priority_level=Incident.PriorityLevel.HIGH
        ).count(),
        "active_count": active.count(),
        "resolved_today_count": Incident.objects.filter(
            status=Incident.Status.RESOLVED,
            updated_at__date=timezone.localdate(),
        ).count(),
        "available_team_count": Team.objects.filter(
            status=Team.Status.AVAILABLE
        ).count(),
    }


def dashboard(request):
    return render(
        request,
        "dashboard.html",
        {
            "incidents": ordered_incidents(),
            "priority_choices": Incident.PriorityLevel.choices,
            **dashboard_counts(),
        },
    )


@require_GET
def dashboard_data(request):
    """Small read-only endpoint for the operations dashboard polling."""
    incidents = []
    for incident in ordered_incidents():
        local_created = timezone.localtime(incident.created_at)
        incidents.append(
            {
                "id": incident.pk,
                "title": incident.title,
                "type": incident.get_incident_type_display(),
                "module": monitoring_channel(incident),
                "location": str(incident.location),
                "priority": incident.priority_level,
                "priority_label": incident.get_priority_level_display(),
                "status": incident.status,
                "status_label": incident.get_status_display(),
                "team": (
                    incident.assigned_team.name
                    if incident.assigned_team_id else "No team yet"
                ),
                "created_time": local_created.strftime("%H:%M"),
                "created_at": local_created.isoformat(),
                "duplicate_of": incident.possible_duplicate_of_id,
                "url": redirect("incident_detail", incident_id=incident.pk).url,
            }
        )
    return JsonResponse({"counts": dashboard_counts(), "incidents": incidents})


def incident_list(request):
    incidents = ordered_incidents()
    priority = request.GET.get("priority", "")
    status = request.GET.get("status", "")
    incident_type = request.GET.get("type", "")
    location = request.GET.get("location", "")
    search = request.GET.get("q", "").strip()

    if priority:
        incidents = incidents.filter(priority_level=priority)
    if status:
        incidents = incidents.filter(status=status)
    if incident_type:
        incidents = incidents.filter(incident_type=incident_type)
    if location:
        incidents = (
            incidents.filter(location_id=int(location))
            if location.isdigit() else incidents.none()
        )
    if search:
        query = Q(title__icontains=search)
        if search.isdigit():
            query |= Q(pk=int(search))
        incidents = incidents.filter(query)

    return render(request, "incidents/incident_list.html", {
        "incidents": incidents,
        "incident_types": Incident.IncidentType.choices,
        "locations": Location.objects.all().order_by("name"),
    })


def incident_detail(request, incident_id):
    incident = get_object_or_404(
        Incident.objects.select_related(
            "source", "location", "assigned_team", "possible_duplicate_of"
        ),
        pk=incident_id,
    )
    suggested_team = None
    if incident.status == Incident.Status.NEW and incident.assigned_team_id is None:
        suggested_team = find_suitable_team(incident)
    return render(request, "incidents/incident_detail.html", {
        "incident": incident,
        "briefing": incident_briefing(incident),
        "suggested_team": suggested_team,
    })


def incident_create(request):
    if request.method == "POST":
        form = IncidentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            manual_source, _ = IncidentSource.objects.get_or_create(
                name="Manual Report",
                defaults={"source_type": IncidentSource.SourceType.STAFF},
            )
            incident = create_incident(
                title=data["title"],
                description=data["description"],
                incident_type=data["incident_type"],
                source=manual_source,
                location=data["location"],
                severity=data["severity"],
                people_affected=data["people_affected"],
            )
            messages.success(request, f"Incident #{incident.pk} created successfully.")
            return redirect("incident_detail", incident_id=incident.pk)
    else:
        form = IncidentForm()
    return render(request, "incidents/incident_form.html", {"form": form})


def team_list(request):
    teams = Team.objects.select_related("current_location").prefetch_related(
        "assigned_incidents"
    )
    return render(request, "teams/team_list.html", {
        "teams": teams,
        "available_team_count": Team.objects.filter(
            status=Team.Status.AVAILABLE
        ).count(),
    })


@require_POST
def incident_assign_team(request, incident_id):
    incident = get_object_or_404(Incident, pk=incident_id)
    if incident.status != Incident.Status.NEW:
        messages.error(request, "Only new incidents can receive an initial assignment.")
        return redirect("incident_detail", incident_id=incident_id)
    try:
        team = assign_team_to_incident(incident)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("incident_detail", incident_id=incident_id)
    if team is None:
        messages.warning(request, "No suitable team is available.")
    else:
        messages.success(request, f"{team.name} assigned successfully.")
    return redirect("incident_detail", incident_id=incident_id)


@require_POST
def incident_update_status(request, incident_id):
    incident = get_object_or_404(Incident, pk=incident_id)
    if incident.status == Incident.Status.ASSIGNED:
        if incident.assigned_team_id is None:
            messages.error(request, "Assign a team first.")
        else:
            update_incident_status(incident, Incident.Status.IN_PROGRESS)
            messages.success(request, "Incident is now in progress.")
    elif incident.status == Incident.Status.IN_PROGRESS:
        release_team_from_incident(incident)
        messages.success(request, "Incident resolved and team released.")
    else:
        messages.error(request, "No valid next status transition.")
    return redirect("incident_detail", incident_id=incident_id)
