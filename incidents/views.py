from datetime import timedelta

from django.contrib import messages
from django.db.models import Q, Case, When, Value, IntegerField
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import IncidentForm
from .models import Incident, Location, Team
from .services.assignment import (
    assign_team_to_incident,
    find_suitable_team,
    release_team_from_incident,
)
from .services.incident_service import create_incident
from .services.workflow import update_incident_status


def ordered_incidents():
    return (
        Incident.objects.select_related(
            "source",
            "location",
            "assigned_team",
            "possible_duplicate_of",
        )
        .annotate(
            priority_order=Case(
                When(priority_level="critical", then=Value(4)),
                When(priority_level="high", then=Value(3)),
                When(priority_level="medium", then=Value(2)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("-priority_order", "-created_at")
    )


def dashboard(request):
    incidents = ordered_incidents()
    active = Incident.objects.exclude(
        status=Incident.Status.RESOLVED
    )
    today = timezone.localdate()

    context = {
        "incidents": incidents,
        "priority_choices": Incident.PriorityLevel.choices,
        "critical_count": active.filter(
            priority_level=Incident.PriorityLevel.CRITICAL
        ).count(),
        "high_count": active.filter(
            priority_level=Incident.PriorityLevel.HIGH
        ).count(),
        "active_count": active.count(),
        "resolved_today_count": Incident.objects.filter(
            status=Incident.Status.RESOLVED,
            updated_at__date=today,
        ).count(),
        "available_team_count": Team.objects.filter(
            status=Team.Status.AVAILABLE
        ).count(),
    }
    return render(request, "dashboard.html", context)


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
        if location.isdigit():
            incidents = incidents.filter(location_id=int(location))
        else:
            incidents = incidents.none()

    if search:
        query = Q(title__icontains=search)
        if search.isdigit():
            query |= Q(pk=int(search))
        incidents = incidents.filter(query)

    return render(
        request,
        "incidents/incident_list.html",
        {
            "incidents": incidents,
            "incident_types": Incident.IncidentType.choices,
            "locations": Location.objects.all().order_by("name"),
        },
    )


def incident_detail(request, incident_id):
    incident = get_object_or_404(
        Incident.objects.select_related(
            "source",
            "location",
            "assigned_team",
            "possible_duplicate_of",
        ),
        pk=incident_id,
    )

    suggested_team = None
    if (
        incident.status == Incident.Status.NEW
        and incident.assigned_team_id is None
    ):
        suggested_team = find_suitable_team(incident)

    return render(
        request,
        "incidents/incident_detail.html",
        {
            "incident": incident,
            "suggested_team": suggested_team,
        },
    )


def incident_create(request):
    if request.method == "POST":
        form = IncidentForm(request.POST)

        if form.is_valid():
            data = form.cleaned_data

            incident = create_incident(
                title=data["title"],
                description=data["description"],
                incident_type=data["incident_type"],
                source=data["source"],
                location=data["location"],
                severity=data["severity"],
                people_affected=data["people_affected"],
            )

            messages.success(
                request,
                f"Incident #{incident.pk} created successfully.",
            )
            return redirect("incident_detail", incident_id=incident.pk)
    else:
        form = IncidentForm()

    return render(
        request,
        "incidents/incident_form.html",
        {"form": form},
    )


def team_list(request):
    teams = Team.objects.select_related(
        "current_location"
    ).prefetch_related("assigned_incidents")

    return render(
        request,
        "teams/team_list.html",
        {
            "teams": teams,
            "available_team_count": Team.objects.filter(
                status=Team.Status.AVAILABLE
            ).count(),
        },
    )


@require_POST
def incident_assign_team(request, incident_id):
    incident = get_object_or_404(Incident, pk=incident_id)

    if incident.status != Incident.Status.NEW:
        messages.error(
            request,
            "Only new incidents can receive an initial assignment.",
        )
        return redirect("incident_detail", incident_id=incident_id)

    try:
        team = assign_team_to_incident(incident)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("incident_detail", incident_id=incident_id)

    if team is None:
        messages.warning(request, "No suitable team is available.")
    else:
        messages.success(
            request,
            f"{team.name} assigned successfully.",
        )

    return redirect("incident_detail", incident_id=incident_id)


@require_POST
def incident_update_status(request, incident_id):
    incident = get_object_or_404(Incident, pk=incident_id)

    if incident.status == Incident.Status.ASSIGNED:
        if incident.assigned_team_id is None:
            messages.error(request, "Assign a team first.")
        else:
            update_incident_status(
                incident,
                Incident.Status.IN_PROGRESS,
            )
            messages.success(request, "Incident is now in progress.")

    elif incident.status == Incident.Status.IN_PROGRESS:
        release_team_from_incident(incident)
        messages.success(
            request,
            "Incident resolved and team released.",
        )

    else:
        messages.error(request, "No valid next status transition.")

    return redirect("incident_detail", incident_id=incident_id)
