from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Q

from .forms import ServiceRequestForm
from .models import ServiceRequest, ServiceRequestAttachment

from datetime import timedelta
from django.utils import timezone
from django.db.models.functions import TruncDate
from django.db.models import Count


def index(request):
    return render(request, "index.html")


def solicitar_servico(request):
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)

        if form.is_valid():
            obj = form.save(commit=False)

            if request.user.is_authenticated:
                obj.created_by = request.user

            obj.save()

            for f in request.FILES.getlist("attachments"):
                ServiceRequestAttachment.objects.create(request=obj, file=f)

            messages.success(request, "Solicitação enviada com sucesso!")
            return redirect("solicitar_servico")
        else:
            messages.error(request, "Revise os campos obrigatórios.")
    else:
        form = ServiceRequestForm()

    return render(request, "solicitar_servico.html", {"form": form})


# -----------------------------
# LOGIN / LOGOUT (usuário interno)
# -----------------------------
@require_http_methods(["GET", "POST"])
def login_view(request):
    # Se já estiver logado, manda pro dashboard
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
        # pós-login → dashboard
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

    # ===== gráfico (últimos 90 dias) =====
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

    # lista completa de datas (pra não “pular” dias sem dados)
    counts_by_day = {row["d"]: row["c"] for row in daily}
    labels = []
    data = []
    for i in range(90):
        day = start + timedelta(days=i)
        labels.append(day.strftime("%d/%m"))
        data.append(counts_by_day.get(day, 0))

    return render(request, "dashboard.html", {
        "stats": stats,
        "recent": recent,
        "chart_labels": labels,
        "chart_data": data,
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


@login_required(login_url="login_admin")
def os_create(request):
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()

            # se você usa anexos:
            for f in request.FILES.getlist("attachments"):
                ServiceRequestAttachment.objects.create(request=obj, file=f)

            messages.success(request, f"Ordem criada com sucesso: {obj.os_number}")
            return redirect("dashboard")  # ou redirect("requests_list")
        else:
            messages.error(request, "Revise os campos obrigatórios.")
    else:
        form = ServiceRequestForm()

    return render(request, "os_nova.html", {"form": form})
