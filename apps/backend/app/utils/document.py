"""Normalização dos dados de identificação do cliente, obrigatórios em toda
planilha upada: código SETA, nome e CPF."""

import re

_SETA_DIGITS = 8
_CPF_DIGITS = 11


def normalize_seta_code(raw: str | None) -> str | None:
    """Extrai os dígitos do código SETA e completa com zeros à esquerda até
    8 dígitos. Retorna None se não sobrar dígito nenhum ou se vier com mais
    de 8 dígitos (não é um SETA válido)."""

    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits or len(digits) > _SETA_DIGITS:
        return None
    return digits.zfill(_SETA_DIGITS)


def format_cpf(raw: str | None) -> str | None:
    """Extrai os dígitos do CPF, completa com zeros à esquerda até 11
    dígitos e formata como XXX.XXX.XXX-XX. Retorna None se não sobrar
    dígito nenhum ou se vier com mais de 11 dígitos."""

    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits or len(digits) > _CPF_DIGITS:
        return None
    digits = digits.zfill(_CPF_DIGITS)
    return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"


def extract_first_name(raw: str | None) -> str:
    """Normaliza um nome completo para só o primeiro nome (planilhas trazem
    nome completo, mas o disparo usa só o primeiro nome)."""

    text = str(raw or "").strip()
    if not text:
        return ""
    return text.split()[0]
