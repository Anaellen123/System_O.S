from django import forms
from .models import ServiceRequest

class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = [
            "person_type", "document", "full_name", "phone",
            "cep", "street", "number", "neighborhood", "city",
            "service_type", "description", "notes",
        ]
