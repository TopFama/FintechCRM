"""Leitura de valor em reais escrito de qualquer jeito numa planilha."""

import re
from decimal import Decimal, InvalidOperation

# Primeiro número do texto: "1.234,56", "1234.56", "1 500,00", "R$ 10",
# "10,00 reais", "US$ 50", ",50". Espaço só conta como separador de milhar.
_NUMERO = re.compile(r"-?\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|-?\d[\d.,]*|-?[.,]\d+")


def ler_valor(texto: str | None) -> Decimal | None:
    """Valor em reais escrito na planilha, ou None se não tem número."""
    achado = _NUMERO.search(texto or "")
    if not achado:
        return None
    num = re.sub(r"[ \u00a0]", "", achado.group()).rstrip(".,")
    if "," in num and "." in num:
        # O último separador é o decimal
        decimal, milhar = (",", ".") if num.rfind(",") > num.rfind(".") else (".", ",")
        num = num.replace(milhar, "").replace(decimal, ".")
    elif "," in num:
        num = num.replace(",", ".") if num.count(",") == 1 else num.replace(",", "")
    elif num.count(".") > 1 or re.fullmatch(r"-?[1-9]\d{0,2}\.\d{3}", num):
        num = num.replace(".", "")  # "1.500" é mil e quinhentos ("0.500" não)
    try:
        return Decimal(num)
    except InvalidOperation:
        return None
