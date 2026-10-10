from django import forms

from .models import Incident


class IncidentForm(forms.ModelForm):
    class Meta:
        model = Incident
        fields = [
            "title",
            "description",
            "incident_type",
            "location",
            "severity",
            "people_affected",
        ]
        help_texts = {"people_affected": "Estimated number; use 0 if unknown."}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "people_affected": forms.NumberInput(attrs={"min": 0}),
        }
