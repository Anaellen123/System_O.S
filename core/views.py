from datetime import timedelta
import json
from urllib.request import urlopen

from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
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
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views.decorators.http import require_http_methods, require_GET

from .forms import (
    ServiceRequestForm,
    ServiceRequestUpdateForm,
    UserRegisterForm,
    UserRoleForm,
    TeamCreateForm,
    ServiceTypeForm,
)
from .models import (
    ServiceRequest,
    ServiceRequestAttachment,
    UserProfile,
    Team,
    TeamMember,
    ServiceType,
)

User = get_user_model()

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

    if request.user.is_authenticated and _is_requisitante(request.user):
        perfil = UserProfile.objects.filter(user=request.user).first()
        nome_usuario = (
            request.user.get_full_name()
            or request.user.first_name
            or request.user.username
            or ""
        ).strip()
        cpf_usuario = _only_digits(getattr(perfil, "cpf", "") or "")

    if request.method == "POST":
        post_data = request.POST.copy()

        # Para requisitante, força nome e CPF com os dados do usuário logado
        if request.user.is_authenticated and _is_requisitante(request.user):
            post_data["full_name"] = nome_usuario
            post_data["document"] = cpf_usuario

        form = ServiceRequestForm(post_data, request.FILES)

        reg_email = (request.POST.get("reg_email") or "").strip().lower()
        reg_p1 = (request.POST.get("reg_password1") or "").strip()
        reg_p2 = (request.POST.get("reg_password2") or "").strip()

        if not form.is_valid():
            messages.error(request, "Revise os campos obrigatórios.")
            return render(request, "solicitar_servico.html", {
                "form": form,
                "created": False,
            })

        document_digits = _only_digits(form.cleaned_data.get("document") or "")

        user_to_link = request.user if request.user.is_authenticated else None

        if len(document_digits) == 11:
            cpf_qs = UserProfile.objects.filter(cpf=document_digits)

            if cpf_qs.exists():
                if user_to_link and user_to_link.is_authenticated:
                    prof = UserProfile.objects.filter(user=user_to_link).first()
                    if not prof or prof.cpf != document_digits:
                        messages.error(
                            request,
                            "Este CPF já possui cadastro em outra conta. Faça login com a conta correta para concluir."
                        )
                        return render(request, "solicitar_servico.html", {
                            "form": form,
                            "created": False
                        })
                else:
                    messages.error(
                        request,
                        "Este CPF já possui cadastro. Faça login para continuar."
                    )
                    return render(request, "solicitar_servico.html", {
                        "form": form,
                        "created": False
                    })

        created_new_user = False

        if not user_to_link:
            errors = []

            if not reg_email:
                errors.append("Informe um email para criar a conta.")
            if not reg_p1 or not reg_p2:
                errors.append("Informe e confirme a senha.")
            if reg_p1 and reg_p2 and reg_p1 != reg_p2:
                errors.append("As senhas não coincidem.")

            if reg_email and User.objects.filter(email__iexact=reg_email).exists():
                errors.append("Este email já está cadastrado. Faça login e tente novamente.")

            if reg_p1 and (reg_p1 == reg_p2):
                try:
                    validate_password(reg_p1)
                except ValidationError as e:
                    errors.append("Senha inválida: " + " ".join(e.messages))

            if errors:
                for e in errors:
                    messages.error(request, e)
                return render(request, "solicitar_servico.html", {
                    "form": form,
                    "created": False
                })

            try:
                with transaction.atomic():
                    username = _make_unique_username(reg_email)
                    user_to_link = User.objects.create_user(
                        username=username,
                        email=reg_email,
                        password=reg_p1,
                        is_active=False,
                    )

                    g = Group.objects.filter(name__iexact="requisitante").first()
                    if g:
                        user_to_link.groups.add(g)

                    profile, _ = UserProfile.objects.get_or_create(user=user_to_link)
                    if len(document_digits) == 11:
                        profile.cpf = document_digits
                        profile.save()

                    created_new_user = True

                _send_activation_email(request, user_to_link)

            except Exception as e:
                if user_to_link and user_to_link.pk:
                    user_to_link.delete()

                messages.error(
                    request,
                    f"Não foi possível enviar o email de ativação. Erro: {e}"
                )
                return render(request, "solicitar_servico.html", {
                    "form": form,
                    "created": False
                })

        obj = form.save(commit=False)

        if user_to_link:
            obj.created_by = user_to_link

            if request.user.is_authenticated and _is_requisitante(request.user):
                obj.full_name = nome_usuario
                obj.document = cpf_usuario

            if len(document_digits) == 11:
                prof = UserProfile.objects.filter(user=user_to_link).first()
                if prof and not prof.cpf:
                    prof.cpf = document_digits
                    prof.save()

        obj.save()

        for f in request.FILES.getlist("attachments"):
            ServiceRequestAttachment.objects.create(request=obj, file=f)

        if created_new_user:
            messages.success(
                request,
                "Solicitação criada com sucesso! Sua conta foi criada e enviamos um link de ativação para seu email."
            )

        form_limpo = ServiceRequestForm()

        if request.user.is_authenticated and _is_requisitante(request.user):
            form_limpo = ServiceRequestForm(initial={
                "full_name": nome_usuario,
                "document": cpf_usuario,
            })

        return render(request, "solicitar_servico.html", {
            "form": form_limpo,
            "created": True,
            "os_created": obj,
        })

    initial = {}

    if request.user.is_authenticated and _is_requisitante(request.user):
        initial = {
            "full_name": nome_usuario,
            "document": cpf_usuario,
        }

    form = ServiceRequestForm(initial=initial)

    return render(request, "solicitar_servico.html", {
        "form": form,
        "created": False,
    })

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
        return JsonResponse({"ok": False, "exists": False, "message": "CPF inválido."}, status=400)

    exists = UserProfile.objects.filter(cpf=cpf).exists()
    return JsonResponse({"ok": True, "exists": exists})

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

        u.is_active = bool(request.POST.get("is_active"))
        u.is_staff = bool(request.POST.get("is_staff"))
        u.is_superuser = bool(request.POST.get("is_superuser"))
        u.save()

        profile.cpf = _only_digits(request.POST.get("cpf") or "")

        birth = (request.POST.get("birth_date") or "").strip()
        profile.birth_date = birth or None

        profile.cep = (request.POST.get("cep") or "").strip()
        profile.street = (request.POST.get("street") or "").strip()
        profile.number = (request.POST.get("number") or "").strip()
        profile.neighborhood = (request.POST.get("neighborhood") or "").strip()
        profile.city = (request.POST.get("city") or "").strip()
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

    qs = User.objects.all().order_by("-date_joined")

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    return render(request, "users_list.html", {"users": qs, "q": q})


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

    stats = {
        "abertos": ServiceRequest.objects.filter(status="OPEN").count(),
        "andamento": ServiceRequest.objects.filter(status="IN_PROGRESS").count(),
        "concluidos": ServiceRequest.objects.filter(status="DONE").count(),
        "total": ServiceRequest.objects.count(),
    }

    recent = ServiceRequest.objects.order_by("-created_at")[:10]

    today = timezone.localdate()
    start = today - timedelta(days=89)

    daily = (
        ServiceRequest.objects
        .filter(created_at__date__gte=start, created_at__date__lte=today)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(c=Count("id"))
        .order_by("d")
    )

    counts_by_day = {row["d"]: row["c"] for row in daily}
    labels = []
    data = []
    for i in range(90):
        day = start + timedelta(days=i)
        labels.append(day.strftime("%d/%m"))
        data.append(counts_by_day.get(day, 0))

    bairros_qs = (
        ServiceRequest.objects
        .filter(city__icontains="socorro")
        .exclude(neighborhood__isnull=True)
        .exclude(neighborhood__exact="")
        .values("neighborhood")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    bairros_labels = [row["neighborhood"] for row in bairros_qs]
    bairros_data = [row["total"] for row in bairros_qs]

    return render(request, "dashboard.html", {
        "stats": stats,
        "recent": recent,
        "chart_labels": labels,
        "chart_data": data,
        "bairros_labels": bairros_labels,
        "bairros_data": bairros_data,
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

    cpf_usuario = _only_digits(getattr(perfil, "cpf", "") or "")

    if request.method == "POST":
        post_data = request.POST.copy()

        if eh_requisitante:
            post_data["full_name"] = nome_usuario
            post_data["document"] = cpf_usuario

        form = ServiceRequestForm(post_data, request.FILES)

        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user

            if eh_requisitante:
                obj.full_name = nome_usuario
                obj.document = cpf_usuario

            obj.save()

            for f in request.FILES.getlist("attachments"):
                ServiceRequestAttachment.objects.create(request=obj, file=f)

            messages.success(request, f"Ordem criada com sucesso: {obj.os_number}")
            return redirect("os_list")
        else:
            messages.error(request, "Revise os campos obrigatórios.")
    else:
        initial = {}

        if eh_requisitante:
            initial = {
                "full_name": nome_usuario,
                "document": cpf_usuario,
            }

        form = ServiceRequestForm(initial=initial)

    return render(request, "os_nova.html", {"form": form})

@login_required(login_url="login_admin")
def os_list(request, status=None):
    qs = ServiceRequest.objects.all().order_by("-created_at")

    if _is_requisitante(request.user):
        qs = qs.filter(created_by=request.user)

    if status and status != "todas":
        qs = qs.filter(status=status)

    get_status = request.GET.get("status")
    if get_status:
        qs = qs.filter(status=get_status)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(os_number__icontains=q)
            | Q(full_name__icontains=q)
            | Q(document__icontains=q)
            | Q(phone__icontains=q)
            | Q(neighborhood__icontains=q)
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
def os_detail(request, pk):
    os_obj = get_object_or_404(ServiceRequest, pk=pk)

    if _is_requisitante(request.user) and os_obj.created_by_id != request.user.id:
        messages.error(request, "Você não tem permissão para acessar esta OS.")
        return redirect("dashboard_requisitante")

    if request.method == "POST":
        if _is_requisitante(request.user):
            messages.error(request, "Você não tem permissão para editar esta OS.")
            return redirect("os_detail", pk=os_obj.pk)

        form = ServiceRequestUpdateForm(request.POST, instance=os_obj)
        if form.is_valid():
            os_edit = form.save(commit=False)

            prazo_dias = form.cleaned_data.get("prazo_dias")
            if prazo_dias is not None and str(prazo_dias).strip() != "":
                data_base = timezone.localtime(os_obj.created_at).date()
                os_edit.due_at = data_base + timedelta(days=int(prazo_dias))

            os_edit.save()
            form.save_m2m()

            messages.success(request, "OS atualizada com sucesso!")
            return redirect("os_detail", pk=os_obj.pk)
        else:
            messages.error(request, "Revise os campos e tente novamente.")
    else:
        form = ServiceRequestUpdateForm(instance=os_obj)

    prazo_formatado = _formatar_prazo_data(os_obj.created_at, os_obj.due_at)

    return render(request, "os_detail.html", {
        "os": os_obj,
        "form": form,
        "prazo_formatado": prazo_formatado,
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
            "message": "Este CPF já está cadastrado."
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

    if _is_requisitante(request.user) and os_obj.created_by_id != request.user.id:
        messages.error(request, "Você não tem permissão para acessar esta OS.")
        return redirect("dashboard_requisitante")

    if request.method == "POST":
        if _is_requisitante(request.user):
            messages.error(request, "Você não tem permissão para alterar o status desta OS.")
            return redirect("os_status_view", pk=os_obj.pk)

        novo_status = (request.POST.get("status") or "").strip()
        solution_taken = (request.POST.get("solution_taken") or "").strip()
        finished_in_days = (request.POST.get("finished_in_days") or "").strip()

        status_validos = [item[0] for item in ServiceRequest.STATUS_CHOICES]
        if novo_status not in status_validos:
            messages.error(request, "Status inválido.")
            return redirect("os_status_view", pk=os_obj.pk)

        if novo_status == "DONE":
            if not solution_taken:
                messages.error(request, "Preencha o campo Solução tomada para finalizar a O.S.")
                return redirect("os_status_view", pk=os_obj.pk)

            if not finished_in_days:
                messages.error(request, "Preencha em quantos dias a O.S foi finalizada.")
                return redirect("os_status_view", pk=os_obj.pk)

            try:
                finished_in_days_int = int(finished_in_days)
                if finished_in_days_int < 0:
                    raise ValueError
            except ValueError:
                messages.error(request, "O campo 'em quantos dias finalizou' deve ser um número válido.")
                return redirect("os_status_view", pk=os_obj.pk)

            os_obj.status = novo_status
            os_obj.solution_taken = solution_taken
            os_obj.finished_in_days = finished_in_days_int
            os_obj.save(update_fields=["status", "solution_taken", "finished_in_days"])

            messages.success(request, "Status da OS atualizado com sucesso!")
            return redirect("os_status_view", pk=os_obj.pk)

        os_obj.status = novo_status
        os_obj.solution_taken = None
        os_obj.finished_in_days = None
        os_obj.save(update_fields=["status", "solution_taken", "finished_in_days"])

        messages.success(request, "Status da OS atualizado com sucesso!")
        return redirect("os_status_view", pk=os_obj.pk)

    prazo_formatado = _formatar_prazo_data(os_obj.created_at, os_obj.due_at)
    endereco_completo = _montar_endereco_os(os_obj)
    anexos = _obter_anexos_os(os_obj)
    observacoes = _obter_observacoes_os(os_obj)

    return render(request, "os/os_status_view.html", {
        "os": os_obj,
        "prazo_formatado": prazo_formatado or "—",
        "endereco_completo": endereco_completo or "—",
        "anexos": anexos,
        "observacoes": observacoes or "—",
        "status_choices": ServiceRequest.STATUS_CHOICES,
    })


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

            if not nome:
                messages.error(request, "Informe o nome do tipo de serviço.")
            elif ServiceType.objects.filter(name__iexact=nome).exists():
                messages.error(request, "Já existe um tipo de serviço com este nome.")
            else:
                obj = form.save(commit=False)
                obj.name = nome

                if hasattr(obj, "is_active"):
                    obj.is_active = True

                obj.save()
                messages.success(request, "Tipo de serviço cadastrado com sucesso.")
                return redirect("service_type_dashboard")
        else:
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
        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        cpf_digits = _only_digits(cpf)

        errors = {}

        # validações
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

        if errors:
            context["form_errors"] = errors
            context["form_data"] = {
                "username": username,
                "email": email,
                "cpf": cpf,
            }
            return render(request, "users/user_create.html", context)

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

                # adiciona ao grupo requisitante (SEM get_or_create)
                grupo = Group.objects.filter(name__iexact="requisitante").first()
                if grupo:
                    user.groups.add(grupo)

                user.save()

                # cria perfil
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.cpf = cpf_digits
                profile.save()

            messages.success(request, "Usuário criado com sucesso!")
            return redirect("users_list")

        except Exception as e:
            context["form_errors"] = {
                "general": f"Erro ao criar usuário: {e}"
            }
            context["form_data"] = {
                "username": username,
                "email": email,
                "cpf": cpf,
            }
            return render(request, "users/user_create.html", context)

    return render(request, "users/user_create.html", context)

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