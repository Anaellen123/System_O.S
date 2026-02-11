from django.urls import path
from . import views

urlpatterns = [
    # ===== PÁGINAS PÚBLICAS =====
    path("", views.index, name="index"),
    path("solicitar-servico/", views.solicitar_servico, name="solicitar_servico"),

    # ===== AUTENTICAÇÃO =====
    path("login/", views.login_view, name="login_admin"),
    path("logout/", views.logout_view, name="logout"),
    


    # ===== DASHBOARD (ÁREA INTERNA) =====
    path("dashboard/", views.dashboard, name="dashboard"),

    # ===== SOLICITAÇÕES / O.S =====
    path("dashboard/solicitacoes/", views.requests_list, name="requests_list"),
    path(
        "dashboard/solicitacoes/<int:pk>/",
        views.request_detail,
        name="request_detail",
    ),

    # ======= Nova O.S ===========
    path("dashboard/os/nova/", views.os_create, name="os_create"),

    # ====== Ordem de serviço ======
    path("dashboard/os/", views.os_list, name="os_list"),
    path("dashboard/os/status/<str:status>/", views.os_list, name="os_list_status"),

    # ======= api cep =====
    path("api/cep/<str:cep>/", views.api_cep, name="api_cep"),

    # ===== api CNPJ/CPF =====
    path("api/validate-document/", views.api_validate_document, name="api_validate_document"),

    # ====== EDIÇÃO DE O.S ====
     path("dashboard/os/<int:pk>/", views.os_detail, name="os_detail"),

    # ==== status de O.S =====
     path("api/os-status/<str:os_number>/", views.api_os_status, name="api_os_status"),
]
