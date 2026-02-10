from django import forms
from django.contrib.auth import get_user_model
from .models import ServiceRequest

User = get_user_model()


class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = [
            "person_type", "document", "full_name", "phone",
            "cep", "street", "number", "neighborhood", "city",
            "service_type", "description", "notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ServiceRequestUpdateForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = [
            "person_type", "document", "full_name", "phone",
            "cep", "street", "number", "neighborhood", "city",
            "service_type", "description", "notes",
            "status", "assigned_to",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # assigned_to é opcional
        self.fields["assigned_to"].required = False

        # (opcional) mostrar só usuários staff no dropdown:
        self.fields["assigned_to"].queryset = User.objects.filter(is_staff=True).order_by("first_name", "username")
