from django.urls import path
from . import views

urlpatterns = [
    # ===== PÁGINAS PÚBLICAS =====
    path("", views.index, name="index"),
    path("solicitar-servico/", views.solicitar_servico, name="solicitar_servico"),

    # ===== PÁGINAS INTERNAS ======
    path("equipe/", views.team_list, name="team_list"),
    path("equipe/nova/", views.team_create, name="team_create"),
    
    # ===== CADASTRO (PÚBLICO) =====
    path("register/", views.register, name="register"),

    # ===== AUTENTICAÇÃO =====
    path("login/", views.login_view, name="login_admin"),
    path("logout/", views.logout_view, name="logout"),

    # ===== DASHBOARD (ÁREA INTERNA) =====
    path("dashboard/", views.dashboard, name="dashboard"),

    # ===== USUÁRIOS (SOMENTE SUPERUSER) =====
    path("dashboard/usuarios/", views.users_list, name="users_list"),
    path("users/<int:user_id>/role/", views.user_role_update, name="user_role_update"),

    # ===== SOLICITAÇÕES / O.S =====
    path("dashboard/solicitacoes/", views.requests_list, name="requests_list"),
    path("dashboard/solicitacoes/<int:pk>/", views.request_detail, name="request_detail"),

    # ======= Nova O.S ===========
    path("dashboard/os/nova/", views.os_create, name="os_create"),

    # ====== Ordem de serviço ======
    path("dashboard/os/", views.os_list, name="os_list"),
    path("dashboard/os/status/<str:status>/", views.os_list, name="os_list_status"),

    # ====== EDIÇÃO DE O.S ====
    path("dashboard/os/<int:pk>/", views.os_detail, name="os_detail"),

    # ===== APIS =====
    path("api/cep/<str:cep>/", views.api_cep, name="api_cep"),
    path("api/validate-document/", views.api_validate_document, name="api_validate_document"),
    path("api/os-status/<str:os_number>/", views.api_os_status, name="api_os_status"),
    path("api/check-cpf/", views.api_check_cpf_exists, name="api_check_cpf_exists"),

    # ===== Users permissions ====
    path("usuarios/<int:user_id>/editar/", views.user_role_update, name="user_role_update"),
    path("meu-painel/", views.dashboard_requisitante, name="dashboard_requisitante"),


]