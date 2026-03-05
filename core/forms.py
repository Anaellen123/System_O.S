from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group

from .models import ServiceRequest, Team

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
            "team",  # ✅ equipe da OS
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Responsável (usuário)
        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].queryset = (
            User.objects.filter(is_staff=True, is_active=True)
            .order_by("first_name", "username")
        )

        # Equipe (lista as equipes criadas)
        self.fields["team"].required = False
        self.fields["team"].queryset = Team.objects.all().order_by("-created_at", "name")


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]


class UserRoleForm(forms.ModelForm):
    group = forms.ModelChoiceField(
        queryset=Group.objects.all().order_by("name"),
        required=False,
        label="Nível do usuário"
    )

    class Meta:
        model = User
        fields = ["is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            current = self.instance.groups.first()
            self.fields["group"].initial = current

    def save(self, commit=True):
        user = super().save(commit=commit)

        user.groups.clear()
        group = self.cleaned_data.get("group")
        if group:
            user.groups.add(group)

        return user


class TeamCreateForm(forms.Form):
    name = forms.CharField(label="Nome da equipe", max_length=120)

    # ✅ seleção por checkbox e só do grupo "interno"
    users = forms.ModelMultipleChoiceField(
        label="Usuários da equipe (Interno)",
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    responsible = forms.ModelChoiceField(
        label="Responsável",
        queryset=User.objects.none(),
        required=True,
    )

    # (você pode esconder esses campos no template, eles não vão impedir salvar)
    function_description = forms.CharField(
        label="Função / Atividade",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    due_at = forms.DateTimeField(
        label="Prazo (data/hora)",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    # ✅ ESSENCIAL: deixar opcional pra não quebrar quando não renderizar no template
    priority = forms.ChoiceField(
        label="Prioridade",
        choices=Team.PRIORITY_CHOICES,
        initial=Team.PRIORITY_MEDIUM,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        interno_qs = (
            User.objects.filter(groups__name__iexact="interno", is_active=True)
            .distinct()
            .order_by("first_name", "username", "email")
        )

        self.fields["users"].queryset = interno_qs
        self.fields["responsible"].queryset = interno_qs

    def clean(self):
        cleaned = super().clean()
        users = cleaned.get("users")
        responsible = cleaned.get("responsible")

        if users is not None and responsible is not None:
            if responsible not in users:
                self.add_error(
                    "responsible",
                    "O responsável precisa estar entre os usuários selecionados."
                )

        return cleaned