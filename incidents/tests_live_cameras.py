"""Tests for the read-only live cameras page and its HLS file serving."""

import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from incidents import views_live
from incidents.models import Incident, IncidentSource, Location


class LiveCamerasTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(views_live, "STREAMS_ROOT", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_stream(self, folder, age_seconds=0):
        path = Path(self.tmp.name) / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / "live.m3u8").write_text("#EXTM3U\n#EXTINF:2.0,\nlive0.ts\n")
        (path / "live0.ts").write_bytes(b"\x47" * 188)
        if age_seconds:
            old = time.time() - age_seconds
            os.utime(path / "live.m3u8", (old, old))
        return path

    def cctv_incident(self, title, incident_type):
        source, _ = IncidentSource.objects.get_or_create(
            name="CCTV Monitoring", defaults={"source_type": IncidentSource.SourceType.SENSOR}
        )
        location, _ = Location.objects.get_or_create(name="Zone A")
        return Incident.objects.create(
            title=title, description="x", incident_type=incident_type, source=source,
            location=location, severity=Incident.Severity.HIGH,
        )

    def test_page_lists_three_cameras_and_navbar_link(self):
        response = self.client.get(reverse("live_cameras"))
        self.assertEqual(response.status_code, 200)
        for name in ("Crowd camera", "Restricted-area camera", "Fall-detection camera"):
            self.assertContains(response, name)
        self.assertContains(response, 'href="/live/"')
        self.assertContains(response, "hls.light.min.js")

    def test_status_reports_live_and_offline_cameras(self):
        self.write_stream("all_crowd")
        self.write_stream("all_fall", age_seconds=120)  # stale: simulation stopped
        data = self.client.get(reverse("live_status")).json()
        state = {cam["id"]: cam["live"] for cam in data["cameras"]}
        self.assertEqual(state, {"crowd": True, "restricted": False, "fall": False})

    def test_single_mode_folder_is_used_too(self):
        self.write_stream("demo_restricted")
        data = self.client.get(reverse("live_status")).json()
        self.assertTrue(next(c for c in data["cameras"] if c["id"] == "restricted")["live"])

    def test_playlist_and_segment_are_served(self):
        self.write_stream("all_crowd")
        playlist = self.client.get(reverse("live_stream_file", args=["crowd", "live.m3u8"]))
        self.assertEqual(playlist.status_code, 200)
        self.assertEqual(playlist["Content-Type"], "application/vnd.apple.mpegurl")
        self.assertEqual(playlist["Cache-Control"], "no-store")
        segment = self.client.get(reverse("live_stream_file", args=["crowd", "live0.ts"]))
        self.assertEqual(segment.status_code, 200)
        self.assertEqual(segment["Content-Type"], "video/mp2t")

    def test_stream_files_are_not_held_open(self):
        # ffmpeg must be able to replace the playlist and delete segments
        # right after they are served (Windows refuses this for open files).
        folder = self.write_stream("all_crowd")
        self.client.get(reverse("live_stream_file", args=["crowd", "live.m3u8"]))
        self.client.get(reverse("live_stream_file", args=["crowd", "live0.ts"]))
        (folder / "live0.ts").unlink()
        (folder / "live.m3u8").replace(folder / "old.m3u8")

    def test_unknown_or_unsafe_requests_are_refused(self):
        self.write_stream("all_crowd")
        bad = [
            ("crowd", "secret.txt"),
            ("crowd", "..%2F..%2Fmanage.py"),
            ("crowd", "live.m3u8.bak"),
            ("lobby", "live.m3u8"),
            ("fall", "live.m3u8"),      # offline camera
            ("crowd", "live9.ts"),      # missing segment
        ]
        for camera, filename in bad:
            response = self.client.get(f"/live/{camera}/{filename}")
            self.assertEqual(response.status_code, 404, (camera, filename))

    def test_last_alert_per_camera(self):
        self.cctv_incident("CCTV Crowding Alert - Zone A", Incident.IncidentType.CROWDING)
        fall = self.cctv_incident("CCTV Possible Fall - Zone A", Incident.IncidentType.MEDICAL)
        data = self.client.get(reverse("live_status")).json()
        alerts = {cam["id"]: cam["alert"] for cam in data["cameras"]}
        self.assertEqual(alerts["fall"]["id"], fall.id)
        self.assertEqual(alerts["fall"]["url"], reverse("incident_detail", args=[fall.id]))
        self.assertIsNotNone(alerts["crowd"])
        self.assertIsNone(alerts["restricted"])

    def test_archived_alerts_are_not_shown(self):
        # After "Prepare demo" archives the queue, cameras start clean.
        fall = self.cctv_incident("CCTV Possible Fall - Zone A", Incident.IncidentType.MEDICAL)
        fall.is_archived = True
        fall.save(update_fields=["is_archived"])
        data = self.client.get(reverse("live_status")).json()
        self.assertIsNone(next(c for c in data["cameras"] if c["id"] == "fall")["alert"])

    def test_page_changes_no_incident(self):
        incident = self.cctv_incident("CCTV Possible Fall - Zone A", Incident.IncidentType.MEDICAL)
        self.client.get(reverse("live_cameras"))
        self.client.get(reverse("live_status"))
        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.NEW)
        self.assertEqual(Incident.objects.count(), 1)
