"""
Live cameras page: every simulated CCTV stream on one screen.

run_simulation.sh / run_simulation.ps1 write each camera's HLS stream
(live.m3u8 + liveN.ts segments) into streams/<folder>/. Django serves those
files read-only under /live/<camera>/<file>, so the browser loads them from
the same origin as the dashboard (no extra ports, no CORS).

Read-only and presentation-only: nothing here creates, changes or resolves
incidents. Detectors keep reading their own HLS URLs as before.
"""

import re
import time
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from incidents.models import Incident
from incidents.services.monitoring_channels import monitoring_channel

STREAMS_ROOT = Path(settings.BASE_DIR) / "streams"
STALE_AFTER_SECONDS = 20  # playlist not rewritten for this long = camera offline
RECENT_INCIDENTS = 200

# Same cameras, folders and locations as run_simulation.sh / .ps1.
# "all" mode writes streams/all_<camera>; single mode writes streams/demo_<camera>.
CAMERAS = {
    "crowd": {
        "name": "Crowd camera",
        "location": "Transport Hub",
        "detector": "CCTV Crowd Detection",
        "folders": ("all_crowd", "demo_crowd"),
    },
    "restricted": {
        "name": "Restricted-area camera",
        "location": "Zone A",
        "detector": "CCTV Restricted-Area Detection",
        "folders": ("all_restricted", "demo_restricted"),
    },
    "fall": {
        "name": "Fall-detection camera",
        "location": "Zone A",
        "detector": "CCTV Fall Detection",
        "folders": ("all_fall", "demo_fall"),
    },
}

# MPEG-TS segments (what run_simulation writes) and fMP4 segments are both accepted.
_FILE_NAME = re.compile(r"live\.m3u8|live\d{1,9}\.(?:ts|m4s)|init\.mp4")
_CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".m4s": "video/iso.segment",
    ".mp4": "video/mp4",
}


def _active_folder(camera):
    """The camera's stream folder with the newest playlist, if it is still live."""
    newest, newest_time = None, 0.0
    for folder in CAMERAS[camera]["folders"]:
        playlist = STREAMS_ROOT / folder / "live.m3u8"
        try:
            modified = playlist.stat().st_mtime
        except OSError:
            continue
        if modified > newest_time:
            newest, newest_time = STREAMS_ROOT / folder, modified
    if newest is None or time.time() - newest_time > STALE_AFTER_SECONDS:
        return None
    return newest


def _latest_alerts():
    """Most recent non-archived incident per detector channel."""
    latest = {}
    wanted = {cam["detector"] for cam in CAMERAS.values()}
    recent = (
        Incident.objects.filter(source__name="CCTV Monitoring", is_archived=False)
        .select_related("source", "location")
        .order_by("-created_at")[:RECENT_INCIDENTS]
    )
    for incident in recent:
        channel = monitoring_channel(incident)
        if channel in wanted and channel not in latest:
            latest[channel] = incident
    return latest


def _camera_state(camera, latest):
    cam = CAMERAS[camera]
    incident = latest.get(cam["detector"])
    alert = None
    if incident is not None:
        alert = {
            "id": incident.pk,
            "title": incident.title,
            "status": incident.status,
            "status_label": incident.get_status_display(),
            "priority": incident.priority_level,
            "priority_label": incident.get_priority_level_display(),
            "time": timezone.localtime(incident.created_at).strftime("%H:%M"),
            "url": reverse("incident_detail", args=[incident.pk]),
        }
    return {
        "id": camera,
        "name": cam["name"],
        "location": cam["location"],
        "detector": cam["detector"],
        "live": _active_folder(camera) is not None,
        "playlist": reverse("live_stream_file", args=[camera, "live.m3u8"]),
        "alert": alert,
    }


def live_cameras(request):
    latest = _latest_alerts()
    cameras = [_camera_state(camera, latest) for camera in CAMERAS]
    return render(request, "live/cameras.html", {"cameras": cameras})


def live_status(request):
    latest = _latest_alerts()
    return JsonResponse({"cameras": [_camera_state(camera, latest) for camera in CAMERAS]})


def live_stream_file(request, camera, filename):
    """Serve one HLS playlist or segment for a known camera. Read-only."""
    if camera not in CAMERAS or not _FILE_NAME.fullmatch(filename):
        raise Http404("Unknown stream file.")
    folder = _active_folder(camera)
    if folder is None:
        raise Http404("Camera is offline.")
    path = folder / filename
    # Read the whole (small) file and close it at once. On Windows an open file
    # cannot be replaced or deleted, and ffmpeg rewrites the playlist and deletes
    # old segments every few seconds; holding the file open would break the stream.
    try:
        data = path.read_bytes()
    except OSError:
        raise Http404("Stream file not available.")
    response = HttpResponse(data, content_type=_CONTENT_TYPES[path.suffix])
    response["Cache-Control"] = "no-store"
    return response
