from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

import os
import uuid


User = get_user_model()


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    cpf = models.CharField(max_length=14, blank=True, null=True, unique=True)
    birth_date = models.DateField(blank=True, null=True)

    cep = models.CharField(max_length=9, blank=True)
    street = models.CharField(max_length=150, blank=True)
    number = models.CharField(max_length=20, blank=True)
    neighborhood = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # LGPD
    lgpd_accepted = models.BooleanField(default=False)
    lgpd_accepted_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Perfil - {self.user.username}"


def validate_image_type(file):
    allowed = ["image/jpeg", "image/png"]
    content_type = getattr(file, "content_type", None)

    ext = os.path.splitext(file.name)[1].lower()

    if content_type and content_type not in allowed:
        raise ValidationError("Envie apenas imagens JPG ou PNG.")

    if ext not in [".jpg", ".jpeg", ".png"]:
        raise ValidationError("Envie apenas imagens JPG ou PNG.")


def attachment_upload_to(instance, filename):
    os_number = instance.request.os_number
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".jpeg":
        ext = ".jpg"

    new_name = f"{uuid.uuid4().hex}{ext}"
    return f"service_requests/{os_number}/{new_name}"


class ServiceType(models.Model):
    name = models.CharField("Nome do serviço", max_length=120, unique=True)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Tipo de serviço"
        verbose_name_plural = "Tipos de serviço"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Team(models.Model):
    PRIORITY_LOW = "LOW"
    PRIORITY_MEDIUM = "MEDIUM"
    PRIORITY_HIGH = "HIGH"
    PRIORITY_URGENT = "URGENT"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Baixa"),
        (PRIORITY_MEDIUM, "Média"),
        (PRIORITY_HIGH, "Alta"),
        (PRIORITY_URGENT, "Urgente"),
    ]

    name = models.CharField(max_length=120, unique=True)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teams_responsible",
    )

    function_description = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ServiceRequest(models.Model):
    PERSON_TYPE_CHOICES = [
        ("PF", "Pessoa Física"),
        ("PJ", "Pessoa Jurídica"),
    ]

    STATUS_CHOICES = [
        ("OPEN", "Pendente"),
        ("IN_PROGRESS", "Em andamento"),
        ("DONE", "Concluído"),
    ]

    os_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name="Número da OS",
    )

    solution_taken = models.TextField("Solução tomada", blank=True, null=True)
    finished_in_days = models.PositiveIntegerField("Finalizado em quantos dias", blank=True, null=True)
    person_type = models.CharField(max_length=2, choices=PERSON_TYPE_CHOICES)
    document = models.CharField(max_length=18)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)

    cep = models.CharField(max_length=9, blank=True)
    street = models.CharField(max_length=150, blank=True)
    number = models.CharField(max_length=20, blank=True)
    neighborhood = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)

    service_type = models.CharField(max_length=80)
    description = models.TextField()
    notes = models.TextField(blank=True)

    due_at = models.DateTimeField("Prazo", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    status_updated_at = models.DateTimeField("Atualizado status em", null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests_created",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests_assigned",
    )

    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
        verbose_name="Equipe",
    )

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="OPEN")

    class Meta:
        permissions = [
            ("tab_dashboard", "Pode visualizar a aba Dashboard"),
            ("tab_users", "Pode visualizar a aba Usuários"),
            ("tab_requests", "Pode visualizar a aba Solicitações"),
            ("tab_os", "Pode visualizar a aba Ordens de Serviço"),
            ("tab_reports", "Pode visualizar a aba Relatórios"),
            ("tab_team", "Pode visualizar a aba Equipe"),
            ("manage_users", "Pode gerenciar usuários (editar níveis/perfis)"),
            ("manage_os", "Pode gerenciar OS (criar/editar)"),
            ("assign_os", "Pode atribuir OS para responsáveis"),
            ("change_os_status", "Pode alterar status da OS"),
            ("manage_team", "Pode gerenciar Equipes (criar/editar/remover)"),
        ]

    def save(self, *args, **kwargs):
        is_new = not self.pk
        old_status = None

        if not is_new:
            old_status = (
                ServiceRequest.objects
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )

        if not self.os_number:
            today = timezone.localdate()
            date_str = today.strftime("%Y%m%d")
            prefix = f"OS-{date_str}-"

            last = (
                ServiceRequest.objects
                .filter(os_number__startswith=prefix)
                .order_by("-os_number")
                .values_list("os_number", flat=True)
                .first()
            )

            seq = int(last.split("-")[-1]) + 1 if last else 1
            self.os_number = f"{prefix}{seq:04d}"

        if is_new and not self.status_updated_at:
            self.status_updated_at = timezone.now()
        elif old_status and old_status != self.status:
            self.status_updated_at = timezone.now()
        elif not self.status_updated_at:
            self.status_updated_at = timezone.now()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.os_number} - {self.full_name}"


class ServiceRequestAttachment(models.Model):
    request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="attachments"
    )

    file = models.FileField(
        upload_to=attachment_upload_to,
        validators=[validate_image_type],
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Anexo {self.id} - {self.request.os_number}"


class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("team", "user")

    def __str__(self):
        return f"{self.team} - {self.user}"


class Notification(models.Model):
    TYPE_OPEN_10 = "OPEN_10"
    TYPE_PROGRESS_15 = "IN_PROGRESS_15"
    TYPE_DONE = "DONE"
    TYPE_MANUAL = "MANUAL"

    TYPE_CHOICES = [
        (TYPE_OPEN_10, "O.S pendente há 10 dias"),
        (TYPE_PROGRESS_15, "O.S em andamento há 15 dias"),
        (TYPE_DONE, "O.S concluída"),
        (TYPE_MANUAL, "Manual"),
    ]

    title = models.CharField("Título", max_length=180)
    message = models.TextField("Mensagem")
    notification_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_MANUAL,
    )

    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="notifications",
        blank=True,
    )

    target_groups = models.ManyToManyField(
        Group,
        related_name="notifications",
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_created",
    )

    event_key = models.CharField(max_length=120, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class NotificationRead(models.Model):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="reads",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_reads",
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("notification", "user")

    def __str__(self):
        return f"{self.user} leu {self.notification}"