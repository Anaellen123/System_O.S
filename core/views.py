from datetime import timedelta
import json
from urllib.request import urlopen

from django.conf import settings
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
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)

        reg_email = (request.POST.get("reg_email") or "").strip().lower()
        reg_p1 = (request.POST.get("reg_password1") or "").strip()
        reg_p2 = (request.POST.get("reg_password2") or "").strip()

        if not form.is_valid():
            messages.error(request, "Revise os campos obrigatórios.")
            return render(request, "solicitar_servico.html", {
                "form": form,
                "created": False,
            })

        person_type = (form.cleaned_data.get("person_type") or "").strip()
        document_digits = _only_digits(form.cleaned_data.get("document") or "")

        user_to_link = request.user if request.user.is_authenticated else None

        if person_type == "PF" and len(document_digits) == 11:
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
                    if person_type == "PF" and len(document_digits) == 11:
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

            if person_type == "PF" and len(document_digits) == 11:
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

        return render(request, "solicitar_servico.html", {
            "form": ServiceRequestForm(),
            "created": True,
            "os_created": obj,
        })

    form = ServiceRequestForm()
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

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password1 = (request.POST.get("password1") or "").strip()
        password2 = (request.POST.get("password2") or "").strip()

        errors = []

        if not username:
            errors.append("Informe um usuário.")
        if not email:
            errors.append("Informe um email.")
        if not password1 or not password2:
            errors.append("Informe e confirme a senha.")
        if password1 and password2 and password1 != password2:
            errors.append("As senhas não coincidem.")

        if username and User.objects.filter(username__iexact=username).exists():
            errors.append("Este usuário já existe.")
        if email and User.objects.filter(email__iexact=email).exists():
            errors.append("Este email já está cadastrado.")

        if password1 and password1 == password2:
            try:
                validate_password(password1)
            except ValidationError as e:
                errors.extend(e.messages)

        if errors:
            for e in errors:
                messages.error(request, e)

            return render(request, "login_admin.html", {
                "show_register": True,
                "register_data": {"username": username, "email": email},
            })

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password1,
                    is_active=False,
                )

                g = Group.objects.filter(name__iexact="requisitante").first()
                if g:
                    user.groups.add(g)

                UserProfile.objects.get_or_create(user=user)

            _send_activation_email(request, user)

            messages.success(
                request,
                "Conta criada com sucesso! Enviamos um link de ativação para seu email."
            )
            return redirect("login_admin")

        except Exception as e:
            try:
                user.delete()
            except Exception:
                pass

            messages.error(
                request,
                f"Não foi possível enviar o email de ativação. Erro: {e}"
            )
            return render(request, "login_admin.html", {
                "show_register": True,
                "register_data": {"username": username, "email": email},
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

    email = (request.POST.get("email") or "").strip().lower()
    print("EMAIL RECEBIDO PARA RECUPERAÇÃO:", email)

    if not email:
        messages.error(request, "Informe seu email.")
        return render(request, "login_admin.html", {
            "show_forgot": True,
        })

    user = User.objects.filter(email__iexact=email).first()
    print("USUÁRIO ENCONTRADO:", user)

    if not user:
        messages.error(request, "Nenhum usuário foi encontrado com este email.")
        return render(request, "login_admin.html", {
            "show_forgot": True,
        })

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    reset_path = reverse("reset_password_confirm", kwargs={
        "uidb64": uid,
        "token": token,
    })
    reset_link = request.build_absolute_uri(reset_path)

    print("LINK DE RECUPERAÇÃO GERADO:", reset_link)

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
        resultado = send_mail(
            subject,
            message,
            from_email,
            [user.email],
            fail_silently=False,
        )
        print("EMAIL ENVIADO COM SUCESSO. RESULTADO =", resultado)
        messages.success(request, "Enviamos o link de recuperação para seu email.")
        return redirect("login_admin")

    except Exception as e:
        print("ERRO AO ENVIAR EMAIL:", repr(e))
        messages.error(
            request,
            f"Não foi possível enviar o email de recuperação. Erro: {e}"
        )
        return render(request, "login_admin.html", {
            "show_forgot": True,
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
    list(messages.get_messages(request))

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username_or_email = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()

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
                messages.error(request, "Sua conta ainda não foi ativada por email.")
                return render(request, "login_admin.html")

            messages.error(request, "Usuário ou senha inválidos.")
            return render(request, "login_admin.html")

        login(request, user)
        return redirect("dashboard")

    return render(request, "login_admin.html")


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
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()

            for f in request.FILES.getlist("attachments"):
                ServiceRequestAttachment.objects.create(request=obj, file=f)

            messages.success(request, f"Ordem criada com sucesso: {obj.os_number}")
            return redirect("os_list")
        else:
            messages.error(request, "Revise os campos obrigatórios.")
    else:
        form = ServiceRequestForm()

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


def _validate_cnpj(cnpj: str) -> bool:
    cnpj = _only_digits(cnpj)
    if len(cnpj) != 14 or _is_repeated_digits(cnpj):
        return False

    nums = list(map(int, cnpj))

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1

    s1 = sum(nums[i] * w1[i] for i in range(12))
    d1 = 11 - (s1 % 11)
    d1 = 0 if d1 >= 10 else d1
    if d1 != nums[12]:
        return False

    s2 = sum(nums[i] * w2[i] for i in range(13))
    d2 = 11 - (s2 % 11)
    d2 = 0 if d2 == 10 else d2
    return d2 == nums[13]


@require_GET
def api_validate_document(request):
    value = request.GET.get("value", "")
    digits = _only_digits(value)

    if len(digits) == 11:
        ok = _validate_cpf(digits)
        doc_type = "CPF"
    elif len(digits) == 14:
        ok = _validate_cnpj(digits)
        doc_type = "CNPJ"
    else:
        return JsonResponse({
            "ok": False,
            "type": None,
            "message": "Digite um CPF (11 dígitos) ou CNPJ (14 dígitos)."
        }, status=400)

    return JsonResponse({
        "ok": ok,
        "type": doc_type,
        "message": "Documento válido." if ok else f"{doc_type} inválido."
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

        status_validos = [item[0] for item in ServiceRequest.STATUS_CHOICES]
        if novo_status not in status_validos:
            messages.error(request, "Status inválido.")
            return redirect("os_status_view", pk=os_obj.pk)

        os_obj.status = novo_status
        os_obj.save(update_fields=["status"])

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