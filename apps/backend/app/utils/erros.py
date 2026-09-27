"""Tradutor e formatador de mensagens de erro da Meta e Chatwoot para português."""

import re

_MAPA_ERROS_META: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"132001|Template name does not exist", re.IGNORECASE),
        "Template ou idioma não encontrado na Meta para este número/WABA",
    ),
    (
        re.compile(r"131026|Message undeliverable", re.IGNORECASE),
        "Mensagem não pôde ser entregue pelo WhatsApp (número sem WhatsApp ou inativo)",
    ),
    (
        re.compile(r"131047|More than 24 hours", re.IGNORECASE),
        "Janela de conversação de 24 horas expirada para o destinatário",
    ),
    (
        re.compile(r"132000|Number of parameters does not match", re.IGNORECASE),
        "Quantidade de variáveis diverge do template aprovado na Meta",
    ),
    (
        re.compile(r"132012|Parameter format does not match", re.IGNORECASE),
        "Formato do parâmetro (ex: imagem/texto) incompatível com o template na Meta",
    ),
    (
        re.compile(r"131051|Unsupported message type", re.IGNORECASE),
        "Tipo de mensagem não suportado pela Meta",
    ),
    (
        re.compile(r"131052|Media download error", re.IGNORECASE),
        "Falha ao baixar imagem de cabeçalho do template",
    ),
    (
        re.compile(r"130429|Rate limit", re.IGNORECASE),
        "Limite de envios da Meta atingido para este número",
    ),
    (
        re.compile(r"131009|Parameter value is not valid", re.IGNORECASE),
        "Valor de variável inválido para o template na Meta",
    ),
    (
        re.compile(r"190|OAuthException|Session has expired|Invalid OAuth", re.IGNORECASE),
        "Token de acesso da Meta expirado ou inválido",
    ),
    (
        re.compile(r"No address associated with hostname", re.IGNORECASE),
        "Falha de conexão DNS com o servidor externo",
    ),
]


def descrever_erro_envio(erro_bruto: str | None) -> str:
    """Transforma mensagens técnicas de erro da Meta/WhatsApp/Chatwoot em uma
    descrição clara em português, mantendo a referência original."""
    if not erro_bruto:
        return "Falha desconhecida no envio"
    texto = str(erro_bruto).strip()
    for padrao, descricao in _MAPA_ERROS_META:
        if padrao.search(texto):
            return f"{descricao} — Detalhes: {texto}"
    return f"Falha no envio — Detalhes: {texto}"
