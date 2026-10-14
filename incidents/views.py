from django.contrib import messages
from django.db import transaction
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
        Incident.objects.filter(is_archived=False).select_related(
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
    active = Incident.objects.filter(is_archived=False).exclude(status=Incident.Status.RESOLVED)
    return {
        "critical_count": active.filter(
            priority_level=Incident.PriorityLevel.CRITICAL
        ).count(),
        "high_count": active.filter(
            priority_level=Incident.PriorityLevel.HIGH
        ).count(),
        "active_count": active.count(),
        "resolved_today_count": Incident.objects.filter(
            is_archived=False, status=Incident.Status.RESOLVED,
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
    archived = request.GET.get("archived") == "1"
    incidents = (Incident.objects.filter(is_archived=True).select_related(
        "source", "location", "assigned_team", "possible_duplicate_of"
    ).order_by("-created_at") if archived else ordered_incidents())
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
        "archived": archived,
        "resolved_count": Incident.objects.filter(is_archived=False, status=Incident.Status.RESOLVED).count(),
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

@require_POST
@transaction.atomic
def manage_incidents(request):
    """Bulk archive/restore and demo reset. All operations preserve incident rows."""
    action = request.POST.get("action")
    valid = {"archive_selected", "archive_resolved", "prepare_demo", "restore_selected"}
    if action not in valid:
        messages.error(request, "Invalid incident-management action.")
        return redirect("incident_list")
    if request.POST.get("confirm") != "yes":
        messages.error(request, "Confirm the action before continuing.")
        return redirect("incident_list")

    if action in ("archive_selected", "restore_selected"):
        ids = request.POST.getlist("incident_ids")
        if not ids or len(ids) > 500 or any(not item.isdecimal() for item in ids):
            messages.error(request, "Select valid incidents (maximum 500).")
            return redirect("incident_list")
        incidents = list(Incident.objects.select_for_update().filter(
            pk__in=set(ids), is_archived=(action == "restore_selected")
        ))
    elif action == "archive_resolved":
        incidents = list(Incident.objects.select_for_update().filter(
            is_archived=False, status=Incident.Status.RESOLVED
        ))
    else:
        incidents = list(Incident.objects.select_for_update().filter(is_archived=False))

    if action == "archive_selected":
        if any(i.status != Incident.Status.RESOLVED for i in incidents):
            messages.error(request, "Only resolved incidents can be archived individually. Use Prepare Demo to close an active queue.")
            return redirect("incident_list")
    if action == "restore_selected":
        Incident.objects.filter(pk__in=[i.pk for i in incidents]).update(is_archived=False)
        messages.success(request, f"Restored {len(incidents)} archived incident(s).")
        return redirect("incident_list")

    if action == "prepare_demo":
        # Demo reset closes prior alerts without deleting them or bypassing the live workflows.
        now = timezone.now()
        ids = [i.pk for i in incidents]
        Incident.objects.filter(pk__in=ids).exclude(
            status=Incident.Status.RESOLVED
        ).update(status=Incident.Status.RESOLVED, updated_at=now)
        team_ids = {i.assigned_team_id for i in incidents if i.assigned_team_id}
        for team in Team.objects.select_for_update().filter(pk__in=team_ids):
            if team.status != Team.Status.BUSY:
                continue
            remaining = Incident.objects.filter(
                assigned_team=team, is_archived=False
            ).exclude(pk__in=ids).exclude(status=Incident.Status.RESOLVED).exists()
            if not remaining:
                team.status = Team.Status.AVAILABLE
                team.save(update_fields=["status"])

    Incident.objects.filter(pk__in=[i.pk for i in incidents]).update(is_archived=True)
    label = "Demo queue prepared" if action == "prepare_demo" else "Incidents archived"
    messages.success(request, f"{label}: {len(incidents)} incident(s). History preserved.")
    return redirect("incident_list")
