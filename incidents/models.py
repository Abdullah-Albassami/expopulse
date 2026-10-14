from django.db import models


class Location(models.Model):
    class ImportanceLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    name = models.CharField(max_length=100)
    zone = models.CharField(max_length=100, blank=True)
    importance_level = models.CharField(
        max_length=20,
        choices=ImportanceLevel.choices,
        default=ImportanceLevel.MEDIUM,
    )

    def __str__(self):
        return self.name


class Team(models.Model):
    class TeamType(models.TextChoices):
        SECURITY = "security", "Security"
        MEDICAL = "medical", "Medical"
        MAINTENANCE = "maintenance", "Maintenance"
        IT = "it", "IT"
        CLEANING = "cleaning", "Cleaning"
        VISITOR_SERVICES = "visitor_services", "Visitor Services"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BUSY = "busy", "Busy"
        OFFLINE = "offline", "Offline"

    name = models.CharField(max_length=100)
    team_type = models.CharField(
        max_length=30,
        choices=TeamType.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    current_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teams",
    )

    def __str__(self):
        return self.name


class IncidentSource(models.Model):
    class SourceType(models.TextChoices):
        STAFF = "staff", "Staff"
        SYSTEM = "system", "System"
        SENSOR = "sensor", "Sensor"
        VISITOR_SERVICE = "visitor_service", "Visitor Service"
        SECURITY = "security", "Security"
        MAINTENANCE = "maintenance", "Maintenance"

    name = models.CharField(max_length=100)
    source_type = models.CharField(
        max_length=30,
        choices=SourceType.choices,
    )

    def __str__(self):
        return self.name


class Incident(models.Model):
    class IncidentType(models.TextChoices):
        CROWDING = "crowding", "Crowding"
        MEDICAL = "medical", "Medical"
        SECURITY = "security", "Security"
        MAINTENANCE = "maintenance", "Maintenance"
        IT = "it", "IT"
        CLEANING = "cleaning", "Cleaning"
        ACCESSIBILITY = "accessibility", "Accessibility"
        OTHER = "other", "Other"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class PriorityLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        NEW = "new", "New"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"

    title = models.CharField(max_length=150)
    description = models.TextField()
    incident_type = models.CharField(
        max_length=30,
        choices=IncidentType.choices,
    )
    source = models.ForeignKey(
        IncidentSource,
        on_delete=models.PROTECT,
        related_name="incidents",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="incidents",
    )
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
    )
    people_affected = models.PositiveIntegerField(default=0)

    priority_score = models.PositiveIntegerField(default=0)
    priority_level = models.CharField(
        max_length=20,
        choices=PriorityLevel.choices,
        default=PriorityLevel.LOW,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )

    assigned_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_incidents",
    )

    possible_duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="possible_duplicates",
    )

    is_archived = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"#{self.id} - {self.title}"