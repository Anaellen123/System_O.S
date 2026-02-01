from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('solicitar-servico/', views.solicitar_servico, name='solicitar_servico'),
    path('login-admin/', views.login_admin, name='login_admin'),
]
