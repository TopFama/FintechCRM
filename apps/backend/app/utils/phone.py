"""Normalização e validação de telefone — porta do Code node usado nos
fluxos n8n de cobrança (DDI 55, DDD, 9º dígito)."""

import re

_INVALID = {
    "0000000000000",
    "5500000000000",
    "5511111111111",
    "5599999999999",
}

_RE_10_DIGITS = re.compile(r"^[1-9]{2}\d{8}$")
_RE_11_DIGITS_WITH_9 = re.compile(r"^[1-9]{2}9\d{8}$")
_RE_55_WITHOUT_9 = re.compile(r"^55[1-9]{2}\d{8}$")
_RE_VALID_FINAL = re.compile(r"^55[1-9]{2}9\d{8}$")


def normalize_phone(raw: str | None) -> str:
    if raw is None:
        return ""
    value = re.sub(r"\D", "", str(raw))

    if _RE_10_DIGITS.match(value):
        value = "55" + value[:2] + "9" + value[2:]
    elif _RE_11_DIGITS_WITH_9.match(value):
        value = "55" + value
    elif _RE_55_WITHOUT_9.match(value):
        value = "55" + value[2:4] + "9" + value[4:]

    return value


def is_valid_phone(raw: str | None) -> bool:
    value = normalize_phone(raw)
    if not _RE_VALID_FINAL.match(value):
        return False
    return value not in _INVALID


def _eh_fixo(raw: str | None) -> bool:
    """Número de 10 dígitos (DDD + 8) cujo primeiro dígito do assinante é 2–5 é
    telefone fixo. `normalize_phone` injeta o 9 em qualquer número de 10
    dígitos e o resultado passaria em `is_valid_phone`, mas fixo não recebe
    WhatsApp — então no fallback do SETA ele conta como telefone inválido."""

    digits = re.sub(r"\D", "", str(raw or ""))
    return bool(_RE_10_DIGITS.match(digits)) and digits[2] in "2345"


def escolher_telefone(**candidatos: str | None) -> tuple[str | None, str | None]:
    """Percorre os telefones na ordem recebida (ex.: telefone2, telefone1,
    telefone3) e devolve (celular_normalizado, nome_do_campo) do primeiro
    utilizável. Campo sem dígito nenhum (vazio ou só máscara, como `(  )     -`)
    é pulado sem contar como erro. Se nenhum servir, devolve (None, None)."""

    for campo, raw in candidatos.items():
        if not raw or not re.search(r"\d", str(raw)):
            continue
        if _eh_fixo(raw) or not is_valid_phone(raw):
            continue
        return normalize_phone(raw), campo
    return None, None
