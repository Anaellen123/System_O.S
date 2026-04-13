from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import ServiceRequest, Notification

User = get_user_model()


class Command(BaseCommand):
    help = "Envia notificações automáticas de O.S pendentes/em andamento"

    def handle(self, *args, **options):
        agora = timezone.now()

        internos = User.objects.filter(
            groups__name__iexact="interno",
            is_active=True
        )

        supers = User.objects.filter(
            is_superuser=True,
            is_active=True
        )

        destinatarios = User.objects.filter(
            id__in=list(internos.values_list("id", flat=True)) + list(supers.values_list("id", flat=True))
        ).distinct()

        # OPEN há 10 dias
        open_limit = agora - timedelta(days=10)
        os_open = ServiceRequest.objects.filter(
            status="OPEN",
            status_updated_at__lte=open_limit
        )

        for os_obj in os_open:
            event_key = f"os_open_10_{os_obj.pk}"
            if Notification.objects.filter(event_key=event_key).exists():
                continue

            n = Notification.objects.create(
                title=f"O.S {os_obj.os_number} pendente há 10 dias",
                message=(
                    f"A ordem de serviço {os_obj.os_number} está pendente há 10 dias ou mais.\n"
                    f"Solicitante: {os_obj.full_name}\n"
                    f"Serviço: {os_obj.service_type}\n"
                    f"Bairro: {os_obj.neighborhood or '-'}"
                ),
                notification_type=Notification.TYPE_OPEN_10,
                service_request=os_obj,
                event_key=event_key,
            )
            n.users.add(*destinatarios)

        # IN_PROGRESS há 15 dias
        progress_limit = agora - timedelta(days=15)
        os_progress = ServiceRequest.objects.filter(
            status="IN_PROGRESS",
            status_updated_at__lte=progress_limit
        )

        for os_obj in os_progress:
            event_key = f"os_progress_15_{os_obj.pk}"
            if Notification.objects.filter(event_key=event_key).exists():
                continue

            n = Notification.objects.create(
                title=f"O.S {os_obj.os_number} em andamento há 15 dias",
                message=(
                    f"A ordem de serviço {os_obj.os_number} está em andamento há 15 dias ou mais.\n"
                    f"Solicitante: {os_obj.full_name}\n"
                    f"Serviço: {os_obj.service_type}\n"
                    f"Bairro: {os_obj.neighborhood or '-'}"
                ),
                notification_type=Notification.TYPE_PROGRESS_15,
                service_request=os_obj,
                event_key=event_key,
            )
            n.users.add(*destinatarios)

        self.stdout.write(self.style.SUCCESS("Notificações automáticas processadas com sucesso."))