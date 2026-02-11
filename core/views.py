from datetime import timedelta
import json
from urllib.request import urlopen

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_GET

from .forms import ServiceRequestForm, ServiceRequestUpdateForm
from .models import ServiceRequest, ServiceRequestAttachment


def index(request):
    return render(request, "index.html")


def solicitar_servico(request):
    """
    Página pública para criar solicitação.
    Correção aplicada:
    - REMOVIDO messages.success() para não "vazar" e aparecer no login_admin.html
      (você já mostra o modal via created=True + os_created)
    """
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)

        if form.is_valid():
            obj = form.save(commit=False)

            if request.user.is_authenticated:
                obj.created_by = request.user

            obj.save()

            # Salvar anexos
            for f in request.FILES.getlist("attachments"):
                ServiceRequestAttachment.objects.create(request=obj, file=f)

            # ✅ REMOVIDO: isso fazia a mensagem aparecer no login depois
            # messages.success(request, "Solicitação enviada com sucesso!")

            # Renderiza o mesmo template com flags de sucesso
            # para abrir o modal e gerar/baixar o comprovante (JS)
            return render(request, "solicitar_servico.html", {
                "form": ServiceRequestForm(),  # formulário limpo
                "created": True,               # o JS usa isso (window.OS_CREATED)
                "os_created": obj,             # dados da OS para preencher o comprovante
            })

        # Mantém erro só na própria página do formulário
        messages.error(request, "Revise os campos obrigatórios.")
        return render(request, "solicitar_servico.html", {
            "form": form,
            "created": False,
        })

    # GET
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

    # label amigável do status (Aberto/Em andamento/Concluído)
    status_label = dict(ServiceRequest.STATUS_CHOICES).get(obj.status, obj.status)

    return JsonResponse({
        "ok": True,
        "os_number": obj.os_number,
        "status": obj.status,              # OPEN / IN_PROGRESS / DONE
        "status_label": status_label,      # Aberto / Em andamento / Concluído
        "service_type": obj.service_type,
        "created_at": obj.created_at.strftime("%d/%m/%Y %H:%M"),
    })


# -----------------------------
# LOGIN / LOGOUT (usuário interno)
# -----------------------------
@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Correção aplicada:
    - Limpamos mensagens antigas ao abrir o login (ex: sucesso do formulário público),
      e assim elas não aparecem no login_admin.html.
    - Mantém as mensagens de erro quando o usuário erra senha.
    """
    # ✅ limpa mensagens antigas "penduradas" na sessão
    list(messages.get_messages(request))

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is None:
            messages.error(request, "Usuário ou senha inválidos.")
            return render(request, "login_admin.html")

        login(request, user)
        return redirect("dashboard")

    return render(request, "login_admin.html")


def logout_view(request):
    logout(request)
    return redirect("login_admin")


# -----------------------------
# DASHBOARD (protegido)
# -----------------------------
@login_required(login_url="login_admin")
def dashboard(request):
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

    # =========================
    # ✅ OS por BAIRRO (Socorro/SE)
    # =========================
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


# -----------------------------
# SOLICITAÇÕES (protegido)
# -----------------------------
@login_required(login_url="login_admin")
def requests_list(request):
    qs = ServiceRequest.objects.all().order_by("-created_at")

    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(document__icontains=q)
            | Q(phone__icontains=q)
        )

    return render(request, "requests_list.html", {"requests": qs})


@login_required(login_url="login_admin")
def request_detail(request, pk):
    obj = get_object_or_404(ServiceRequest, pk=pk)
    return render(request, "request_detail.html", {"obj": obj})


# -----------------------------
# CRIAR OS (protegido)
# -----------------------------
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


# -----------------------------
# LISTAGEM DE OS (protegido)
# -----------------------------
@login_required(login_url="login_admin")
def os_list(request, status=None):
    qs = ServiceRequest.objects.all().order_by("-created_at")

    if status and status != "todas":
        qs = qs.filter(status=status)

    get_status = request.GET.get("status")
    if get_status:
        qs = qs.filter(status=get_status)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(os_number__icontains=q)
            | Q(full_name__icontains=q)
            | Q(document__icontains=q)
            | Q(phone__icontains=q)
        )

    total = ServiceRequest.objects.count()
    ativas = ServiceRequest.objects.exclude(status="DONE").count()

    vencidas = ServiceRequest.objects.filter(
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


# -----------------------------
# DETALHE / EDIÇÃO DA OS (protegido)
# -----------------------------
@login_required(login_url="login_admin")
def os_detail(request, pk):
    os_obj = get_object_or_404(ServiceRequest, pk=pk)

    if request.method == "POST":
        form = ServiceRequestUpdateForm(request.POST, instance=os_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "OS atualizada com sucesso!")
            return redirect("os_detail", pk=os_obj.pk)
        else:
            messages.error(request, "Revise os campos e tente novamente.")
    else:
        form = ServiceRequestUpdateForm(instance=os_obj)

    return render(request, "os_detail.html", {"os": os_obj, "form": form})


# -----------------------------
# API CEP
# -----------------------------
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


# -----------------------------
# VALIDAÇÃO CPF/CNPJ (API)
# -----------------------------
def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


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
    d2 = 0 if d2 >= 10 else d2
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
