"""Fuso horário de negócio (Brasília) — todo timestamp é armazenado em UTC no
banco; a conversão pra hora local só acontece na borda (decisões de "que dia
é hoje" e exibição pra humano). Ver `para_br` para o motivo."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .config import settings

BUSINESS_TZ = ZoneInfo(settings.business_timezone)
_UTC = ZoneInfo("UTC")


def agora_br() -> datetime:
    """Agora, convertido pro fuso de negócio (a partir do relógio UTC do servidor)."""
    return datetime.now(_UTC).astimezone(BUSINESS_TZ)


def hoje_br() -> date:
    """Data de "hoje" no fuso de negócio — usar em vez de date.today() sempre
    que a data decide corte de negócio (ex.: bloquear reenvio no mesmo dia),
    já que o relógio do servidor é UTC."""
    return agora_br().date()


# O banco grava UTC "ingênuo" (sem tzinfo). As conversões abaixo são a única
# ponte entre esse formato e o dia/hora de Brasília.


def para_br(dt_utc: datetime) -> datetime:
    """Timestamp UTC ingênuo do banco → horário de Brasília (com fuso).

    A janela de disparo (horário, dias da semana) é pensada no horário de quem
    opera; comparar direto em UTC faria a janela fechar 3h fora do horário real."""
    return dt_utc.replace(tzinfo=_UTC).astimezone(BUSINESS_TZ)


def dia_br(dt_utc: datetime) -> date:
    """Data em Brasília de um timestamp UTC ingênuo."""
    return para_br(dt_utc).date()


def hora_br(dt_utc: datetime | None) -> datetime | None:
    """Timestamp UTC ingênuo → horário de Brasília ingênuo (para Excel e telas)."""
    if dt_utc is None:
        return None
    return para_br(dt_utc).replace(tzinfo=None)


def utc_ingenuo(local: datetime) -> datetime:
    """Horário com fuso → UTC ingênuo (como o banco grava)."""
    return local.astimezone(_UTC).replace(tzinfo=None)


def inicio_do_dia_utc(dia: date) -> datetime:
    """Meia-noite de Brasília do dia, em UTC ingênuo: limite de filtro por dia."""
    return utc_ingenuo(datetime.combine(dia, time.min, BUSINESS_TZ))


def inicio_hoje_utc() -> datetime:
    """Meia-noite de hoje em Brasília, em UTC ingênuo (como sent_at é gravado)."""
    return inicio_do_dia_utc(hoje_br())
