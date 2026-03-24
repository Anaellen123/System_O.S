from django.urls import path
from . import views

urlpatterns = [
    # ===== PÁGINAS PÚBLICAS =====
    path("", views.index, name="index"),
    path("solicitar-servico/", views.solicitar_servico, name="solicitar_servico"),

    # ===== PÁGINAS INTERNAS =====
    path("equipe/", views.team_list, name="team_list"),
    path("equipe/nova/", views.team_create, name="team_create"),
    path("equipe/<int:team_id>/editar/", views.team_update, name="team_update"),
    path("equipe/<int:team_id>/excluir/", views.team_delete, name="team_delete"),
    path("equipe/minha/", views.team_my, name="team_my"),
    path("equipe/<int:team_id>/os/<int:os_id>/remover/", views.team_remove_os, name="team_remove_os"),

    # ===== CADASTRO (PÚBLICO) =====
    path("register/", views.register, name="register"),
    path("ativar-conta/<uidb64>/<token>/", views.activate_account, name="activate_account"),

    # ===== AUTENTICAÇÃO =====
    path("login/", views.login_view, name="login_admin"),
    path("logout/", views.logout_view, name="logout"),
    path("esqueci-senha/", views.forgot_password_request, name="forgot_password"),
    path("redefinir-senha/<uidb64>/<token>/", views.reset_password_confirm, name="reset_password_confirm"),
    
    # ===== DASHBOARD (ÁREA INTERNA) =====
    path("dashboard/", views.dashboard, name="dashboard"),
    path("minhas-os/", views.team_my, name="team_my"),
    path("minha-equipe/relatorio/", views.team_my_report, name="team_my_report"),
    

    # ===== USUÁRIOS (SOMENTE SUPERUSER) =====
    path("dashboard/usuarios/", views.users_list, name="users_list"),
    path("users/<int:user_id>/role/", views.user_role_update, name="user_role_update"),

    # ===== SOLICITAÇÕES / O.S =====
    path("dashboard/solicitacoes/", views.requests_list, name="requests_list"),
    path("dashboard/solicitacoes/<int:pk>/", views.request_detail, name="request_detail"),

    # ===== NOVA O.S =====
    path("dashboard/os/nova/", views.os_create, name="os_create"),

    # ===== ORDEM DE SERVIÇO =====
    path("dashboard/os/", views.os_list, name="os_list"),
    path("dashboard/os/status/<str:status>/", views.os_list, name="os_list_status"),

    # ===== EDIÇÃO / DETALHE DE O.S =====
    path("dashboard/os/<int:pk>/", views.os_detail, name="os_detail"),
    path("os/<int:pk>/visualizar/", views.os_status_view, name="os_status_view"),

    # ===== APIS =====
    path("api/cep/<str:cep>/", views.api_cep, name="api_cep"),
    path("api/validate-document/", views.api_validate_document, name="api_validate_document"),
    path("api/os-status/<str:os_number>/", views.api_os_status, name="api_os_status"),
    path("api/check-cpf/", views.api_check_cpf_exists, name="api_check_cpf_exists"),

    # ===== USERS PERMISSIONS =====
    path("usuarios/<int:user_id>/editar/", views.user_role_update, name="user_role_update"),
    path("usuarios/<int:user_id>/excluir/", views.user_delete, name="user_delete"),

    # ===== DASHBOARD REQUISITANTE =====
    path("meu-painel/", views.dashboard_requisitante, name="dashboard_requisitante"),

    # === Impressões =======
    path("os/<int:pk>/imprimir/", views.os_print, name="os_print"),
]