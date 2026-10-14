"""Explicit presentation-only priority overrides for recorded CCTV demonstrations.

Not used by normal monitoring commands. The original calculated score and
priority are retained in the incident description for auditability.
"""
from incidents.models import Incident

DEMO_PROFILE = {
    "medium": (Incident.PriorityLevel.MEDIUM, 45),
    "high": (Incident.PriorityLevel.HIGH, 65),
    "critical": (Incident.PriorityLevel.CRITICAL, 85),
}


def apply_demo_priority(incident, level):
    """Apply a visibly labeled demo priority to a newly created CCTV incident."""
    priority, display_score = DEMO_PROFILE[level]
    original_level, original_score = incident.priority_level, incident.priority_score
    incident.description += (
        "\n\n[DEMONSTRATION MODE] The displayed priority is a scripted "
        f"{priority.upper()} classification for presentation purposes. "
        f"Original calculated priority: {original_level.upper()} "
        f"(score {original_score}). No production risk assessment implied."
    )
    incident.priority_level = priority
    incident.priority_score = display_score
    incident.save(update_fields=["description", "priority_level", "priority_score", "updated_at"])
    return incident
