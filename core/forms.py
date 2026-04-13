from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.utils import timezone

from .models import ServiceRequest, Team, ServiceType, Notification

User = get_user_model()


class ServiceRequestForm(forms.ModelForm):
    prazo_dias = forms.IntegerField(
        required=False,
        min_value=0,
        label="Prazo em dias",
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "Digite o prazo em dias",
        })
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "document", "full_name", "phone",
            "cep", "street", "number", "neighborhood", "city",
            "service_type", "description", "notes",
        ]
        widgets = {
            "document": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "full_name": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "cep": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "street": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "number": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "neighborhood": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "city": forms.TextInput(attrs={
                "class": "form-control",
            }),
            "description": forms.Textarea(attrs={
                "rows": 4,
                "class": "form-control",
            }),
            "notes": forms.Textarea(attrs={
                "rows": 3,
                "class": "form-control",
            }),
        }

    def clean_document(self):
        cpf = "".join(filter(str.isdigit, self.cleaned_data.get("document", "")))

        if len(cpf) != 11:
            raise forms.ValidationError("CPF inválido. Deve conter 11 dígitos.")

        return cpf

    def clean_prazo_dias(self):
        prazo = self.cleaned_data.get("prazo_dias")

        if prazo is None:
            return None

        if prazo < 0:
            raise forms.ValidationError("O prazo não pode ser negativo.")

        return prazo

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        service_types = ServiceType.objects.filter(is_active=True).order_by("name")
        self.fields["service_type"].widget = forms.Select(
            attrs={"class": "form-control"},
            choices=[("", "Selecione...")] + [
                (item.name, item.name) for item in service_types
            ]
        )


class ServiceRequestUpdateForm(forms.ModelForm):
    prazo_dias = forms.IntegerField(
        required=False,
        min_value=0,
        label="Prazo em dias",
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "Digite o prazo em dias",
        })
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "document", "full_name", "phone",
            "cep", "street", "number", "neighborhood", "city",
            "service_type", "description", "notes",
            "status", "assigned_to", "team",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-control"}),
            "assigned_to": forms.Select(attrs={"class": "form-control"}),
            "team": forms.Select(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "cep": forms.TextInput(attrs={"class": "form-control"}),
            "street": forms.TextInput(attrs={"class": "form-control"}),
            "number": forms.TextInput(attrs={"class": "form-control"}),
            "neighborhood": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_prazo_dias(self):
        prazo = self.cleaned_data.get("prazo_dias")

        if prazo is None:
            return None

        if prazo < 0:
            raise forms.ValidationError("O prazo não pode ser negativo.")

        return prazo

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        service_types = ServiceType.objects.filter(is_active=True).order_by("name")
        self.fields["service_type"].widget = forms.Select(
            attrs={"class": "form-control"},
            choices=[("", "Selecione...")] + [
                (item.name, item.name) for item in service_types
            ]
        )

        self.fields["assigned_to"].required = False
        self.fields["assigned_to"].queryset = (
            User.objects.filter(is_staff=True, is_active=True)
            .order_by("first_name", "username")
        )

        self.fields["team"].required = False
        self.fields["team"].queryset = Team.objects.all().order_by("-created_at", "name")

        self.fields["document"].disabled = True
        self.fields["full_name"].disabled = True

        instance = kwargs.get("instance")
        if instance and instance.created_at and instance.due_at:
            data_inicial = timezone.localtime(instance.created_at).date()
            data_final = instance.due_at.date() if hasattr(instance.due_at, "date") else instance.due_at
            diferenca = (data_final - data_inicial).days
            self.fields["prazo_dias"].initial = max(diferenca, 0)


class UserRegisterForm(forms.Form):
    username = forms.CharField(
        required=True,
        error_messages={
            "required": "Informe um usuário.",
        }
    )

    email = forms.EmailField(
        required=True,
        error_messages={
            "required": "Informe um email.",
            "invalid": "Digite um email válido.",
        }
    )

    cpf = forms.CharField(
        required=True,
        max_length=14,
        error_messages={
            "required": "Informe o CPF.",
        }
    )

    password1 = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        error_messages={
            "required": "Informe a senha.",
        }
    )

    password2 = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        error_messages={
            "required": "Confirme a senha.",
        }
    )


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
    name = forms.CharField(
        label="Nome da equipe",
        max_length=120,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Digite o nome da equipe",
        })
    )

    users = forms.ModelMultipleChoiceField(
        label="Usuários da equipe (Interno)",
        queryset=User.objects.none(),
        widget=forms.SelectMultiple(attrs={
            "class": "form-control",
        }),
        required=False,
    )

    responsible = forms.ModelChoiceField(
        label="Responsável",
        queryset=User.objects.none(),
        required=True,
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    function_description = forms.CharField(
        label="Função / Atividade",
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "class": "form-control",
            "placeholder": "Descreva a função da equipe",
        }),
    )

    due_at = forms.DateTimeField(
        label="Prazo (data/hora)",
        required=False,
        widget=forms.DateTimeInput(attrs={
            "type": "datetime-local",
            "class": "form-control",
        }),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    priority = forms.ChoiceField(
        label="Prioridade",
        choices=Team.PRIORITY_CHOICES,
        initial=Team.PRIORITY_MEDIUM,
        required=False,
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
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

        if responsible and users is not None:
            if responsible not in users:
                self.add_error(
                    "responsible",
                    "O responsável precisa estar entre os usuários selecionados."
                )

        return cleaned


class ServiceTypeForm(forms.ModelForm):
    class Meta:
        model = ServiceType
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Digite o nome do tipo de serviço",
            }),
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }


class NotificationCreateForm(forms.ModelForm):
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("first_name", "username", "email"),
        required=False,
        label="Usuários",
        widget=forms.SelectMultiple(attrs={
            "class": "form-control tomselect",
            "placeholder": "Selecione os usuários",
        }),
    )

    target_groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by("name"),
        required=False,
        label="Grupos",
        widget=forms.SelectMultiple(attrs={
            "class": "form-control tomselect",
            "placeholder": "Selecione os grupos",
        }),
    )

    class Meta:
        model = Notification
        fields = ["title", "message", "users", "target_groups"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Digite o título da notificação",
            }),
            "message": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Digite a mensagem da notificação",
            }),
        }

    def clean(self):
        cleaned = super().clean()
        users = cleaned.get("users")
        groups = cleaned.get("target_groups")

        if not users and not groups:
            raise forms.ValidationError("Selecione ao menos um usuário ou um grupo.")

        return cleaned