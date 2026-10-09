from django import forms

from .models import Incident


class IncidentForm(forms.ModelForm):
    class Meta:
        model = Incident
        fields = [
            "title",
            "description",
            "incident_type",
            "source",
            "location",
            "severity",
            "people_affected",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "people_affected": forms.NumberInput(attrs={"min": 0}),
        }
