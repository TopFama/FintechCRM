import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Literal, Mapping

from .timezone import hoje_br
from .utils.leads_xlsx import formatar_codigo, formatar_cpf, primeiro_nome

CAMPOS_CLIENTE: dict[str, str] = {
    "codigo": "Código SETA",
    "nome": "Nome completo",
    "primeiro_nome": "Primeiro nome",
    "codigo_primeiro_nome": "Código - Primeiro nome",
    "cpf": "CPF",
    "celular": "Celular",
    "cluster": "Cluster",
    "faixa": "Faixa de atraso",
    "dias_atraso": "Dias de atraso",
    "qtd_parcelas": "Parcelas em atraso",
    "valor_cobrar": "Valor a cobrar",
    "valor_em_aberto": "Valor em aberto",
    "vencimento": "Vencimento da parcela mais antiga",
    "valor_parcela_amanha": "Valor da parcela que vence amanhã",
    "valor_atraso": "Valor em atraso",
}


class PlaceholderDesconhecido(Exception):
    def __init__(self, placeholder: str, chaves_validas: Iterable[str]):
        self.placeholder = placeholder
        self.chaves_validas = list(chaves_validas)
        validas_str = ", ".join(sorted(str(c) for c in self.chaves_validas))
        super().__init__(
            f"Placeholder '{placeholder}' desconhecido. Chaves válidas: {validas_str}"
        )


def remover_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_chave(chave: str) -> str:
    texto = remover_acentos(str(chave).lower())
    texto = texto.replace("_", " ")
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_para_meta(texto: Any) -> str:
    if texto is None:
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip()


def formatar_moeda(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, str) and not valor.strip():
        return ""
    try:
        d = Decimal(str(valor).strip())
    except Exception:
        return ""

    d = d.quantize(Decimal("0.01"))
    sinal = "-" if d < 0 else ""
    abs_d = abs(d)
    partes = f"{abs_d:.2f}".split(".")
    int_part, dec_part = partes[0], partes[1]

    int_com_pontos = ""
    while int_part:
        int_com_pontos = int_part[-3:] + ("." + int_com_pontos if int_com_pontos else "")
        int_part = int_part[:-3]

    return f"{sinal}R$ {int_com_pontos},{dec_part}"


def formatar_data(valor: Any) -> str:
    if not valor:
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, str):
        v = valor.strip()
        if not v:
            return ""
        if len(v) >= 10 and v[4] == "-" and v[7] == "-":
            try:
                ano, mes, dia = v[:10].split("-")
                return f"{dia}/{mes}/{ano}"
            except Exception:
                return v
        return v
    return str(valor)


def _campo(obj: Any, nome: str) -> Any:
    return obj.get(nome) if isinstance(obj, Mapping) else getattr(obj, nome, None)


def valor_em_atraso_com_juros(parcelas: Iterable, juros: Any = None) -> Decimal:
    """Mesma conta do valor a cobrar do SETA, mas contada até hoje: com
    `dias_min` ou mais de atraso, valor + valor × juros_dia × dias + valor × multa."""
    from .cobranca_regras import PARAMETROS_JUROS_PADRAO

    juros = juros or PARAMETROS_JUROS_PADRAO
    hoje = hoje_br()
    total = Decimal("0")
    for p in parcelas:
        venc = _campo(p, "vencimento")
        if venc is None or venc >= hoje:
            continue
        valor = Decimal(str(_campo(p, "valor") or 0))
        dias = (hoje - venc).days
        if dias >= juros.dias_min:
            valor = valor + valor * juros.juros_dia * dias + valor * juros.multa
        total += valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total


def contexto_cliente(cliente: Mapping) -> dict[str, str]:
    if not isinstance(cliente, Mapping):
        cliente = {}

    cpf_val = cliente.get("cpfcnpj") if cliente.get("cpfcnpj") is not None else cliente.get("cpf")
    qtd_val = (
        cliente.get("qtd_parcelas_cobranca")
        if cliente.get("qtd_parcelas_cobranca") is not None
        else cliente.get("qtd_parcelas")
    )
    venc_val = (
        cliente.get("vencimento_mais_antigo")
        if cliente.get("vencimento_mais_antigo") is not None
        else cliente.get("vencimento")
    )
    dias_val = cliente.get("dias_atraso")

    # Lembrete D-1: soma das parcelas do cliente que vencem amanhã (GMT-3).
    # Aceita o valor já calculado ou a lista de parcelas do lead.
    valor_amanha = cliente.get("valor_parcela_amanha")
    if valor_amanha is None and cliente.get("parcelas") is not None:
        amanha = hoje_br() + timedelta(days=1)
        valor_amanha = sum(
            (Decimal(str(_campo(p, "valor") or 0)) for p in cliente["parcelas"]
             if _campo(p, "vencimento") == amanha),
            Decimal("0"),
        )
        if valor_amanha == 0:
            valor_amanha = None
    # Valor em atraso: parcelas já vencidas (antes de hoje, GMT-3) com juros
    # e multa corridos até hoje pelos parâmetros de Configurações → Indicadores.
    valor_atraso = cliente.get("valor_atraso")
    if valor_atraso is None and cliente.get("parcelas") is not None:
        valor_atraso = valor_em_atraso_com_juros(cliente["parcelas"], cliente.get("juros"))
    codigo_fmt = formatar_codigo(cliente.get("codigo"))
    primeiro = primeiro_nome(cliente.get("nome"))

    return {
        "codigo": codigo_fmt,
        "nome": str(cliente.get("nome") or "").strip(),
        "primeiro_nome": primeiro,
        "codigo_primeiro_nome": " - ".join(x for x in (codigo_fmt, primeiro) if x),
        "cpf": formatar_cpf(cpf_val),
        "celular": str(cliente.get("celular") or "").strip(),
        "cluster": str(cliente.get("cluster") or "").strip(),
        "faixa": str(cliente.get("faixa") or "").strip(),
        "dias_atraso": str(dias_val) if dias_val is not None and str(dias_val).strip() != "" else "",
        "qtd_parcelas": str(qtd_val) if qtd_val is not None and str(qtd_val).strip() != "" else "",
        "valor_cobrar": formatar_moeda(cliente.get("valor_cobrar")),
        "valor_em_aberto": formatar_moeda(cliente.get("valor_em_aberto")),
        "vencimento": formatar_data(venc_val),
        "valor_parcela_amanha": formatar_moeda(valor_amanha),
        "valor_atraso": formatar_moeda(valor_atraso),
    }


def extrair_placeholders(expressao: str) -> list[str]:
    if not expressao:
        return []
    matches = re.findall(r"\{([^{}]*)\}", expressao)
    return [m.strip() for m in matches if m.strip()]


def validar_sintaxe(expressao: str | None) -> str | None:
    if not expressao or not expressao.strip():
        return "Expressão vazia: informe ao menos um placeholder entre chaves"

    depth = 0
    pos_abertura = -1
    placeholders = []

    for i, ch in enumerate(expressao):
        if ch == "{":
            if depth > 0:
                return "Chaves aninhadas não são permitidas"
            depth += 1
            pos_abertura = i
        elif ch == "}":
            if depth == 0:
                return "Chave de fechamento '}' sem abertura correspondente"
            conteudo = expressao[pos_abertura + 1 : i].strip()
            if not conteudo:
                return "Placeholder vazio '{}' não é permitido"
            placeholders.append(conteudo)
            depth -= 1

    if depth > 0:
        return "Chave de abertura '{' sem fechamento correspondente"

    if not placeholders:
        return "A expressão deve conter ao menos um placeholder entre chaves, ex: {nome}"

    return None


def _construir_mapa_normalizado(contexto: Mapping[str, Any]) -> dict[str, Any]:
    norm_map = {}
    for k, v in contexto.items():
        nk = normalizar_chave(k)
        if nk not in norm_map:
            norm_map[nk] = v

    # Permite resolver também pelo rótulo do catálogo (ex: {Código SETA} -> codigo)
    for campo, rotulo in CAMPOS_CLIENTE.items():
        if campo in contexto:
            n_rotulo = normalizar_chave(rotulo)
            if n_rotulo not in norm_map:
                norm_map[n_rotulo] = contexto[campo]

    return norm_map


def renderizar_expressao(
    expressao: str,
    contexto: Mapping[str, Any],
    *,
    estrito: bool = False,
) -> str:
    norm_map = _construir_mapa_normalizado(contexto)

    def substituir(match: re.Match) -> str:
        raw = match.group(1).strip()
        if raw in contexto:
            val = contexto[raw]
        else:
            nk = normalizar_chave(raw)
            if nk in norm_map:
                val = norm_map[nk]
            else:
                if estrito:
                    raise PlaceholderDesconhecido(raw, contexto.keys())
                val = ""
        return str(val) if val is not None else ""

    resultado = re.sub(r"\{([^{}]*)\}", substituir, expressao)
    return normalizar_para_meta(resultado)


@dataclass(frozen=True)
class FonteVariavel:
    nome_interno: str
    tipo: Literal["coluna", "campo_cliente", "expressao"]
    valor: str


def resolver_variaveis(
    fontes: Iterable[FonteVariavel],
    contexto: Mapping[str, Any],
    *,
    estrito: bool = False,
) -> dict[str, str]:
    norm_map = _construir_mapa_normalizado(contexto)
    resultado = {}

    for fonte in fontes:
        if fonte.tipo == "coluna":
            if fonte.valor in contexto:
                val = contexto.get(fonte.valor)
            else:
                nk = normalizar_chave(fonte.valor)
                if nk in norm_map:
                    val = norm_map[nk]
                else:
                    if estrito:
                        raise PlaceholderDesconhecido(fonte.valor, contexto.keys())
                    val = ""
        elif fonte.tipo == "campo_cliente":
            if fonte.valor in contexto:
                val = contexto[fonte.valor]
            else:
                nk = normalizar_chave(fonte.valor)
                if nk in norm_map:
                    val = norm_map[nk]
                else:
                    if estrito:
                        raise PlaceholderDesconhecido(fonte.valor, contexto.keys())
                    val = ""
        elif fonte.tipo == "expressao":
            val = renderizar_expressao(fonte.valor, contexto, estrito=estrito)
        else:
            val = ""

        resultado[fonte.nome_interno] = normalizar_para_meta(val)

    return resultado
