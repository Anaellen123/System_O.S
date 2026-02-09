from django.conf import settings
from django.db import models
from django.utils import timezone


class ServiceRequest(models.Model):
    PERSON_TYPE_CHOICES = [
        ("PF", "Pessoa Física"),
        ("PJ", "Pessoa Jurídica"),
    ]

    STATUS_CHOICES = [
        ("OPEN", "Aberto"),
        ("IN_PROGRESS", "Em andamento"),
        ("DONE", "Concluído"),
    ]

    # =========================
    # IDENTIFICAÇÃO DA OS (FASE FINAL - SEM NULL)
    # =========================
    os_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name="Número da OS",
    )

    # =========================
    # DADOS DO SOLICITANTE
    # =========================
    person_type = models.CharField(max_length=2, choices=PERSON_TYPE_CHOICES)
    document = models.CharField(max_length=18)  # CPF/CNPJ
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)

    # =========================
    # ENDEREÇO
    # =========================
    cep = models.CharField(max_length=9, blank=True)
    street = models.CharField(max_length=150, blank=True)
    number = models.CharField(max_length=20, blank=True)
    neighborhood = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)

    # =========================
    # SERVIÇO
    # =========================
    service_type = models.CharField(max_length=80)
    description = models.TextField()
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

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

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="OPEN")

    # =========================
    # GERAÇÃO AUTOMÁTICA DA OS
    # =========================
    def save(self, *args, **kwargs):
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

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.os_number} - {self.full_name}"


class ServiceRequestAttachment(models.Model):
    request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="attachments"
    )
    file = models.FileField(upload_to="service_requests/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attachment #{self.id} - Request #{self.request_id}"
