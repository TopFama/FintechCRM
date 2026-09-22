"""Fuso horário de negócio (Brasília) — todo timestamp é armazenado em UTC no
banco; a conversão pra hora local só acontece na borda (decisões de "que dia
é hoje" e exibição pra humano). Ver worker.py para o motivo original."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import settings

BUSINESS_TZ = ZoneInfo(settings.business_timezone)


def agora_br() -> datetime:
    """Agora, convertido pro fuso de negócio (a partir do relógio UTC do servidor)."""
    return datetime.now(ZoneInfo("UTC")).astimezone(BUSINESS_TZ)


def hoje_br() -> date:
    """Data de "hoje" no fuso de negócio — usar em vez de date.today() sempre
    que a data decide corte de negócio (ex.: bloquear reenvio no mesmo dia),
    já que o relógio do servidor é UTC."""
    return agora_br().date()
