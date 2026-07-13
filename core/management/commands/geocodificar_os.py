import json
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.db.models import Q

from core.models import ServiceRequest


class Command(BaseCommand):
    help = "Geocodifica as O.S. antigas e salva latitude e longitude."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limite",
            type=int,
            default=None,
            help="Quantidade máxima de O.S. para processar.",
        )

        parser.add_argument(
            "--forcar",
            action="store_true",
            help=(
                "Geocodifica novamente até as O.S. "
                "que já possuem coordenadas."
            ),
        )

    def limpar_valor(self, valor):
        if valor is None:
            return ""

        return str(valor).strip()

    def montar_tentativas_endereco(self, os_obj):
        rua = self.limpar_valor(os_obj.street)
        numero = self.limpar_valor(os_obj.number)
        bairro = self.limpar_valor(os_obj.neighborhood)
        cidade = self.limpar_valor(os_obj.city)
        cep = self.limpar_valor(os_obj.cep)

        if not cidade:
            cidade = "Nossa Senhora do Socorro"

        estado = "Sergipe"
        pais = "Brasil"

        tentativas = []

        def adicionar(partes):
            endereco = ", ".join(
                parte
                for parte in partes
                if parte
            )

            if endereco and endereco not in tentativas:
                tentativas.append(endereco)

        # Tentativa mais completa.
        adicionar([
            rua,
            numero,
            bairro,
            cidade,
            estado,
            pais,
            cep,
        ])

        # Sem CEP.
        adicionar([
            rua,
            numero,
            bairro,
            cidade,
            estado,
            pais,
        ])

        # Sem número.
        adicionar([
            rua,
            bairro,
            cidade,
            estado,
            pais,
        ])

        # Apenas rua e cidade.
        adicionar([
            rua,
            cidade,
            estado,
            pais,
        ])

        # CEP com cidade.
        adicionar([
            cep,
            cidade,
            estado,
            pais,
        ])

        # Somente CEP.
        adicionar([
            cep,
            pais,
        ])

        # Última alternativa: bairro.
        adicionar([
            bairro,
            cidade,
            estado,
            pais,
        ])

        return tentativas

    def consultar_nominatim(self, endereco):
        parametros = urlencode({
            "q": endereco,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "br",
            "addressdetails": 1,
        })

        url = (
            "https://nominatim.openstreetmap.org/search?"
            f"{parametros}"
        )

        requisicao = Request(
            url,
            headers={
                "User-Agent": (
                    "PortalServicosUrbanos/1.0 "
                    "(servicosurbanossocorro@gmail.com)"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9",
            },
        )

        try:
            with urlopen(requisicao, timeout=20) as resposta:
                dados = json.loads(
                    resposta.read().decode("utf-8")
                )

            if not dados:
                return None, None

            latitude = Decimal(str(dados[0]["lat"]))
            longitude = Decimal(str(dados[0]["lon"]))

            return latitude, longitude

        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            InvalidOperation,
            json.JSONDecodeError,
        ) as erro:
            self.stderr.write(
                self.style.ERROR(
                    f"Erro ao consultar endereço: {erro}"
                )
            )

            return None, None

    def geocodificar(self, os_obj):
        tentativas = self.montar_tentativas_endereco(os_obj)

        for numero_tentativa, endereco in enumerate(
            tentativas,
            start=1,
        ):
            self.stdout.write(
                f"  Tentativa {numero_tentativa}: {endereco}"
            )

            latitude, longitude = self.consultar_nominatim(
                endereco
            )

            if (
                latitude is not None
                and longitude is not None
            ):
                return latitude, longitude, endereco

            # Respeita o intervalo entre consultas.
            time.sleep(1)

        return None, None, None

    def handle(self, *args, **options):
        limite = options.get("limite")
        forcar = options.get("forcar", False)

        queryset = (
            ServiceRequest.objects
            .all()
            .order_by("id")
        )

        if not forcar:
            queryset = queryset.filter(
                Q(latitude__isnull=True)
                | Q(longitude__isnull=True)
            )

        if limite:
            queryset = queryset[:limite]

        total = queryset.count()

        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "Nenhuma O.S. precisa ser geocodificada."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"{total} O.S. serão processadas."
            )
        )

        encontradas = 0
        nao_encontradas = 0

        for indice, os_obj in enumerate(
            queryset,
            start=1,
        ):
            self.stdout.write("")
            self.stdout.write(
                f"[{indice}/{total}] {os_obj.os_number}"
            )

            latitude, longitude, endereco_usado = (
                self.geocodificar(os_obj)
            )

            if (
                latitude is None
                or longitude is None
            ):
                nao_encontradas += 1

                self.stderr.write(
                    self.style.WARNING(
                        "Localização não encontrada: "
                        f"{os_obj.os_number}"
                    )
                )
                continue

            os_obj.latitude = latitude
            os_obj.longitude = longitude

            os_obj.save(
                update_fields=[
                    "latitude",
                    "longitude",
                ]
            )

            encontradas += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Salvo: {latitude}, {longitude}"
                )
            )

            self.stdout.write(
                f"  Endereço utilizado: {endereco_usado}"
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Geocodificação finalizada."
            )
        )
        self.stdout.write(
            f"Localizações encontradas: {encontradas}"
        )
        self.stdout.write(
            f"Localizações não encontradas: {nao_encontradas}"
        )