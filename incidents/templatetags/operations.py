from django import template
from incidents.services.monitoring_channels import monitoring_channel

register = template.Library()

@register.filter
def monitoring_module(incident):
    return monitoring_channel(incident)
