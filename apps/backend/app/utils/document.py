"""Validação do código de identificação do cliente: código SETA (8 dígitos
numéricos, uso interno TopFama) ou CPF (com dígitos verificadores)."""

import re

_SETA_RE = re.compile(r"^\d{8}$")

_CPF_INVALID = {d * 11 for d in "0123456789"}


def _cpf_check_digit(digits: str, weight_start: int) -> int:
    total = sum(int(d) * w for d, w in zip(digits, range(weight_start, 1, -1)))
    remainder = (total * 10) % 11
    return 0 if remainder == 10 else remainder


def is_valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit() or digits in _CPF_INVALID:
        return False
    d1 = _cpf_check_digit(digits[:9], 10)
    d2 = _cpf_check_digit(digits[:9] + str(d1), 11)
    return digits[-2:] == f"{d1}{d2}"


def validate_client_code(raw: str | None) -> tuple[str, str] | None:
    """Retorna (código_normalizado, tipo) onde tipo é "seta" ou "cpf", ou
    None se o valor não for um SETA de 8 dígitos nem um CPF válido."""

    digits = re.sub(r"\D", "", str(raw or ""))
    if _SETA_RE.match(digits):
        return digits, "seta"
    if is_valid_cpf(digits):
        return digits, "cpf"
    return None
