from datetime import timedelta
from django.db.models import Q, Exists, OuterRef
from django.contrib.auth import get_user_model
from .models import Notification, NotificationRead, TeamMember
from .models import Team
import json
from urllib.request import Request, urlopen
import os
from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db.models import Q, Count, Exists, OuterRef
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from urllib.parse import quote, urlencode
from django.utils import timezone
from datetime import datetime, time, timedelta
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views.decorators.http import require_http_methods, require_GET
from django.template.loader import render_to_string
from django.http import HttpResponse
from weasyprint import HTML
from django.db.models import Count, Avg, Q
from django.views.decorators.http import require_GET, require_POST
from .models import NotificationHidden
from decimal import Decimal, InvalidOperation

from .forms import (
    ServiceRequestForm,
    ServiceRequestUpdateForm,
    UserRegisterForm,
    UserRoleForm,
    TeamCreateForm,
    ServiceTypeForm,
    NotificationCreateForm,
)
from .models import (
    ServiceRequest,
    ServiceRequestAttachment,
    UserProfile,
    Team,
    TeamMember,
    ServiceType,
    Notification,
    NotificationRead,
)

User = get_user_model()

def _get_os_team_internal_users(os_obj):
    """
    Retorna os usuários internos da equipe da O.S.:
    - responsável da equipe
    - membros da equipe
    """
    if not getattr(os_obj, "team_id", None):
        return User.objects.none()

    responsible_ids = []
    if getattr(os_obj.team, "responsible_id", None):
        responsible_ids.append(os_obj.team.responsible_id)

    member_ids = list(
        TeamMember.objects.filter(team=os_obj.team)
        .values_list("user_id", flat=True)
    )

    ids = set(responsible_ids + member_ids)

    if not ids:
        return User.objects.none()

    return User.objects.filter(
        id__in=ids,
        is_active=True,
        groups__name__iexact="interno",
    ).distinct()




def _create_pending_notification_for_os(os_obj, created_by=None):
    if not os_obj:
        return None, False

    if os_obj.status == "DONE":
        return None, False

    prazo_base = os_obj.due_at

    # se não tiver prazo, cria baseado na criação
    if not prazo_base:
        prazo_base = os_obj.created_at + timedelta(days=10)

    # 🔥 GARANTE QUE É DATETIME
    if isinstance(prazo_base, timezone.datetime):
        # já é datetime
        pass
    else:
        # se for date, converte para datetime
        prazo_base = datetime.combine(prazo_base, time(0, 0))

    # 🔥 GARANTE TIMEZONE
    if timezone.is_naive(prazo_base):
        prazo_base = timezone.make_aware(
            prazo_base,
            timezone.get_current_timezone()
        )

    agora = timezone.now()

    if prazo_base > agora:
        return None, False

    internos_da_equipe = _get_os_team_internal_users(os_obj)

    superusers = User.objects.filter(
        is_superuser=True,
        is_active=True
    ).distinct()

    usuarios_destino = User.objects.filter(
        id__in=list(internos_da_equipe.values_list("id", flat=True)) +
               list(superusers.values_list("id", flat=True))
    ).distinct()

    if not usuarios_destino.exists():
        return None, False

    event_key = f"os_pending_{os_obj.pk}"

    return _create_notification(
        title=f"O.S. {os_obj.os_number} pendente",
        message=(
            f"A ordem de serviço {os_obj.os_number} está pendente.\n"
            f"Serviço: {os_obj.service_type}\n"
            f"Status atual: {os_obj.get_status_display()}"
        ),
        notification_type=Notification.TYPE_OPEN_10,
        users=list(usuarios_destino),
        service_request=os_obj,
        created_by=created_by,
        event_key=event_key,
    )

def _geocodificar_endereco_os(os_obj):
    """
    Converte o endereço da O.S. em latitude e longitude usando Nominatim.

    Retorna:
        (latitude, longitude) quando encontrar;
        (None, None) quando não encontrar.
    """

    if not os_obj:
        return None, None

    partes = [
        os_obj.street,
        os_obj.number,
        os_obj.neighborhood,
        os_obj.city or "Nossa Senhora do Socorro",
        "Sergipe",
        "Brasil",
        os_obj.cep,
    ]

    endereco = ", ".join(
        str(parte).strip()
        for parte in partes
        if parte and str(parte).strip()
    )

    if not endereco:
        return None, None

    parametros = urlencode({
        "q": endereco,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "br",
    })

    url = f"https://nominatim.openstreetmap.org/search?{parametros}"

    requisicao = Request(
        url,
        headers={
            "User-Agent": "PortalServicosUrbanos/1.0"
        }
    )

    try:
        with urlopen(requisicao, timeout=10) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))

        if not dados:
            return None, None

        latitude = Decimal(str(dados[0]["lat"]))
        longitude = Decimal(str(dados[0]["lon"]))

        return latitude, longitude

    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        InvalidOperation,
        json.JSONDecodeError,
    ):
        return None, None

class LoginForm(forms.Form):
    username = forms.EmailField(
        error_messages={
            "required": "Informe seu email.",
            "invalid": "Digite um email válido.",
        }
    )
    password = forms.CharField(
        widget=forms.PasswordInput,
        error_messages={
            "required": "Informe sua senha.",
        }
    )


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        error_messages={
            "required": "Informe seu email.",
            "invalid": "Digite um email válido.",
        }
    )

def _is_requisitante(user) -> bool:
    return user.is_authenticated and user.groups.filter(name__iexact="requisitante").exists()


def _is_interno(user) -> bool:
    return user.is_authenticated and user.groups.filter(name__iexact="interno").exists()


def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _make_unique_username(base: str) -> str:
    base = (base or "").strip()
    if not base:
        base = "usuario"

    candidate = base
    if not User.objects.filter(username__iexact=candidate).exists():
        return candidate

    i = 2
    while True:
        candidate = f"{base}-{i}"
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate
        i += 1


def _send_activation_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    activation_path = reverse("activate_account", kwargs={
        "uidb64": uid,
        "token": token,
    })
    activation_link = request.build_absolute_uri(activation_path)

    subject = "Ative sua conta - Portal de Serviços Urbanos"
    message = (
        f"Olá, {user.username}!\n\n"
        f"Seu cadastro foi realizado com sucesso.\n\n"
        f"Para ativar sua conta, clique no link abaixo:\n"
        f"{activation_link}\n\n"
        f"Se você não realizou este cadastro, ignore este email."
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "no-reply@portaldeservicos.com"

    send_mail(
        subject,
        message,
        from_email,
        [user.email],
        fail_silently=False,
    )


def _formatar_prazo_data(data_inicial, data_final):
    """
    Retorna o prazo em formato amigável:
    - até 29 dias: X dias
    - a partir de 30 dias: X mês(es) e Y dia(s)
    """
    if not data_inicial or not data_final:
        return ""

    if hasattr(data_inicial, "date"):
        data_inicial = data_inicial.date()
    if hasattr(data_final, "date"):
        data_final = data_final.date()

    diferenca = (data_final - data_inicial).days

    if diferenca <= 0:
        return "0 dias"

    if diferenca < 30:
        return f"{diferenca} dia" if diferenca == 1 else f"{diferenca} dias"

    meses = diferenca // 30
    resto = diferenca % 30

    if resto == 0:
        return f"{meses} mês" if meses == 1 else f"{meses} meses"

    if meses == 1:
        return f"1 mês e {resto} dia" if resto == 1 else f"1 mês e {resto} dias"

    return f"{meses} meses e {resto} dia" if resto == 1 else f"{meses} meses e {resto} dias"


def _montar_endereco_os(os_obj):
    partes = [
        getattr(os_obj, "street", "") or "",
        getattr(os_obj, "number", "") or "",
        getattr(os_obj, "neighborhood", "") or "",
        getattr(os_obj, "city", "") or "",
        getattr(os_obj, "cep", "") or "",
    ]
    return ", ".join([p.strip() for p in partes if str(p).strip()])


def _obter_observacoes_os(os_obj):
    candidatos = [
        "notes",
        "note",
        "observation",
        "observations",
        "observacao",
        "observacoes",
        "comments",
        "comment",
    ]
    for campo in candidatos:
        if hasattr(os_obj, campo):
            valor = getattr(os_obj, campo, "")
            if valor:
                return valor
    return ""


def _obter_anexos_os(os_obj):
    try:
        return ServiceRequestAttachment.objects.filter(request=os_obj)
    except Exception:
        return []


def index(request):
    return render(request, "index.html")


def solicitar_servico(request):
    perfil = None
    nome_usuario = ""
    cpf_usuario = ""

    eh_requisitante = (
        request.user.is_authenticated
        and _is_requisitante(request.user)
    )

    if eh_requisitante:
        perfil = (
            UserProfile.objects
            .filter(user=request.user)
            .first()
        )

        nome_usuario = (
            request.user.get_full_name()
            or request.user.first_name
            or request.user.username
            or ""
        ).strip()

        cpf_usuario = _only_digits(
            getattr(perfil, "cpf", "") or ""
        )

    if request.method == "POST":
        post_data = request.POST.copy()

        if eh_requisitante:
            post_data["full_name"] = nome_usuario
            post_data["document"] = cpf_usuario

        form = ServiceRequestForm(
            post_data,
            request.FILES,
        )

        if not form.is_valid():
            messages.error(
                request,
                "Revise os campos obrigatórios.",
            )

            return render(
                request,
                "solicitar_servico.html",
                {
                    "form": form,
                    "created": False,
                },
            )

        document_digits = _only_digits(
            form.cleaned_data.get("document") or ""
        )

        if len(document_digits) != 11:
            form.add_error(
                "document",
                "Digite um CPF válido com 11 dígitos.",
            )

            messages.error(
                request,
                "CPF inválido.",
            )

            return render(
                request,
                "solicitar_servico.html",
                {
                    "form": form,
                    "created": False,
                },
            )

        perfil_cpf = (
            UserProfile.objects
            .filter(cpf=document_digits)
            .select_related("user")
            .first()
        )

        if not perfil_cpf:
            form.add_error(
                "document",
                (
                    "Usuário não encontrado. Cadastre uma conta "
                    "antes de solicitar o serviço."
                ),
            )

            messages.error(
                request,
                (
                    "Este CPF ainda não possui cadastro. "
                    "Cadastre uma conta antes de continuar."
                ),
            )

            return render(
                request,
                "solicitar_servico.html",
                {
                    "form": form,
                    "created": False,
                    "cpf_nao_cadastrado": True,
                    "cpf_informado": document_digits,
                },
            )

        usuario_do_cpf = perfil_cpf.user

        if eh_requisitante:
            if usuario_do_cpf.id != request.user.id:
                form.add_error(
                    "document",
                    "Este CPF pertence a outra conta.",
                )

                messages.error(
                    request,
                    "Este CPF está cadastrado em outra conta.",
                )

                return render(
                    request,
                    "solicitar_servico.html",
                    {
                        "form": form,
                        "created": False,
                    },
                )

        prazo_dias = form.cleaned_data.get(
            "prazo_dias"
        )

        obj = form.save(commit=False)

        # O sistema utiliza somente CPF atualmente.
        # A opção PJ permanece no model para uso futuro.
        obj.person_type = "PF"
        obj.document = document_digits
        obj.created_by = usuario_do_cpf

        if eh_requisitante:
            obj.full_name = nome_usuario
            obj.document = cpf_usuario

        # Mantém o campo antigo com o nome do serviço para
        # compatibilidade com relatórios e notificações.
        if obj.service_type_ref:
            obj.service_type = obj.service_type_ref.name

        if prazo_dias is None:
            prazo_dias = _get_service_type_deadline_days(
                obj.service_type
            )

        if prazo_dias is not None:
            obj.due_at = (
                timezone.now()
                + timedelta(days=int(prazo_dias))
            )
        else:
            obj.due_at = None

        obj.save()

        # ==========================================================
        # Geocodifica o endereço para exibição no mapa
        # ==========================================================
        try:
            latitude, longitude = _geocodificar_endereco_os(obj)

            if (
                latitude is not None
                and longitude is not None
            ):
                obj.latitude = latitude
                obj.longitude = longitude

                obj.save(
                    update_fields=[
                        "latitude",
                        "longitude",
                    ]
                )

        except Exception as erro:
            print(
                f"Não foi possível geocodificar a O.S. "
                f"{obj.os_number}: {erro}"
            )

        # ==========================================================
        # Salvar anexos
        # ==========================================================
        anexos = request.FILES.getlist("attachments")

        print("=" * 50)
        print(
            "TOTAL DE ANEXOS RECEBIDOS:",
            len(anexos),
        )
        print(
            "FILES:",
            request.FILES,
        )
        print("=" * 50)

        for arquivo in anexos:
            ServiceRequestAttachment.objects.create(
                request=obj,
                file=arquivo,
            )

        messages.success(
            request,
            (
                f"Solicitação criada com sucesso! "
                f"Número: {obj.os_number}"
            ),
        )

        initial = {}

        if eh_requisitante:
            initial = {
                "full_name": nome_usuario,
                "document": cpf_usuario,
            }

        form_limpo = ServiceRequestForm(
            initial=initial,
        )

        return render(
            request,
            "solicitar_servico.html",
            {
                "form": form_limpo,
                "created": True,
                "os_created": obj,
            },
        )

    initial = {}

    if eh_requisitante:
        initial = {
            "full_name": nome_usuario,
            "document": cpf_usuario,
        }

    form = ServiceRequestForm(
        initial=initial,
    )

    return render(
        request,
        "solicitar_servico.html",
        {
            "form": form,
            "created": False,
        },
    )

@require_GET
def api_os_status(request, os_number):
    os_number = (os_number or "").strip().upper()

    obj = ServiceRequest.objects.filter(os_number=os_number).first()
    if not obj:
        return JsonResponse({"ok": False, "message": "OS não encontrada."}, status=404)

    status_label = dict(ServiceRequest.STATUS_CHOICES).get(obj.status, obj.status)

    return JsonResponse({
        "ok": True,
        "os_number": obj.os_number,
        "status": obj.status,
        "status_label": status_label,
        "service_type": obj.service_type,
        "created_at": obj.created_at.strftime("%d/%m/%Y %H:%M"),
    })


@require_GET
def api_check_cpf_exists(request):
    cpf = _only_digits(request.GET.get("cpf", ""))

    if len(cpf) != 11:
        return JsonResponse({
            "ok": False,
            "exists": False,
            "message": "CPF inválido."
        }, status=400)

    profile = (
        UserProfile.objects
        .filter(cpf=cpf)
        .select_related("user")
        .first()
    )

    if not profile:
        return JsonResponse({
            "ok": True,
            "exists": False
        })

    user = profile.user

    nome = (
        user.get_full_name()
        or user.first_name
        or user.username
        or ""
    )

    telefone = getattr(profile, "phone", "") or ""

    return JsonResponse({
        "ok": True,
        "exists": True,
        "user": {
            "name": nome,
            "phone": telefone,
            "cep": profile.cep or "",
            "street": profile.street or "",
            "number": profile.number or "",
            "neighborhood": profile.neighborhood or "",
            "city": profile.city or "",
        }
    })

@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    login_form = LoginForm()
    forgot_form = ForgotPasswordForm()

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        cpf = (request.POST.get("cpf") or "").strip()
        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        cpf_digits = _only_digits(cpf)

        form = UserRegisterForm(request.POST)
        valid = True

        if not username:
            form.add_error("username", "Informe seu nome completo.")
            valid = False
        elif User.objects.filter(username__iexact=username).exists():
            form.add_error("username", "Já existe um usuário cadastrado com este nome.")
            valid = False

        if not email:
            form.add_error("email", "Informe um email.")
            valid = False
        elif User.objects.filter(email__iexact=email).exists():
            form.add_error("email", "Este email já está cadastrado.")
            valid = False

        if not cpf:
            form.add_error("cpf", "Informe o CPF.")
            valid = False
        else:
            if len(cpf_digits) != 11:
                form.add_error("cpf", "Digite um CPF com 11 dígitos.")
                valid = False
            elif not _validate_cpf(cpf_digits):
                form.add_error("cpf", "CPF inválido.")
                valid = False
            elif UserProfile.objects.filter(cpf=cpf_digits).exists() or UserProfile.objects.filter(cpf=cpf).exists():
                form.add_error("cpf", "Este CPF já está cadastrado.")
                valid = False

        if not password1:
            form.add_error("password1", "Informe a senha.")
            valid = False

        if not password2:
            form.add_error("password2", "Confirme a senha.")
            valid = False

        if password1 and password2 and password1 != password2:
            form.add_error("password2", "As senhas não coincidem.")
            valid = False

        if password1 and password2 and password1 == password2:
            try:
                validate_password(password1)
            except ValidationError as e:
                for msg in e.messages:
                    form.add_error("password1", msg)
                valid = False

        if not valid:
            return render(request, "login_admin.html", {
                "show_register": True,
                "form": form,
                "login_form": login_form,
                "forgot_form": forgot_form,
                "register_data": {
                    "username": username,
                    "email": email,
                    "cpf": cpf,
                },
                "login_data": {},
                "forgot_data": {},
            })

        user = None

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password1,
                    is_active=False,
                )

                partes = username.split(" ", 1)
                user.first_name = partes[0]
                user.last_name = partes[1] if len(partes) > 1 else ""
                user.save()

                g = Group.objects.filter(name__iexact="requisitante").first()
                if g:
                    user.groups.add(g)

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.cpf = cpf_digits
                profile.save()

            _send_activation_email(request, user)

            return render(request, "login_admin.html", {
                "success_message": "Conta criada com sucesso! Enviamos um link de ativação para seu email.",
                "form": UserRegisterForm(),
                "login_form": LoginForm(),
                "forgot_form": ForgotPasswordForm(),
                "register_data": {},
                "login_data": {},
                "forgot_data": {},
            })

        except Exception as e:
            try:
                if user:
                    user.delete()
            except Exception:
                pass

            form.add_error(None, f"Não foi possível enviar o email de ativação. Erro: {e}")

            return render(request, "login_admin.html", {
                "show_register": True,
                "form": form,
                "login_form": login_form,
                "forgot_form": forgot_form,
                "register_data": {
                    "username": username,
                    "email": email,
                    "cpf": cpf,
                },
                "login_data": {},
                "forgot_data": {},
            })

    return redirect("login_admin")

@require_http_methods(["GET"])
def activate_account(request, uidb64, token):
    if request.user.is_authenticated:
        return redirect("dashboard")

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        user = None

    if not user:
        messages.error(request, "Link de ativação inválido.")
        return redirect("login_admin")

    if user.is_active:
        messages.info(request, "Esta conta já foi ativada. Faça login.")
        return redirect("login_admin")

    if not default_token_generator.check_token(user, token):
        messages.error(request, "Link de ativação inválido ou expirado.")
        return redirect("login_admin")

    user.is_active = True
    user.save(update_fields=["is_active"])

    messages.success(request, "Conta ativada com sucesso! Agora você já pode fazer login.")
    return redirect("login_admin")


@require_http_methods(["POST"])
def forgot_password_request(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = ForgotPasswordForm(request.POST)
    register_form = UserRegisterForm()
    login_form = LoginForm()

    email = (request.POST.get("email") or "").strip().lower()

    if not form.is_valid():
        return render(request, "login_admin.html", {
            "show_forgot": True,
            "forgot_form": form,
            "form": register_form,
            "login_form": login_form,
            "forgot_data": {
                "email": email,
            },
            "register_data": {},
            "login_data": {},
        })

    user = User.objects.filter(email__iexact=email).first()

    if not user:
        form.add_error("email", "Nenhum usuário foi encontrado com este email.")
        return render(request, "login_admin.html", {
            "show_forgot": True,
            "forgot_form": form,
            "form": register_form,
            "login_form": login_form,
            "forgot_data": {
                "email": email,
            },
            "register_data": {},
            "login_data": {},
        })

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    reset_path = reverse("reset_password_confirm", kwargs={
        "uidb64": uid,
        "token": token,
    })
    reset_link = request.build_absolute_uri(reset_path)

    subject = "Recuperação de senha - Portal de Serviços Urbanos"
    message = (
        f"Olá, {user.username}!\n\n"
        f"Recebemos uma solicitação para redefinir sua senha.\n\n"
        f"Acesse o link abaixo para cadastrar uma nova senha:\n"
        f"{reset_link}\n\n"
        f"Se você não solicitou esta alteração, ignore este email."
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "no-reply@portaldeservicos.com"

    try:
        send_mail(
            subject,
            message,
            from_email,
            [user.email],
            fail_silently=False,
        )

        return render(request, "login_admin.html", {
            "success_message": "Enviamos o link de recuperação para seu email.",
            "form": register_form,
            "login_form": login_form,
            "forgot_form": ForgotPasswordForm(),
            "register_data": {},
            "login_data": {},
            "forgot_data": {},
        })

    except Exception as e:
        form.add_error(None, f"Não foi possível enviar o email de recuperação. Erro: {e}")
        return render(request, "login_admin.html", {
            "show_forgot": True,
            "forgot_form": form,
            "form": register_form,
            "login_form": login_form,
            "forgot_data": {
                "email": email,
            },
            "register_data": {},
            "login_data": {},
        })

@require_http_methods(["GET", "POST"])
def reset_password_confirm(request, uidb64, token):
    if request.user.is_authenticated:
        return redirect("dashboard")

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        user = None

    if not user or not default_token_generator.check_token(user, token):
        messages.error(request, "Link de redefinição inválido ou expirado.")
        return redirect("login_admin")

    if request.method == "POST":
        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        if not password1 or not password2:
            messages.error(request, "Informe e confirme a nova senha.")
            return render(request, "reset_password.html", {
                "uidb64": uidb64,
                "token": token,
            })

        if password1 != password2:
            messages.error(request, "As senhas não coincidem.")
            return render(request, "reset_password.html", {
                "uidb64": uidb64,
                "token": token,
            })

        try:
            validate_password(password1, user=user)
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
            return render(request, "reset_password.html", {
                "uidb64": uidb64,
                "token": token,
            })

        user.set_password(password1)
        user.save()

        messages.success(request, "Senha redefinida com sucesso. Faça login com a nova senha.")
        return redirect("login_admin")

    return render(request, "reset_password.html", {
        "uidb64": uidb64,
        "token": token,
    })


def is_superuser(user):
    return user.is_authenticated and user.is_superuser


@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def user_role_update(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, "Você não tem permissão para editar usuários.")
        return redirect("dashboard")

    u = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=u)

    if request.method == "POST":
        u.first_name = (request.POST.get("first_name") or "").strip()
        u.last_name = (request.POST.get("last_name") or "").strip()
        u.email = (request.POST.get("email") or "").strip()
        u.username = f"{u.first_name} {u.last_name}".strip() or u.username

        u.is_active = bool(request.POST.get("is_active"))
        u.is_staff = bool(request.POST.get("is_staff"))
        u.is_superuser = bool(request.POST.get("is_superuser"))
        u.save()

        profile.cpf = _only_digits(request.POST.get("cpf") or "")
        profile.phone = (request.POST.get("phone") or "").strip()

        birth = (request.POST.get("birth_date") or "").strip()
        profile.birth_date = birth or None

        profile.cep = (request.POST.get("cep") or "").strip()
        profile.street = (request.POST.get("street") or "").strip()
        profile.number = (request.POST.get("number") or "").strip()
        profile.neighborhood = (request.POST.get("neighborhood") or "").strip()
        profile.city = (request.POST.get("city") or "").strip()

        profile.cargo_funcao = (request.POST.get("cargo_funcao") or "").strip()
        profile.setor = (request.POST.get("setor") or "").strip()

        profile.save()

        group_id = (request.POST.get("group_id") or "").strip()
        u.groups.clear()

        if group_id:
            g = Group.objects.filter(id=group_id).first()
            if g:
                u.groups.add(g)

        messages.success(request, "Usuário atualizado com sucesso.")
        return redirect("users_list")

    groups = Group.objects.all().order_by("name")
    current_group = u.groups.first()

    return render(request, "users/user_edit.html", {
        "u": u,
        "profile": profile,
        "groups": groups,
        "current_group": current_group,
    })


@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def user_delete(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, "Você não tem permissão para excluir usuários.")
        return redirect("dashboard")

    u = get_object_or_404(User, id=user_id)

    if u.id == request.user.id:
        messages.error(request, "Você não pode excluir seu próprio usuário.")
        return redirect("users_list")

    user_name = u.get_full_name() or u.username
    u.delete()

    messages.success(request, f'Usuário "{user_name}" excluído com sucesso.')
    return redirect("users_list")


@login_required(login_url="login_admin")
def users_list(request):
    if not request.user.is_superuser:
        messages.error(request, "Você não tem permissão para acessar Usuários.")
        return redirect("dashboard")

    q = (request.GET.get("q") or "").strip()
    filtro = (request.GET.get("filtro") or "").strip()

    qs = User.objects.all().prefetch_related("groups").order_by("-date_joined")

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    if filtro == "requisitante":
        qs = qs.filter(groups__name__iexact="requisitante")

    elif filtro == "interno":
        qs = qs.filter(groups__name__iexact="interno")

    elif filtro == "superuser":
        qs = qs.filter(is_superuser=True)

    elif filtro == "ativo":
        qs = qs.filter(is_active=True)

    elif filtro == "bloqueado":
        qs = qs.filter(is_active=False)

    elif filtro == "staff":
        qs = qs.filter(is_staff=True)

    qs = qs.distinct()

    return render(request, "users_list.html", {
        "users": qs,
        "q": q,
        "filtro": filtro,
    })


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    register_form = UserRegisterForm()
    forgot_form = ForgotPasswordForm()

    if request.method == "POST":
        form = LoginForm(request.POST)

        username_or_email = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()

        if not form.is_valid():
            return render(request, "login_admin.html", {
                "login_form": form,
                "form": register_form,
                "forgot_form": forgot_form,
                "login_data": {
                    "username": username_or_email,
                },
                "register_data": {},
                "forgot_data": {},
            })

        user = authenticate(request, username=username_or_email, password=password)

        if user is None and username_or_email:
            try:
                u = User.objects.get(email__iexact=username_or_email)
                user = authenticate(request, username=u.username, password=password)
            except User.DoesNotExist:
                user = None

        if user is None and username_or_email:
            u = User.objects.filter(
                Q(username__iexact=username_or_email) | Q(email__iexact=username_or_email)
            ).first()

            if u and not u.is_active:
                form.add_error(None, "Sua conta ainda não foi ativada por email.")
            else:
                form.add_error(None, "Usuário ou senha inválidos.")

            return render(request, "login_admin.html", {
                "login_form": form,
                "form": register_form,
                "forgot_form": forgot_form,
                "login_data": {
                    "username": username_or_email,
                },
                "register_data": {},
                "forgot_data": {},
            })

        login(request, user)
        return redirect("dashboard")

    return render(request, "login_admin.html", {
        "form": UserRegisterForm(),
        "login_form": LoginForm(),
        "forgot_form": ForgotPasswordForm(),
        "register_data": {},
        "login_data": {},
        "forgot_data": {},
    })

def logout_view(request):
    logout(request)
    return redirect("login_admin")


@login_required(login_url="login_admin")
def dashboard(request):
    if _is_requisitante(request.user):
        return redirect("dashboard_requisitante")

    solicitacoes = ServiceRequest.objects.all()

    stats = {
        "abertos": solicitacoes.filter(status="OPEN").count(),
        "andamento": solicitacoes.filter(status="IN_PROGRESS").count(),
        "concluidos": solicitacoes.filter(status="DONE").count(),
        "total": solicitacoes.count(),
    }

    today = timezone.localdate()
    start = today - timedelta(days=89)

    daily = (
        solicitacoes
        .filter(
            created_at__date__gte=start,
            created_at__date__lte=today
        )
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(c=Count("id"))
        .order_by("d")
    )

    counts_by_day = {
        row["d"]: row["c"]
        for row in daily
    }

    labels = []
    data = []

    for i in range(90):
        day = start + timedelta(days=i)
        labels.append(day.strftime("%d/%m"))
        data.append(counts_by_day.get(day, 0))

    bairros_qs = (
        solicitacoes
        .filter(city__icontains="socorro")
        .exclude(neighborhood__isnull=True)
        .exclude(neighborhood__exact="")
        .values("neighborhood")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    bairros_labels = [
        row["neighborhood"]
        for row in bairros_qs
    ]

    bairros_data = [
        row["total"]
        for row in bairros_qs
    ]

    # ==========================================================
    # Gráficos circulares por tipo de demanda
    # ==========================================================
    total_solicitacoes = solicitacoes.count()

    demandas_qs = (
        solicitacoes
        .exclude(service_type__isnull=True)
        .exclude(service_type__exact="")
        .values("service_type")
        .annotate(
            total=Count("id"),
            concluidas=Count(
                "id",
                filter=Q(status="DONE")
            ),
            andamento=Count(
                "id",
                filter=Q(status="IN_PROGRESS")
            ),
            pendentes=Count(
                "id",
                filter=Q(status="OPEN")
            ),
        )
        .order_by("-total", "service_type")
    )

    graficos_demandas = []

    for indice, item in enumerate(demandas_qs):
        total_demanda = item["total"]

        percentual = (
            round((total_demanda / total_solicitacoes) * 100)
            if total_solicitacoes
            else 0
        )

        graficos_demandas.append({
            "id": indice + 1,
            "nome": item["service_type"],
            "total": total_demanda,
            "percentual": percentual,
            "concluidas": item["concluidas"],
            "andamento": item["andamento"],
            "pendentes": item["pendentes"],
        })

    os_com_localizacao = (
        solicitacoes
        .exclude(latitude__isnull=True)
        .exclude(longitude__isnull=True)
        .order_by("-created_at")
    )

    mapa_pontos = []

    for os_obj in os_com_localizacao:
        endereco_partes = [
            os_obj.street,
            os_obj.number,
            os_obj.neighborhood,
            os_obj.city,
        ]

        endereco = ", ".join(
            str(parte).strip()
            for parte in endereco_partes
            if parte and str(parte).strip()
        )

        mapa_pontos.append({
            "id": os_obj.pk,
            "numero": os_obj.os_number,
            "solicitante": os_obj.full_name or "Não informado",
            "servico": os_obj.service_type or "Não informado",
            "bairro": os_obj.neighborhood or "Não informado",
            "endereco": endereco or "Endereço não informado",
            "status": os_obj.status,
            "status_label": os_obj.get_status_display(),
            "data": timezone.localtime(
                os_obj.created_at
            ).strftime("%d/%m/%Y %H:%M"),
            "latitude": float(os_obj.latitude),
            "longitude": float(os_obj.longitude),
            "url": reverse(
                "os_detail",
                kwargs={"pk": os_obj.pk}
            ),
        })

    return render(request, "dashboard.html", {
        "stats": stats,
        "chart_labels": labels,
        "chart_data": data,
        "bairros_labels": bairros_labels,
        "bairros_data": bairros_data,
        "graficos_demandas": graficos_demandas,
        "mapa_pontos": mapa_pontos,
    })



@login_required(login_url="login_admin")
def dashboard_requisitante(request):
    if not _is_requisitante(request.user):
        return redirect("dashboard")

    qs = ServiceRequest.objects.filter(created_by=request.user).order_by("-created_at")

    stats = {
        "abertos": qs.filter(status="OPEN").count(),
        "andamento": qs.filter(status="IN_PROGRESS").count(),
        "concluidos": qs.filter(status="DONE").count(),
        "total": qs.count(),
    }

    recent = qs[:10]

    return render(request, "requisitante/dashboard_requisitante.html", {
        "stats": stats,
        "recent": recent,
    })


@login_required(login_url="login_admin")
def requests_list(request):
    qs = ServiceRequest.objects.all().order_by("-created_at")

    if _is_requisitante(request.user):
        qs = qs.filter(created_by=request.user)

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(os_number__icontains=q)
            | Q(full_name__icontains=q)
            | Q(document__icontains=q)
            | Q(phone__icontains=q)
            | Q(neighborhood__icontains=q)
            | Q(service_type__icontains=q)
        )

    total = qs.count()
    ativas = qs.exclude(status="DONE").count()

    vencidas = qs.filter(
        status__in=["OPEN", "IN_PROGRESS"],
        created_at__lt=timezone.now() - timedelta(days=30)
    ).count()

    context = {
        "os_list": qs,
        "total": total,
        "ativas": ativas,
        "vencidas": vencidas,
        "status_atual": status or "todas",
    }

    return render(request, "os_list.html", context)


@login_required(login_url="login_admin")
def request_detail(request, pk):
    obj = get_object_or_404(ServiceRequest, pk=pk)

    if _is_requisitante(request.user) and obj.created_by_id != request.user.id:
        messages.error(request, "Você não tem permissão para acessar esta solicitação.")
        return redirect("dashboard_requisitante")

    return render(request, "request_detail.html", {"obj": obj})


@login_required(login_url="login_admin")
def os_create(request):
    perfil = UserProfile.objects.filter(user=request.user).first()
    eh_requisitante = _is_requisitante(request.user)

    nome_usuario = (
        request.user.get_full_name()
        or request.user.first_name
        or request.user.username
        or ""
    ).strip()

    cpf_usuario = _only_digits(
        getattr(perfil, "cpf", "") or ""
    )

    if request.method == "POST":
        post_data = request.POST.copy()

        if eh_requisitante:
            post_data["full_name"] = nome_usuario
            post_data["document"] = cpf_usuario

        form = ServiceRequestForm(
            post_data,
            request.FILES,
        )

        if form.is_valid():
            document_digits = _only_digits(
                form.cleaned_data.get("document") or ""
            )

            if len(document_digits) != 11:
                form.add_error(
                    "document",
                    "Digite um CPF válido com 11 dígitos.",
                )

                messages.error(
                    request,
                    "CPF inválido.",
                )

                return render(
                    request,
                    "os_nova.html",
                    {
                        "form": form,
                    },
                )

            perfil_cpf = (
                UserProfile.objects
                .filter(cpf=document_digits)
                .select_related("user")
                .first()
            )

            if not perfil_cpf:
                form.add_error(
                    "document",
                    (
                        "CPF não encontrado. Para cadastrar uma O.S. "
                        "com este CPF, primeiro cadastre o usuário no "
                        "menu Usuários > Criar usuário."
                    ),
                )

                messages.error(
                    request,
                    (
                        "CPF não encontrado. É preciso cadastrar o "
                        "usuário antes de criar a O.S."
                    ),
                )

                return render(
                    request,
                    "os_nova.html",
                    {
                        "form": form,
                    },
                )

            obj = form.save(commit=False)

            # Mantém o nome do serviço sincronizado
            if obj.service_type_ref:
                obj.service_type = obj.service_type_ref.name

            obj.created_by = perfil_cpf.user

            if eh_requisitante:
                obj.full_name = nome_usuario
                obj.document = cpf_usuario

            prazo_dias = form.cleaned_data.get("prazo_dias")

            if prazo_dias is None:
                prazo_dias = _get_service_type_deadline_days(
                    obj.service_type
                )

            if prazo_dias is not None:
                obj.due_at = timezone.now() + timedelta(
                    days=int(prazo_dias)
                )
            else:
                obj.due_at = None

            obj.save()

            # ==========================================================
            # Geocodifica o endereço para exibição no mapa
            # ==========================================================
            try:
                latitude, longitude = _geocodificar_endereco_os(obj)

                if latitude is not None and longitude is not None:
                    obj.latitude = latitude
                    obj.longitude = longitude

                    obj.save(
                        update_fields=[
                            "latitude",
                            "longitude",
                        ]
                    )

            except Exception as erro:
                print(
                    f"Não foi possível geocodificar a O.S. "
                    f"{obj.os_number}: {erro}"
                )

            # ==========================================================
            # Salvar anexos
            # ==========================================================
            anexos = request.FILES.getlist("attachments")

            print("=" * 50)
            print("TOTAL DE ANEXOS RECEBIDOS:", len(anexos))
            print("FILES:", request.FILES)
            print("=" * 50)

            for arquivo in anexos:
                ServiceRequestAttachment.objects.create(
                    request=obj,
                    file=arquivo,
                )

            messages.success(
                request,
                f"Ordem criada com sucesso: {obj.os_number}",
            )

            return redirect("os_list")

        messages.error(
            request,
            "Revise os campos obrigatórios.",
        )

    else:
        initial = {}

        if eh_requisitante:
            initial = {
                "full_name": nome_usuario,
                "document": cpf_usuario,
            }

        form = ServiceRequestForm(
            initial=initial,
        )

    return render(
        request,
        "os_nova.html",
        {
            "form": form,
        },
    )

@login_required(login_url="login_admin")
def os_list(request, status=None):
    qs = ServiceRequest.objects.all().order_by("-created_at")

    if _is_requisitante(request.user):
        qs = qs.filter(created_by=request.user)

    if status and status != "todas":
        qs = qs.filter(status=status)

    get_status = (request.GET.get("status") or "").strip()
    if get_status:
        qs = qs.filter(status=get_status)

    def get_multi_text(name):
        valores = request.GET.getlist(name)
        itens = []

        for valor in valores:
            partes = str(valor).replace(";", ",").split(",")
            for parte in partes:
                parte = parte.strip()
                if parte:
                    itens.append(parte)

        return itens

    nomes = get_multi_text("nome")
    cpfs = get_multi_text("cpf")
    telefones = get_multi_text("telefone")

    bairros = [b.strip() for b in request.GET.getlist("bairro") if b.strip()]
    servicos = [s.strip() for s in request.GET.getlist("servico") if s.strip()]

    if nomes:
        q_nome = Q()
        for nome in nomes:
            q_nome |= Q(full_name__icontains=nome)
        qs = qs.filter(q_nome)

    if cpfs:
        q_cpf = Q()
        for cpf in cpfs:
            q_cpf |= Q(document__icontains=cpf)
        qs = qs.filter(q_cpf)

    if telefones:
        q_tel = Q()
        for telefone in telefones:
            q_tel |= Q(phone__icontains=telefone)
        qs = qs.filter(q_tel)

    if bairros:
        qs = qs.filter(neighborhood__in=bairros)

    if servicos:
        q_servico = Q()
        for servico in servicos:
            q_servico |= Q(service_type__icontains=servico)
        qs = qs.filter(q_servico)

    total = qs.count()
    ativas = qs.exclude(status="DONE").count()

    vencidas = qs.filter(
        status__in=["OPEN", "IN_PROGRESS"],
        created_at__lt=timezone.now() - timedelta(days=30)
    ).count()

    bairros_options = (
        ServiceRequest.objects
        .exclude(neighborhood__isnull=True)
        .exclude(neighborhood__exact="")
        .values_list("neighborhood", flat=True)
        .distinct()
        .order_by("neighborhood")
    )

    servicos_options = (
        ServiceType.objects
        .filter(is_active=True)
        .order_by("name")
    )

    context = {
        "os_list": qs,
        "total": total,
        "ativas": ativas,
        "vencidas": vencidas,
        "status_atual": get_status or status or "todas",

        "bairros_options": bairros_options,
        "servicos_options": servicos_options,

        "bairros_selecionados": bairros,
        "servicos_selecionados": servicos,

        "filtros": {
            "nome": ", ".join(nomes),
            "cpf": ", ".join(cpfs),
            "telefone": ", ".join(telefones),
        }
    }

    return render(request, "os_list.html", context)

@login_required(login_url="login_admin")
def os_detail(request, pk):
    os_obj = get_object_or_404(ServiceRequest, pk=pk)

    # Guarda a URL da listagem com filtros.
    # No GET vem pela URL.
    # No POST vem pelo input hidden do formulário.
    back_url = (
        request.GET.get("next")
        or request.POST.get("next")
        or reverse("os_list")
    )

    if _is_requisitante(request.user) and os_obj.created_by_id != request.user.id:
        messages.error(request, "Você não tem permissão para acessar esta OS.")
        return redirect("dashboard_requisitante")

    if request.method == "POST":
        if _is_requisitante(request.user):
            messages.error(request, "Você não tem permissão para editar esta OS.")

            detail_url = reverse("os_detail", kwargs={"pk": os_obj.pk})
            return redirect(f"{detail_url}?next={quote(back_url)}")

        status_anterior = os_obj.status

        form = ServiceRequestUpdateForm(request.POST, instance=os_obj)

        if form.is_valid():
            os_edit = form.save(commit=False)

            if os_edit.service_type_ref:
                os_edit.service_type = os_edit.service_type_ref.name

            prazo_dias = form.cleaned_data.get("prazo_dias")

            if prazo_dias is not None and str(prazo_dias).strip() != "":
                data_base = timezone.localtime(os_obj.created_at).date()
                os_edit.due_at = data_base + timedelta(days=int(prazo_dias))

            os_edit.save()
            form.save_m2m()

            if status_anterior != "DONE" and os_edit.status == "DONE" and os_edit.created_by:
                event_key = f"os_done_{os_edit.pk}"

                _create_notification(
                    title=f"O.S {os_edit.os_number} concluída",
                    message=(
                        f"Sua ordem de serviço {os_edit.os_number} foi concluída.\n"
                        f"Serviço: {os_edit.service_type}\n"
                        f"Status atual: {os_edit.get_status_display()}"
                    ),
                    notification_type="DONE",
                    users=[os_edit.created_by],
                    service_request=os_edit,
                    created_by=request.user,
                    event_key=event_key,
                )

            Notification.objects.filter(
                event_key=f"os_pending_{os_edit.pk}"
            ).delete()

            if os_edit.status != "DONE":
                _create_pending_notification_for_os(
                    os_obj=os_edit,
                    created_by=request.user
                )

            messages.success(request, "OS atualizada com sucesso!")

            detail_url = reverse("os_detail", kwargs={"pk": os_obj.pk})
            return redirect(f"{detail_url}?next={quote(back_url)}")

        else:
            messages.error(request, "Revise os campos e tente novamente.")

    else:
        form = ServiceRequestUpdateForm(instance=os_obj)

    prazo_formatado = _formatar_prazo_data(os_obj.created_at, os_obj.due_at)
    anexos = _obter_anexos_os(os_obj)
    endereco_completo = _montar_endereco_os(os_obj)

    return render(request, "os_detail.html", {
        "os": os_obj,
        "form": form,
        "prazo_formatado": prazo_formatado,
        "anexos": anexos,
        "endereco_completo": endereco_completo or "—",
        "status_choices": ServiceRequest.STATUS_CHOICES,
        "back_url": back_url,
    })

@login_required(login_url="login_admin")
def os_print(request, pk):
    os_obj = get_object_or_404(ServiceRequest, pk=pk)

    if _is_requisitante(request.user) and os_obj.created_by_id != request.user.id:
        messages.error(request, "Você não tem permissão para imprimir esta OS.")
        return redirect("dashboard_requisitante")

    anexos = _obter_anexos_os(os_obj)
    endereco_completo = _montar_endereco_os(os_obj)
    observacoes = _obter_observacoes_os(os_obj)
    prazo_formatado = _formatar_prazo_data(os_obj.created_at, os_obj.due_at)

    return render(request, "os/os_print.html", {
        "os": os_obj,
        "anexos": anexos,
        "endereco_completo": endereco_completo or "—",
        "observacoes": observacoes or "",
        "prazo_formatado": prazo_formatado or "—",
    })


def api_cep(request, cep):
    cep_num = "".join([c for c in cep if c.isdigit()])

    if len(cep_num) != 8:
        return JsonResponse({"error": "CEP inválido"}, status=400)

    url = f"https://viacep.com.br/ws/{cep_num}/json/"
    with urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("erro"):
        return JsonResponse({"error": "CEP não encontrado"}, status=404)

    return JsonResponse({
        "rua": data.get("logradouro", ""),
        "bairro": data.get("bairro", ""),
        "cidade": data.get("localidade", ""),
        "uf": data.get("uf", ""),
    })


def _is_repeated_digits(s: str) -> bool:
    return len(s) > 0 and s == s[0] * len(s)


def _validate_cpf(cpf: str) -> bool:
    cpf = _only_digits(cpf)
    if len(cpf) != 11 or _is_repeated_digits(cpf):
        return False

    nums = list(map(int, cpf))

    s1 = sum(nums[i] * (10 - i) for i in range(9))
    d1 = (s1 * 10) % 11
    d1 = 0 if d1 == 10 else d1
    if d1 != nums[9]:
        return False

    s2 = sum(nums[i] * (11 - i) for i in range(10))
    d2 = (s2 * 10) % 11
    d2 = 0 if d2 == 10 else d2
    return d2 == nums[10]


@require_GET
def api_validate_document(request):
    value = request.GET.get("value", "")
    digits = _only_digits(value)

    if len(digits) != 11:
        return JsonResponse({
            "ok": False,
            "type": "CPF",
            "message": "Digite um CPF com 11 dígitos."
        }, status=400)

    ok = _validate_cpf(digits)

    if not ok:
        return JsonResponse({
            "ok": False,
            "type": "CPF",
            "message": "CPF inválido."
        }, status=400)

    if UserProfile.objects.filter(cpf=digits).exists():
        return JsonResponse({
            "ok": False,
            "type": "CPF",
            "message": "CPF válido."
        }, status=400)

    return JsonResponse({
        "ok": True,
        "type": "CPF",
        "message": "CPF válido."
    })

@login_required(login_url="login_admin")
def team_list(request):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para acessar a Equipe.")
        return redirect("dashboard_requisitante")

    teams = (
        Team.objects.all()
        .order_by("-created_at")
        .select_related("responsible")
        .prefetch_related("members__user", "service_requests")
    )

    for team in teams:
        for os in team.service_requests.all():
            os.prazo_formatado = _formatar_prazo_data(os.created_at, os.due_at)

    users = (
        User.objects.filter(groups__name__iexact="interno", is_active=True)
        .distinct()
        .order_by("first_name", "username", "email")
    )

    return render(request, "team_list.html", {
        "teams": teams,
        "users": users,
        "priority_choices": Team.PRIORITY_CHOICES,
    })


@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def team_create(request):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para criar equipes.")
        return redirect("dashboard_requisitante")

    if request.method == "POST":
        form = TeamCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                users = list(form.cleaned_data["users"])
                responsible = form.cleaned_data["responsible"]

                if responsible not in users:
                    users.append(responsible)

                team = Team.objects.create(
                    name=form.cleaned_data["name"].strip(),
                    responsible=responsible,
                    function_description=(form.cleaned_data.get("function_description") or "").strip(),
                    due_at=form.cleaned_data.get("due_at"),
                    priority=form.cleaned_data.get("priority") or Team.PRIORITY_MEDIUM,
                )

                for u in users:
                    TeamMember.objects.create(team=team, user=u)

            messages.success(request, "Equipe criada com sucesso.")
            return redirect("team_list")
        else:
            messages.error(request, "Revise os campos e tente novamente.")
    else:
        form = TeamCreateForm()

    return render(request, "team_create.html", {"form": form})


@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def team_update(request, team_id):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para editar equipes.")
        return redirect("dashboard_requisitante")

    team = get_object_or_404(Team, id=team_id)
    form = TeamCreateForm(request.POST)

    if form.is_valid():
        with transaction.atomic():
            users = list(form.cleaned_data["users"])
            responsible = form.cleaned_data["responsible"]

            if responsible not in users:
                users.append(responsible)

            team.name = form.cleaned_data["name"].strip()
            team.responsible = responsible
            team.function_description = (form.cleaned_data.get("function_description") or "").strip()
            team.due_at = form.cleaned_data.get("due_at")
            team.priority = form.cleaned_data.get("priority") or Team.PRIORITY_MEDIUM
            team.save()

            TeamMember.objects.filter(team=team).delete()
            for u in users:
                TeamMember.objects.create(team=team, user=u)

        messages.success(request, f'Equipe "{team.name}" atualizada com sucesso.')
    else:
        messages.error(request, "Não foi possível atualizar a equipe. Revise os campos.")

    return redirect("team_list")


@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def team_delete(request, team_id):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para excluir equipes.")
        return redirect("dashboard_requisitante")

    team = get_object_or_404(Team, id=team_id)
    team_name = team.name
    team.delete()

    messages.success(request, f'Equipe "{team_name}" excluída com sucesso.')
    return redirect("team_list")


@login_required(login_url="login_admin")
def team_my(request):
    if not _is_interno(request.user):
        messages.error(request, "Você não tem permissão para acessar Minhas O.S.")
        return redirect("dashboard")

    teams = (
        Team.objects
        .filter(Q(responsible=request.user) | Q(members__user=request.user))
        .distinct()
        .select_related("responsible")
        .prefetch_related("members__user", "service_requests")
        .order_by("-created_at")
    )

    total = 0
    abertas = 0
    andamento = 0
    concluidas = 0

    for team in teams:
        team.os_list = list(
            ServiceRequest.objects
            .filter(team=team)
            .select_related("team", "assigned_to", "created_by")
            .order_by("-created_at")
        )

        for os in team.os_list:
            os.prazo_formatado = _formatar_prazo_data(os.created_at, os.due_at)

        team.stats = {
            "total": len(team.os_list),
            "abertas": sum(1 for os in team.os_list if os.status == "OPEN"),
            "andamento": sum(1 for os in team.os_list if os.status == "IN_PROGRESS"),
            "concluidas": sum(1 for os in team.os_list if os.status == "DONE"),
        }

        total += team.stats["total"]
        abertas += team.stats["abertas"]
        andamento += team.stats["andamento"]
        concluidas += team.stats["concluidas"]

    stats = {
        "total": total,
        "abertas": abertas,
        "andamento": andamento,
        "concluidas": concluidas,
    }

    return render(request, "my_team.html", {
        "teams": teams,
        "stats": stats,
    })


@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def team_remove_os(request, team_id, os_id):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para alterar equipes.")
        return redirect("dashboard_requisitante")

    team = get_object_or_404(Team, id=team_id)
    os_obj = get_object_or_404(ServiceRequest, id=os_id, team=team)

    os_obj.team = None
    os_obj.save(update_fields=["team"])

    messages.success(request, f"O.S {os_obj.os_number} removida da equipe {team.name}.")
    return redirect("team_list")


@login_required(login_url="login_admin")
def team_my_report(request):
    if not _is_interno(request.user):
        messages.error(request, "Você não tem permissão para acessar este relatório.")
        return redirect("dashboard")

    teams = (
        Team.objects
        .filter(Q(responsible=request.user) | Q(members__user=request.user))
        .distinct()
        .select_related("responsible")
        .prefetch_related("members__user", "service_requests")
        .order_by("-created_at")
    )

    total = 0
    abertas = 0
    andamento = 0
    concluidas = 0

    for team in teams:
        team.os_list = list(
            ServiceRequest.objects
            .filter(team=team)
            .select_related("team", "assigned_to", "created_by")
            .order_by("-created_at")
        )

        team.stats = {
            "total": len(team.os_list),
            "abertas": sum(1 for os in team.os_list if os.status == "OPEN"),
            "andamento": sum(1 for os in team.os_list if os.status == "IN_PROGRESS"),
            "concluidas": sum(1 for os in team.os_list if os.status == "DONE"),
        }

        total += team.stats["total"]
        abertas += team.stats["abertas"]
        andamento += team.stats["andamento"]
        concluidas += team.stats["concluidas"]

    stats = {
        "total": total,
        "abertas": abertas,
        "andamento": andamento,
        "concluidas": concluidas,
    }

    return render(request, "reports/team_os_report.html", {
        "teams": teams,
        "stats": stats,
        "generated_at": timezone.localtime(),
    })


@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def os_status_view(request, pk):
    os_obj = get_object_or_404(ServiceRequest, pk=pk)

    # ==========================================================
    # PERMISSÃO DE ACESSO
    # ==========================================================
    if (
        _is_requisitante(request.user)
        and os_obj.created_by_id != request.user.id
    ):
        messages.error(
            request,
            "Você não tem permissão para acessar esta O.S."
        )
        return redirect("dashboard_requisitante")

    # ==========================================================
    # FUNÇÃO AUXILIAR PARA CONVERTER DATA DO FORMULÁRIO
    # ==========================================================
    def converter_data_formulario(valor, horario_padrao=None):
        """
        Converte uma data no formato YYYY-MM-DD para um datetime
        com o fuso horário atual do Django.
        """
        if not valor:
            return None

        data_convertida = datetime.strptime(
            valor,
            "%Y-%m-%d"
        ).date()

        horario = horario_padrao or time.min

        data_hora = datetime.combine(
            data_convertida,
            horario
        )

        if timezone.is_naive(data_hora):
            data_hora = timezone.make_aware(
                data_hora,
                timezone.get_current_timezone()
            )

        return data_hora

    # ==========================================================
    # ALTERAÇÃO DE STATUS
    # ==========================================================
    if request.method == "POST":
        if _is_requisitante(request.user):
            messages.error(
                request,
                "Você não tem permissão para alterar o status desta O.S."
            )
            return redirect(
                "os_status_view",
                pk=os_obj.pk
            )

        novo_status = (
            request.POST.get("status") or ""
        ).strip()

        solution_taken = (
            request.POST.get("solution_taken") or ""
        ).strip()

        finished_in_days = (
            request.POST.get("finished_in_days") or ""
        ).strip()

        # Datas enviadas separadamente pelo formulário.
        started_at_raw = (
            request.POST.get("started_at") or ""
        ).strip()

        completed_at_raw = (
            request.POST.get("completed_at") or ""
        ).strip()

        status_validos = [
            item[0]
            for item in ServiceRequest.STATUS_CHOICES
        ]

        if novo_status not in status_validos:
            messages.error(
                request,
                "Status inválido."
            )
            return redirect(
                "os_status_view",
                pk=os_obj.pk
            )

        status_anterior = os_obj.status
        agora = timezone.now()

        # ======================================================
        # BLOQUEIO DE REABERTURA
        # ======================================================
        if (
            status_anterior == "DONE"
            and novo_status != "DONE"
            and not request.user.is_superuser
        ):
            messages.error(
                request,
                (
                    "Esta O.S. já foi concluída. "
                    "Apenas o administrador pode alterar "
                    "o status novamente."
                )
            )
            return redirect(
                "os_status_view",
                pk=os_obj.pk
            )

        # ======================================================
        # STATUS: EM ANDAMENTO
        # ======================================================
        if novo_status == "IN_PROGRESS":
            # Registra somente a primeira entrada em andamento.
            if not os_obj.started_at:
                os_obj.started_at = agora

            os_obj.status = "IN_PROGRESS"
            os_obj.solution_taken = None
            os_obj.finished_in_days = None
            os_obj.completed_at = None

            os_obj.save(
                update_fields=[
                    "status",
                    "started_at",
                    "solution_taken",
                    "finished_in_days",
                    "completed_at",
                    "status_updated_at",
                ]
            )

            messages.success(
                request,
                (
                    "O.S. colocada em andamento. "
                    "A data de início foi registrada automaticamente."
                )
            )

            return redirect(
                "os_status_view",
                pk=os_obj.pk
            )

        # ======================================================
        # STATUS: CONCLUÍDO
        # ======================================================
        if novo_status == "DONE":
            if not solution_taken:
                messages.error(
                    request,
                    (
                        "Preencha o campo Solução tomada "
                        "para finalizar a O.S."
                    )
                )
                return redirect(
                    "os_status_view",
                    pk=os_obj.pk
                )

            if finished_in_days == "":
                messages.error(
                    request,
                    (
                        "Informe em quantos dias "
                        "a O.S. foi finalizada."
                    )
                )
                return redirect(
                    "os_status_view",
                    pk=os_obj.pk
                )

            try:
                total_dias = int(finished_in_days)

                if total_dias < 0:
                    raise ValueError

            except (TypeError, ValueError):
                messages.error(
                    request,
                    (
                        "O campo 'Finalizado em quantos dias' "
                        "deve possuir um número inteiro válido."
                    )
                )
                return redirect(
                    "os_status_view",
                    pk=os_obj.pk
                )

            # ==================================================
            # CONVERSÃO E VALIDAÇÃO DAS DATAS
            # ==================================================
            try:
                # Mantém o horário anterior quando somente
                # a data do início for corrigida.
                horario_inicio = (
                    timezone.localtime(os_obj.started_at).time()
                    if os_obj.started_at
                    else time.min
                )

                data_inicio_informada = converter_data_formulario(
                    started_at_raw,
                    horario_inicio
                )

                # Mantém o horário anterior da conclusão, quando existir.
                horario_conclusao = (
                    timezone.localtime(os_obj.completed_at).time()
                    if os_obj.completed_at
                    else time.min
                )

                data_conclusao_informada = converter_data_formulario(
                    completed_at_raw,
                    horario_conclusao
                )

            except ValueError:
                messages.error(
                    request,
                    (
                        "Uma das datas informadas é inválida. "
                        "Revise a data de início e a data de finalização."
                    )
                )
                return redirect(
                    "os_status_view",
                    pk=os_obj.pk
                )

            # Usa exatamente a data de início enviada pelo formulário.
            if data_inicio_informada:
                data_inicio = data_inicio_informada

            elif os_obj.started_at:
                data_inicio = os_obj.started_at

            else:
                # Compatibilidade com O.S. antiga.
                data_inicio = os_obj.created_at

            # A data de início não pode ser anterior à abertura.
            abertura_local = timezone.localtime(
                os_obj.created_at
            )

            if data_inicio.date() < abertura_local.date():
                messages.error(
                    request,
                    (
                        "A data de início do andamento não pode ser "
                        "anterior à data de abertura da O.S."
                    )
                )
                return redirect(
                    "os_status_view",
                    pk=os_obj.pk
                )

            # Usa exatamente a conclusão enviada pelo formulário.
            if data_conclusao_informada:
                data_conclusao = data_conclusao_informada
            else:
                # Somente calcula quando a conclusão não foi informada.
                data_conclusao = (
                    data_inicio
                    + timedelta(days=total_dias)
                )

            if data_conclusao.date() < data_inicio.date():
                messages.error(
                    request,
                    (
                        "A data de finalização não pode ser "
                        "anterior à data de início do andamento."
                    )
                )
                return redirect(
                    "os_status_view",
                    pk=os_obj.pk
                )

            # Calcula novamente os dias usando as duas datas efetivas.
            total_dias_calculado = max(
                (
                    data_conclusao.date()
                    - data_inicio.date()
                ).days,
                0
            )

            os_obj.status = "DONE"
            os_obj.solution_taken = solution_taken
            os_obj.started_at = data_inicio
            os_obj.completed_at = data_conclusao
            os_obj.finished_in_days = total_dias_calculado

            os_obj.save(
                update_fields=[
                    "status",
                    "solution_taken",
                    "finished_in_days",
                    "started_at",
                    "completed_at",
                    "status_updated_at",
                ]
            )

            messages.success(
                request,
                (
                    "O.S. concluída com sucesso! "
                    f"Tempo de execução: {total_dias_calculado} "
                    f"{'dia' if total_dias_calculado == 1 else 'dias'}."
                )
            )

            return redirect(
                "os_status_view",
                pk=os_obj.pk
            )

        # ======================================================
        # STATUS: PENDENTE
        # ======================================================
        os_obj.status = "OPEN"
        os_obj.solution_taken = None
        os_obj.finished_in_days = None
        os_obj.completed_at = None

        # O started_at é preservado para manter o histórico
        # da primeira entrada em andamento.
        os_obj.save(
            update_fields=[
                "status",
                "solution_taken",
                "finished_in_days",
                "completed_at",
                "status_updated_at",
            ]
        )

        messages.success(
            request,
            "Status da O.S. atualizado com sucesso!"
        )

        return redirect(
            "os_status_view",
            pk=os_obj.pk
        )

    # ==========================================================
    # DADOS PARA EXIBIÇÃO
    # ==========================================================
    prazo_formatado = _formatar_prazo_data(
        os_obj.created_at,
        os_obj.due_at,
    )

    endereco_completo = _montar_endereco_os(os_obj)
    anexos = _obter_anexos_os(os_obj)
    observacoes = _obter_observacoes_os(os_obj)

    agora = timezone.now()

    # Data original de abertura da O.S.
    data_abertura_calendario = timezone.localtime(
        os_obj.created_at
    )

    # Para O.S. antiga sem started_at, a data de início visual
    # será a mesma data da abertura.
    if os_obj.started_at:
        data_inicio_calendario = timezone.localtime(
            os_obj.started_at
        )
        inicio_foi_estimado = False
    else:
        data_inicio_calendario = data_abertura_calendario
        inicio_foi_estimado = True

    data_fim_calendario = None

    # Prioridade para a data de conclusão realmente salva.
    if os_obj.completed_at:
        data_fim_calendario = timezone.localtime(
            os_obj.completed_at
        )

    # Compatibilidade com O.S. antiga que já possui
    # finished_in_days, mas ainda não possui completed_at.
    elif (
        os_obj.status == "DONE"
        and os_obj.finished_in_days is not None
    ):
        data_fim_calendario = (
            data_inicio_calendario
            + timedelta(
                days=int(os_obj.finished_in_days)
            )
        )

    # Quando está em andamento, o calendário mostra até hoje.
    elif os_obj.status == "IN_PROGRESS":
        data_fim_calendario = timezone.localtime(agora)

    dias_calculados = None

    if (
        os_obj.status == "DONE"
        and data_inicio_calendario
        and data_fim_calendario
    ):
        dias_calculados = max(
            (
                data_fim_calendario.date()
                - data_inicio_calendario.date()
            ).days,
            0
        )

    elif os_obj.finished_in_days is not None:
        dias_calculados = int(
            os_obj.finished_in_days
        )

    # ==========================================================
    # TEMPLATE
    # ==========================================================
    return render(
        request,
        "os/os_status_view.html",
        {
            "os": os_obj,
            "prazo_formatado": prazo_formatado or "—",
            "endereco_completo": endereco_completo or "—",
            "anexos": anexos,
            "observacoes": observacoes or "—",
            "status_choices": ServiceRequest.STATUS_CHOICES,

            # Data de abertura
            "data_abertura_iso": (
                data_abertura_calendario
                .date()
                .isoformat()
            ),

            "data_abertura_formatada": (
                data_abertura_calendario
                .strftime("%d/%m/%Y às %H:%M")
            ),

            # Data de início do andamento
            "data_inicio_iso": (
                data_inicio_calendario
                .date()
                .isoformat()
            ),

            "data_inicio_formatada": (
                (
                    data_inicio_calendario
                    .strftime("%d/%m/%Y às %H:%M")
                    + " — mesmo dia da abertura"
                )
                if inicio_foi_estimado
                else data_inicio_calendario.strftime(
                    "%d/%m/%Y às %H:%M"
                )
            ),

            # Data de conclusão
            "data_fim_iso": (
                data_fim_calendario
                .date()
                .isoformat()
                if data_fim_calendario
                else ""
            ),

            "data_conclusao_formatada": (
                data_fim_calendario.strftime(
                    "%d/%m/%Y às %H:%M"
                )
                if data_fim_calendario
                else "Ainda não concluído"
            ),

            "dias_calculados": dias_calculados,
            "inicio_foi_estimado": inicio_foi_estimado,
        },
    )


def _service_type_deadlines_file():
    return os.path.join(settings.BASE_DIR, "service_type_deadlines.json")


def _load_service_type_deadlines():
    path = _service_type_deadlines_file()

    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_service_type_deadline_days(service_type_name):
    nome = (service_type_name or "").strip()
    if not nome:
        return None

    service_type = ServiceType.objects.filter(name__iexact=nome).first()
    if not service_type:
        return None

    return service_type.prazo_dias

def _load_service_type_deadlines():
    path = _service_type_deadlines_file()

    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _save_service_type_deadlines(data):
    path = _service_type_deadlines_file()

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def service_type_dashboard(request):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para acessar esta área.")
        return redirect("dashboard_requisitante")

    if request.method == "POST":
        form = ServiceTypeForm(request.POST)

        if form.is_valid():
            nome = (form.cleaned_data.get("name") or "").strip()
            prazo_raw = (request.POST.get("prazo_dias") or "").strip()

            if not nome:
                messages.error(request, "Informe o nome do tipo de serviço.")
                return redirect("service_type_dashboard")

            if ServiceType.objects.filter(name__iexact=nome).exists():
                messages.error(request, "Já existe um tipo de serviço com este nome.")
                return redirect("service_type_dashboard")

            prazo_dias = None

            if prazo_raw != "":
                try:
                    prazo_dias = int(prazo_raw)

                    if prazo_dias < 0:
                        raise ValueError

                except ValueError:
                    messages.error(
                        request,
                        "O prazo em dias deve ser um número válido maior ou igual a zero."
                    )
                    return redirect("service_type_dashboard")

            obj = form.save(commit=False)
            obj.name = nome
            obj.prazo_dias = prazo_dias

            if hasattr(obj, "is_active"):
                obj.is_active = True

            obj.save()

            messages.success(request, "Tipo de serviço cadastrado com sucesso.")
            return redirect("service_type_dashboard")

        messages.error(request, "Revise os campos e tente novamente.")

    else:
        form = ServiceTypeForm()

    service_types = ServiceType.objects.all().order_by("name")

    total_os = (
        ServiceRequest.objects
        .exclude(service_type__isnull=True)
        .exclude(service_type__exact="")
        .count()
    )

    ranking_qs = (
        ServiceRequest.objects
        .exclude(service_type__isnull=True)
        .exclude(service_type__exact="")
        .values("service_type")
        .annotate(total=Count("id"))
        .order_by("-total", "service_type")[:3]
    )

    top_services = []

    for row in ranking_qs:
        quantidade = row["total"]
        percentual = round((quantidade / total_os) * 100) if total_os > 0 else 0

        top_services.append({
            "name": row["service_type"],
            "count": quantidade,
            "percent": percentual,
        })

    return render(request, "service_types.html", {
        "form": form,
        "service_types": service_types,
        "top_services": top_services,
        "top_services_json": json.dumps(top_services, ensure_ascii=False),
    })
    
@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def service_type_delete(request, pk):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para excluir tipos de serviço.")
        return redirect("dashboard_requisitante")

    obj = get_object_or_404(ServiceType, pk=pk)
    nome = obj.name

    deadlines_map = _load_service_type_deadlines()
    deadlines_map.pop(str(obj.id), None)
    _save_service_type_deadlines(deadlines_map)

    obj.delete()

    messages.success(request, f'Tipo de serviço "{nome}" excluído com sucesso.')
    return redirect("service_type_dashboard")

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.hashers import check_password

@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def account_settings(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "profile":
            username = (request.POST.get("username") or "").strip()
            email = (request.POST.get("email") or "").strip().lower()
            cpf = (request.POST.get("cpf") or "").strip()
            cpf_digits = _only_digits(cpf)

            errors = {}

            # USERNAME
            if not username:
                errors["username"] = "Informe o nome de usuário."
            elif User.objects.filter(username__iexact=username).exclude(id=user.id).exists():
                errors["username"] = "Já existe outro usuário com este nome."

            # EMAIL
            if not email:
                errors["email"] = "Informe seu email."
            elif User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                errors["email"] = "Este email já está cadastrado para outro usuário."

            # CPF
            if not cpf:
                errors["cpf"] = "Informe o CPF."
            else:
                if len(cpf_digits) != 11:
                    errors["cpf"] = "Digite um CPF com 11 dígitos."
                elif not _validate_cpf(cpf_digits):
                    errors["cpf"] = "CPF inválido."
                elif UserProfile.objects.filter(cpf=cpf_digits).exclude(user=user).exists():
                    errors["cpf"] = "Este CPF já está cadastrado para outro usuário."

            if errors:
                return render(request, "account_settings.html", {
                    "user_obj": user,
                    "profile": profile,
                    "form_errors": errors,
                    "form_data": {
                        "username": username,
                        "email": email,
                        "cpf": cpf,
                    }
                })

            user.username = username
            user.email = email

            partes = username.split(" ", 1)
            user.first_name = partes[0]
            user.last_name = partes[1] if len(partes) > 1 else ""

            user.save()

            profile.cpf = cpf_digits
            profile.save()

            messages.success(request, "Dados atualizados com sucesso.")
            return redirect("account_settings")

        elif action == "password":
            current_password = (request.POST.get("current_password") or "").strip()
            new_password1 = (request.POST.get("new_password1") or "").strip()
            new_password2 = (request.POST.get("new_password2") or "").strip()

            password_errors = {}

            if not current_password:
                password_errors["current_password"] = "Informe sua senha atual."
            elif not user.check_password(current_password):
                password_errors["current_password"] = "A senha atual está incorreta."

            if not new_password1:
                password_errors["new_password1"] = "Informe a nova senha."

            if not new_password2:
                password_errors["new_password2"] = "Confirme a nova senha."

            if new_password1 and new_password2 and new_password1 != new_password2:
                password_errors["new_password2"] = "As novas senhas não coincidem."

            if "new_password1" not in password_errors and "new_password2" not in password_errors and new_password1:
                try:
                    validate_password(new_password1, user=user)
                except ValidationError as e:
                    password_errors["new_password1"] = " ".join(e.messages)

            if password_errors:
                return render(request, "account_settings.html", {
                    "user_obj": user,
                    "profile": profile,
                    "password_errors": password_errors,
                    "form_data": {
                        "username": user.username,
                        "email": user.email,
                        "cpf": profile.cpf or "",
                    }
                })

            user.set_password(new_password1)
            user.save()
            update_session_auth_hash(request, user)

            messages.success(request, "Senha alterada com sucesso.")
            return redirect("account_settings")

    return render(request, "account_settings.html", {
        "user_obj": user,
        "profile": profile,
        "form_errors": {},
        "password_errors": {},
        "form_data": {
            "username": user.username,
            "email": user.email,
            "cpf": profile.cpf or "",
        }
    })

@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def lgpd_consent(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        if request.POST.get("accept_lgpd") == "1":
            profile.lgpd_accepted = True
            profile.lgpd_accepted_at = timezone.now()
            profile.save(update_fields=["lgpd_accepted", "lgpd_accepted_at"])

            messages.success(request, "Termo de privacidade aceito com sucesso.")
            return redirect("dashboard")

        messages.error(request, "Você precisa aceitar o termo para continuar.")
        return redirect("lgpd_consent")

    return render(request, "lgpd_consent.html", {
        "lgpd_text": """
Termo de Consentimento e Privacidade (LGPD)

Nós valorizamos a segurança dos seus dados pessoais e atuamos em total conformidade com a Lei Geral de Proteção de Dados (Lei nº 13.709/2018). Ao realizar este cadastro, coletamos informações essenciais, como nome e e-mail, com a finalidade exclusiva de identificar seu acesso, garantir a segurança da conta e viabilizar a prestação dos nossos serviços de forma personalizada e eficiente.

Informamos que seus dados serão armazenados em ambiente seguro e não serão compartilhados com terceiros para fins comerciais sem a sua autorização expressa. O tratamento desses dados perdurará apenas pelo período necessário para cumprir as finalidades descritas ou para o atendimento de obrigações legais e regulatórias, sendo garantido a você o direito de solicitar a exclusão das informações a qualquer momento.

Ao prosseguir e clicar no botão de finalização do cadastro, você declara estar ciente e concordar com o tratamento de seus dados pessoais nos termos aqui expostos. Ressaltamos que você possui o direito de acessar, corrigir ou revogar este consentimento mediante solicitação direta em nossos canais de atendimento, assegurando total transparência sobre o uso de sua privacidade.
        """.strip()
    })

def _must_accept_lgpd(user) -> bool:
    if not user.is_authenticated:
        return False

    profile, _ = UserProfile.objects.get_or_create(user=user)

    if not profile.lgpd_accepted or not profile.lgpd_accepted_at:
        return True

    limite = timezone.now() - timedelta(days=30)
    return profile.lgpd_accepted_at < limite

@login_required(login_url="login_admin")
@require_http_methods(["GET", "POST"])
def user_create(request):
    if not request.user.is_superuser:
        messages.error(request, "Você não tem permissão para criar usuários.")
        return redirect("dashboard")

    context = {
        "form_errors": {},
        "form_data": {},
    }

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        cpf = (request.POST.get("cpf") or "").strip()
        phone = (request.POST.get("phone") or "").strip()

        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        cpf_digits = _only_digits(cpf)

        errors = {}

        # =========================
        # VALIDAÇÕES
        # =========================

        if not username:
            errors["username"] = "Informe o nome completo."

        elif User.objects.filter(username__iexact=username).exists():
            errors["username"] = "Já existe um usuário com este nome."

        if not email:
            errors["email"] = "Informe o email."

        elif User.objects.filter(email__iexact=email).exists():
            errors["email"] = "Este email já está cadastrado."

        if not cpf:
            errors["cpf"] = "Informe o CPF."

        elif len(cpf_digits) != 11:
            errors["cpf"] = "CPF deve conter 11 dígitos."

        elif not _validate_cpf(cpf_digits):
            errors["cpf"] = "CPF inválido."

        elif UserProfile.objects.filter(cpf=cpf_digits).exists():
            errors["cpf"] = "Este CPF já está cadastrado."

        if not password1:
            errors["password1"] = "Informe a senha."

        if not password2:
            errors["password2"] = "Confirme a senha."

        if password1 and password2 and password1 != password2:
            errors["password2"] = "As senhas não coincidem."

        if password1 and password2 and password1 == password2:
            try:
                validate_password(password1)

            except ValidationError as e:
                errors["password1"] = " ".join(e.messages)

        # =========================
        # ERROS
        # =========================

        if errors:
            context["form_errors"] = errors

            context["form_data"] = {
                "username": username,
                "email": email,
                "cpf": cpf,
                "phone": phone,
            }

            return render(request, "users/user_create.html", context)

        # =========================
        # CRIA USUÁRIO
        # =========================

        try:
            with transaction.atomic():

                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password1,
                    is_active=True,
                )

                # separa nome
                partes = username.split(" ", 1)

                user.first_name = partes[0]
                user.last_name = partes[1] if len(partes) > 1 else ""

                # grupo requisitante
                grupo = Group.objects.filter(
                    name__iexact="requisitante"
                ).first()

                if grupo:
                    user.groups.add(grupo)

                user.save()

                # =========================
                # PERFIL
                # =========================

                profile, _ = UserProfile.objects.get_or_create(
                    user=user
                )

                profile.cpf = cpf_digits

                # TELEFONE
                if hasattr(profile, "phone"):
                    profile.phone = phone

                elif hasattr(profile, "telefone"):
                    profile.telefone = phone

                elif hasattr(profile, "celular"):
                    profile.celular = phone

                elif hasattr(profile, "whatsapp"):
                    profile.whatsapp = phone

                profile.save()

            messages.success(
                request,
                "Usuário criado com sucesso!"
            )

            return redirect("users_list")

        except Exception as e:

            context["form_errors"] = {
                "general": f"Erro ao criar usuário: {e}"
            }

            context["form_data"] = {
                "username": username,
                "email": email,
                "cpf": cpf,
                "phone": phone,
            }

            return render(
                request,
                "users/user_create.html",
                context
            )

    return render(
        request,
        "users/user_create.html",
        context
    )

@require_GET
def api_check_email_exists(request):
    email = (request.GET.get("email") or "").strip().lower()

    if not email:
        return JsonResponse(
            {"ok": False, "exists": False, "message": "Informe um email."},
            status=400
        )

    exists = User.objects.filter(email__iexact=email).exists()
    return JsonResponse({"ok": True, "exists": exists})

@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def os_delete(request, pk):
    os_obj = get_object_or_404(ServiceRequest, pk=pk)

    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para excluir esta O.S.")
        return redirect("dashboard_requisitante")

    # apaga anexos físicos, se existirem
    anexos = ServiceRequestAttachment.objects.filter(request=os_obj)
    for anexo in anexos:
        try:
            if anexo.file:
                anexo.file.delete(save=False)
        except Exception:
            pass

    numero_os = os_obj.os_number
    os_obj.delete()

    messages.success(request, f"O.S {numero_os} excluída com sucesso.")
    return redirect("os_list")

def _get_notification_target_users(notification):
    direct_ids = notification.users.values_list("id", flat=True)
    group_ids = User.objects.filter(
        groups__in=notification.target_groups.all(),
        is_active=True
    ).values_list("id", flat=True)

    ids = set(direct_ids) | set(group_ids)
    return User.objects.filter(id__in=ids, is_active=True).distinct()


def _create_notification(title, message, notification_type="MANUAL", users=None, groups=None, service_request=None, created_by=None, event_key=None):
    if event_key:
        existing = Notification.objects.filter(event_key=event_key).first()
        if existing:
            return existing, False

    notification = Notification.objects.create(
        title=title,
        message=message,
        notification_type=notification_type,
        service_request=service_request,
        created_by=created_by,
        event_key=event_key,
    )

    if users:
        notification.users.add(*users)

    if groups:
        notification.target_groups.add(*groups)

    return notification, True


def _get_internal_and_superusers():
    internos = User.objects.filter(
        groups__name__iexact="interno",
        is_active=True
    )

    supers = User.objects.filter(
        is_superuser=True,
        is_active=True
    )

    return User.objects.filter(
        id__in=list(internos.values_list("id", flat=True)) + list(supers.values_list("id", flat=True))
    ).distinct()

@login_required(login_url="login_admin")
def notifications_list(request):
    unread_subquery = NotificationRead.objects.filter(
        notification=OuterRef("pk"),
        user=request.user
    )

    notifications = (
        Notification.objects
        .filter(
            Q(users=request.user) |
            Q(target_groups__in=request.user.groups.all())
        )
        .exclude(
            hidden_by__user=request.user
        )
        .select_related("service_request", "service_request__team")
        .annotate(is_read=Exists(unread_subquery))
        .distinct()
        .order_by("-created_at")
    )

    if request.user.is_superuser:
        pass

    elif _is_requisitante(request.user):
        notifications = notifications.exclude(
            notification_type=Notification.TYPE_OPEN_10
        )

    elif _is_interno(request.user):
        team_ids = set()

        team_ids.update(
            Team.objects.filter(responsible=request.user)
            .values_list("id", flat=True)
        )

        team_ids.update(
            TeamMember.objects.filter(user=request.user)
            .values_list("team_id", flat=True)
        )

        notifications = notifications.filter(
            Q(notification_type=Notification.TYPE_DONE) |
            Q(notification_type=Notification.TYPE_MANUAL) |
            (
                Q(notification_type=Notification.TYPE_OPEN_10) &
                Q(service_request__team_id__in=team_ids)
            )
        )

    return render(request, "notifications/notifications_list.html", {
        "notifications": notifications,
    })

@login_required(login_url="login_admin")
def notification_mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk)

    can_view = (
        notification.users.filter(pk=request.user.pk).exists()
        or notification.target_groups.filter(id__in=request.user.groups.values_list("id", flat=True)).exists()
    )

    if not can_view:
        messages.error(request, "Você não tem permissão para acessar esta notificação.")
        return redirect("notifications_list")

    NotificationRead.objects.get_or_create(
        notification=notification,
        user=request.user,
    )

    messages.success(request, "Notificação marcada como lida.")
    return redirect("notifications_list")


@login_required(login_url="login_admin")
def notifications_mark_all_read(request):
    notifications = (
        Notification.objects
        .filter(
            Q(users=request.user) |
            Q(target_groups__in=request.user.groups.all())
        )
        .distinct()
    )

    existing_ids = set(
        NotificationRead.objects.filter(
            user=request.user,
            notification__in=notifications
        ).values_list("notification_id", flat=True)
    )

    to_create = [
        NotificationRead(notification=n, user=request.user)
        for n in notifications if n.id not in existing_ids
    ]

    if to_create:
        NotificationRead.objects.bulk_create(to_create)

    messages.success(request, "Todas as notificações foram marcadas como lidas.")
    return redirect("notifications_list")


@login_required(login_url="login_admin")
def notifications_create(request):
    if not request.user.is_superuser:
        messages.error(request, "Você não tem permissão para criar notificações.")
        return redirect("dashboard")

    if request.method == "POST":
        form = NotificationCreateForm(request.POST)
        if form.is_valid():
            notification = form.save(commit=False)
            notification.notification_type = "MANUAL"
            notification.created_by = request.user
            notification.save()

            form.save_m2m()

            messages.success(request, "Notificação criada com sucesso.")
            return redirect("notifications_list")
        else:
            messages.error(request, "Revise os campos e tente novamente.")
    else:
        form = NotificationCreateForm()

    return render(request, "notifications/notifications_create.html", {
        "form": form,
    })

@login_required(login_url="login_admin")
def api_notifications_dropdown(request):
    unread_subquery = NotificationRead.objects.filter(
        notification=OuterRef("pk"),
        user=request.user
    )

    notifications = (
        Notification.objects
        .filter(
            Q(users=request.user) |
            Q(target_groups__in=request.user.groups.all())
        )
        .select_related("service_request", "service_request__team")
        .annotate(is_read=Exists(unread_subquery))
        .distinct()
        .order_by("-created_at")[:8]
    )

    data = []
    for n in notifications:
        data.append({
            "id": n.id,
            "title": n.title or "Notificação",
            "message": n.message or "",
            "created_at": n.created_at.strftime("%d/%m/%Y %H:%M") if n.created_at else "",
            "is_read": bool(n.is_read),
            "read_url": reverse("notification_mark_read", args=[n.pk]),
        })

    return JsonResponse({"notifications": data})


@login_required(login_url="login_admin")
def report_os_search(request):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para acessar relatórios.")
        return redirect("dashboard_requisitante")

    ultimas_os = (
        ServiceRequest.objects
        .filter(status="DONE")
        .order_by("-created_at")[:15]
    )

    return render(request, "reports/os_report_search.html", {
        "ultimas_os": ultimas_os,
    })


@login_required(login_url="login_admin")
def report_os_download(request):
    if _is_requisitante(request.user):
        messages.error(request, "Você não tem permissão para gerar relatórios.")
        return redirect("dashboard_requisitante")

    os_number = (request.GET.get("os_number") or "").strip().upper()

    if not os_number:
        messages.error(request, "Informe o número da O.S.")
        return redirect("report_os_search")

    os_obj = (
        ServiceRequest.objects
        .select_related("team", "assigned_to", "created_by")
        .prefetch_related("attachments")
        .filter(os_number=os_number)
        .first()
    )

    if not os_obj:
        messages.error(request, "O.S não encontrada.")
        return redirect("report_os_search")

    anexos = list(os_obj.attachments.all())

    data_abertura = timezone.localtime(os_obj.created_at) if os_obj.created_at else None

    data_conclusao = None
    if os_obj.status == "DONE" and os_obj.status_updated_at:
        data_conclusao = timezone.localtime(os_obj.status_updated_at)

    prazo_estimado = None
    if os_obj.due_at:
        prazo_estimado = timezone.localtime(os_obj.due_at)

    dias_para_conclusao = "—"
    periodo_execucao = "—"

    if data_abertura and data_conclusao:
        total_dias = (data_conclusao.date() - data_abertura.date()).days
        total_dias = max(total_dias, 0)
        dias_para_conclusao = f"{total_dias} dia" if total_dias == 1 else f"{total_dias} dias"
        periodo_execucao = f"{total_dias} dia" if total_dias == 1 else f"{total_dias} dias"
        periodo_execucao += f" (de {data_abertura.strftime('%d/%m/%Y')} a {data_conclusao.strftime('%d/%m/%Y')})"
    elif os_obj.finished_in_days is not None:
        total_dias = int(os_obj.finished_in_days)
        dias_para_conclusao = f"{total_dias} dia" if total_dias == 1 else f"{total_dias} dias"
        periodo_execucao = dias_para_conclusao

    endereco = ", ".join([
        p for p in [
            os_obj.street,
            f"nº {os_obj.number}" if os_obj.number else "",
            os_obj.neighborhood,
            f"{os_obj.city}/SE" if os_obj.city else "",
        ] if p
    ]) or "—"

    responsavel = "—"
    if os_obj.assigned_to:
        responsavel = os_obj.assigned_to.get_full_name() or os_obj.assigned_to.username
    elif os_obj.team and os_obj.team.responsible:
        responsavel = os_obj.team.responsible.get_full_name() or os_obj.team.responsible.username

    equipe_responsavel = os_obj.team.name if os_obj.team else "—"

    foto_antes = anexos[0] if len(anexos) > 0 else None
    foto_depois = anexos[1] if len(anexos) > 1 else None

    contexto = {
        "os": os_obj,
        "data_emissao": timezone.localtime(),
        "data_abertura": data_abertura,
        "data_conclusao": data_conclusao,
        "dias_para_conclusao": dias_para_conclusao,
        "prazo_estimado": prazo_estimado,
        "periodo_execucao": periodo_execucao,
        "endereco": endereco,
        "bairro": os_obj.neighborhood or "—",
        "equipe_responsavel": equipe_responsavel,
        "responsavel": responsavel,
        "descricao_problema": os_obj.description or "—",
        "solucao_aplicada": os_obj.solution_taken or os_obj.notes or "—",
        "observacoes": os_obj.notes or "Serviço executado sem intercorrências.",
        "foto_antes": foto_antes,
        "foto_depois": foto_depois,
        "solicitante_nome": os_obj.full_name or "—",
        "solicitante_documento": os_obj.document or "—",
        "solicitante_telefone": os_obj.phone or "—",
    }

    html_string = render_to_string(
        "reports/os_report_pdf.html",
        contexto,
        request=request
    )

    pdf_file = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/")
    ).write_pdf()

    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="relatorio_{os_obj.os_number}.pdf"'
    return response

@login_required(login_url="login_admin")
def report_services_search(request):
    return render(request, "reports/report_services_search.html")


@login_required(login_url="login_admin")
def report_services_download(request):
    from datetime import datetime

    # ======================================
    # DADOS VINDOS DO FORMULÁRIO
    # ======================================
    data_inicio_str = request.GET.get("data_inicio")
    data_fim_str = request.GET.get("data_fim")

    sections = request.GET.getlist("sections")
    service_fields = request.GET.getlist("service_fields")
    region_fields = request.GET.getlist("region_fields")
    quantidade_regioes = request.GET.get("quantidade_regioes", "5")

    if not data_inicio_str or not data_fim_str:
        messages.error(request, "Selecione a data inicial e a data final do relatório.")
        return redirect("report_services_search")

    try:
        data_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d").date()
        data_fim = datetime.strptime(data_fim_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Período inválido. Selecione datas válidas.")
        return redirect("report_services_search")

    if data_inicio > data_fim:
        messages.error(request, "A data inicial não pode ser maior que a data final.")
        return redirect("report_services_search")

    # Caso nada venha selecionado, gera tudo por padrão
    if not sections:
        sections = [
            "todos_servicos",
            "media_tempo_atendimento",
            "total_os_periodo",
            "total_os_concluidas_prazo",
            "top_3_servicos_aberturas",
            "datas_maiores_aberturas",
            "grafico_total_aberturas_periodo",
            "servicos_maior_retorno_resolucao",
            "servicos_menor_retorno_resolucao",
            "tabela_regioes",
            "grafico_distribuicao_os_regiao",
            "media_resposta_os_regiao",
        ]

    if not service_fields:
        service_fields = [
            "quantidade_os_periodo",
            "prazo_estimado",
            "prazo_medio_real",
            "os_concluidas_dentro_prazo",
        ]

    if not region_fields:
        region_fields = [
            "total_os_aberta_regiao",
            "total_porcentagem",
            "top_3_servicos_requisitados_quantidade",
        ]

    titulo_periodo = f"DE {data_inicio.strftime('%d/%m/%Y')} ATÉ {data_fim.strftime('%d/%m/%Y')}"
    nome_arquivo = "relatorio_servicos_personalizado.pdf"

    # ======================================
    # QUERY BASE
    # ======================================
    qs = ServiceRequest.objects.filter(
        created_at__date__gte=data_inicio,
        created_at__date__lte=data_fim
    )

    total_os = qs.count()
    concluidas = qs.filter(status="DONE").count()

    media_tempo = (
        qs.filter(finished_in_days__isnull=False)
        .aggregate(media=Avg("finished_in_days"))
        .get("media") or 0
    )
    media_tempo = round(media_tempo, 1)

    # ======================================
    # FUNÇÃO AUXILIAR PARA PRAZO
    # ======================================
    def _calcular_prazo_servico(nome_servico):
        prazo = _get_service_type_deadline_days(nome_servico)
        return prazo if prazo is not None else 0

    def _os_dentro_do_prazo(os_obj):
        prazo_estimado = _calcular_prazo_servico(os_obj.service_type)

        if not prazo_estimado:
            return False

        if os_obj.finished_in_days is None:
            return False

        return int(os_obj.finished_in_days) <= int(prazo_estimado)

    # ======================================
    # TODOS OS SERVIÇOS / RANKING
    # ======================================
    ranking_qs = (
        qs.exclude(service_type__isnull=True)
        .exclude(service_type__exact="")
        .values("service_type")
        .annotate(total=Count("id"))
        .order_by("-total", "service_type")
    )

    ranking = []

    for item in ranking_qs:
        nome_servico = item["service_type"]
        total_servico = item["total"]

        percentual = round((total_servico / total_os) * 100, 1) if total_os else 0

        prazo_estimado = _calcular_prazo_servico(nome_servico)

        media_real = (
            qs.filter(
                service_type=nome_servico,
                finished_in_days__isnull=False
            )
            .aggregate(media=Avg("finished_in_days"))
            .get("media") or 0
        )
        media_real = round(media_real, 1)

        os_concluidas_servico = qs.filter(
            service_type=nome_servico,
            status="DONE"
        )

        total_concluidas_servico = os_concluidas_servico.count()

        dentro_prazo_count = 0
        for os_obj in os_concluidas_servico:
            if _os_dentro_do_prazo(os_obj):
                dentro_prazo_count += 1

        percentual_prazo_servico = round(
            (dentro_prazo_count / total_concluidas_servico) * 100, 1
        ) if total_concluidas_servico else 0

        ranking.append({
            "service_type": nome_servico,
            "total": total_servico,
            "percentual": percentual,
            "prazo_estimado": prazo_estimado,
            "media_real": media_real,
            "dentro_prazo_count": dentro_prazo_count,
            "percentual_prazo": percentual_prazo_servico,
        })

    top3 = ranking[:3]

    # ======================================
    # TOTAL DE O.S CONCLUÍDAS DENTRO DO PRAZO
    # ======================================
    total_concluidas_dentro_prazo = 0

    for os_obj in qs.filter(status="DONE", finished_in_days__isnull=False):
        if _os_dentro_do_prazo(os_obj):
            total_concluidas_dentro_prazo += 1

    percentual_prazo = round(
        (total_concluidas_dentro_prazo / concluidas) * 100, 1
    ) if concluidas else 0

    # ======================================
    # DATAS COM MAIORES ABERTURAS
    # ======================================
    maiores_datas = []

    datas_qs = (
        qs.annotate(data=TruncDate("created_at"))
        .values("data")
        .annotate(total=Count("id"))
        .order_by("-total", "data")[:5]
    )

    for item in datas_qs:
        servico_top = (
            qs.filter(created_at__date=item["data"])
            .exclude(service_type__isnull=True)
            .exclude(service_type__exact="")
            .values("service_type")
            .annotate(total=Count("id"))
            .order_by("-total", "service_type")
            .first()
        )

        maiores_datas.append({
            "data": item["data"],
            "total": item["total"],
            "servico": servico_top["service_type"] if servico_top else "—",
        })

    # ======================================
    # GRÁFICO DE ABERTURAS POR PERÍODO
    # ======================================
    aberturas_periodo = []

    aberturas_qs = (
        qs.annotate(data=TruncDate("created_at"))
        .values("data")
        .annotate(total=Count("id"))
        .order_by("data")
    )

    for item in aberturas_qs:
        aberturas_periodo.append({
            "data": item["data"],
            "total": item["total"],
        })

    # ======================================
    # MAIOR / MENOR RETORNO DE RESOLUÇÃO
    # ======================================
    melhores_servicos = []
    piores_servicos = []

    servicos_done = (
        qs.filter(status="DONE")
        .exclude(service_type__isnull=True)
        .exclude(service_type__exact="")
        .values("service_type")
        .annotate(
            total=Count("id"),
            media=Avg("finished_in_days")
        )
        .order_by("service_type")
    )

    for item in servicos_done:
        nome_servico = item["service_type"]

        total_servico_done = qs.filter(
            status="DONE",
            service_type=nome_servico
        ).count()

        dentro_prazo_count = 0

        for os_obj in qs.filter(
            status="DONE",
            service_type=nome_servico,
            finished_in_days__isnull=False
        ):
            if _os_dentro_do_prazo(os_obj):
                dentro_prazo_count += 1

        percentual_servico = round(
            (dentro_prazo_count / total_servico_done) * 100, 1
        ) if total_servico_done else 0

        dados_servico = {
            "service_type": nome_servico,
            "percentual_prazo": percentual_servico,
            "media_real": round(item["media"] or 0, 1),
        }

        melhores_servicos.append(dados_servico)
        piores_servicos.append(dados_servico)

    melhores_servicos = sorted(
        melhores_servicos,
        key=lambda x: x["percentual_prazo"],
        reverse=True
    )[:5]

    piores_servicos = sorted(
        piores_servicos,
        key=lambda x: x["percentual_prazo"]
    )[:5]

    # ======================================
    # REGIÕES
    # ======================================
    limite_regioes = None

    if quantidade_regioes != "all":
        try:
            limite_regioes = int(quantidade_regioes)
        except ValueError:
            limite_regioes = 5

    regioes_base = (
        qs.exclude(neighborhood__isnull=True)
        .exclude(neighborhood__exact="")
        .values("neighborhood")
        .annotate(total=Count("id"))
        .order_by("-total", "neighborhood")
    )

    if limite_regioes:
        regioes_base = regioes_base[:limite_regioes]

    regioes = []

    for regiao in regioes_base:
        nome_regiao = regiao["neighborhood"]
        total_regiao = regiao["total"]

        percentual_regiao = round(
            (total_regiao / total_os) * 100, 1
        ) if total_os else 0

        top_servicos_regiao_qs = (
            qs.filter(neighborhood=nome_regiao)
            .exclude(service_type__isnull=True)
            .exclude(service_type__exact="")
            .values("service_type")
            .annotate(total=Count("id"))
            .order_by("-total", "service_type")[:3]
        )

        top_servicos_regiao = []

        for servico in top_servicos_regiao_qs:
            top_servicos_regiao.append({
                "service_type": servico["service_type"],
                "total": servico["total"],
            })

        media_resposta_regiao = (
            qs.filter(
                neighborhood=nome_regiao,
                finished_in_days__isnull=False
            )
            .aggregate(media=Avg("finished_in_days"))
            .get("media") or 0
        )

        regioes.append({
            "nome": nome_regiao,
            "total": total_regiao,
            "percentual": percentual_regiao,
            "top_servicos": top_servicos_regiao,
            "media_resposta": round(media_resposta_regiao, 1),
        })

    # ======================================
    # DADOS DO USUÁRIO LOGADO
    # ======================================
    profile = UserProfile.objects.filter(user=request.user).first()

    nome_usuario = (
        f"{request.user.first_name} {request.user.last_name}".strip()
        or request.user.get_full_name()
        or request.user.username
    )

    cargo_usuario = getattr(profile, "cargo_funcao", "") if profile else ""
    setor_usuario = getattr(profile, "setor", "") if profile else ""

    # ======================================
    # CONTEXTO DO PDF
    # ======================================
    context = {
        "periodo": titulo_periodo,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "data_emissao": timezone.localtime(),

        "sections": sections,
        "service_fields": service_fields,
        "region_fields": region_fields,
        "quantidade_regioes": quantidade_regioes,

        "total_os": total_os,
        "concluidas": concluidas,
        "media_tempo": media_tempo,
        "percentual_prazo": percentual_prazo,
        "total_concluidas_dentro_prazo": total_concluidas_dentro_prazo,

        "ranking": ranking,
        "top3": top3,
        "maiores_datas": maiores_datas,
        "aberturas_periodo": aberturas_periodo,
        "melhores_servicos": melhores_servicos,
        "piores_servicos": piores_servicos,
        "regioes": regioes,

        "usuario_nome": nome_usuario,
        "usuario_cargo": cargo_usuario,
        "usuario_setor": setor_usuario,
    }

    html_string = render_to_string(
        "reports/report_services_pdf.html",
        context,
        request=request
    )

    pdf = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/")
    ).write_pdf()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response

@login_required(login_url="login_admin")
@require_POST
def service_type_update(request, pk):
    if not request.user.is_superuser:
        messages.error(request, "Você não tem permissão para editar tipos de serviço.")
        return redirect("dashboard")

    service_type = get_object_or_404(ServiceType, pk=pk)

    name = (request.POST.get("name") or "").strip()
    prazo_dias = (request.POST.get("prazo_dias") or "").strip()

    if not name:
        messages.error(request, "O nome do serviço é obrigatório.")
        return redirect("service_type_dashboard")

    if ServiceType.objects.filter(name__iexact=name).exclude(pk=service_type.pk).exists():
        messages.error(request, "Já existe um tipo de serviço com este nome.")
        return redirect("service_type_dashboard")

    service_type.name = name

    if prazo_dias != "":
        try:
            service_type.prazo_dias = int(prazo_dias)
        except ValueError:
            messages.error(request, "O prazo deve ser um número válido.")
            return redirect("service_type_dashboard")
    else:
        service_type.prazo_dias = None

    service_type.save()

    ServiceRequest.objects.filter(service_type_ref=service_type).update(
        service_type=service_type.name
    )

    messages.success(request, "Tipo de serviço atualizado com sucesso.")
    return redirect("service_type_dashboard")



@login_required(login_url="login_admin")
@require_http_methods(["POST"])
def notifications_clear_history(request):

    notifications = (
        Notification.objects.filter(
            Q(users=request.user)
            | Q(target_groups__in=request.user.groups.all())
        )
        .distinct()
    )

    hidden_existing_ids = set(
        NotificationHidden.objects.filter(
            user=request.user,
            notification__in=notifications
        ).values_list("notification_id", flat=True)
    )

    NotificationHidden.objects.bulk_create([
        NotificationHidden(
            notification=n,
            user=request.user
        )
        for n in notifications
        if n.id not in hidden_existing_ids
    ])

    messages.success(
        request,
        "Histórico limpo com sucesso."
    )

    return redirect("notifications_list")

@login_required(login_url="login_admin")
def help_page(request):
    whatsapp_number = getattr(settings, "HELP_WHATSAPP_NUMBER", "5579988459933")

    return render(request, "help_page.html", {
        "whatsapp_number": whatsapp_number,
    })