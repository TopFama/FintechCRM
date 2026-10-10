"""Peças da camada HTTP usadas por mais de um router (dependências de filtro,
leitura de arquivo enviado). Não é um router: não registra rota nenhuma."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from .. import cobranca_base, google_client, lojas as lojas_base
from ..database import get_db
from ..regras_db import carregar_regras

_TAMANHO_MAXIMO_PLANILHA_BYTES = 20 * 1024 * 1024


async def ler_planilha_limitada(file: UploadFile) -> bytes:
    # Lê no máximo o limite + 1 byte: arquivo gigante não vai inteiro para a memória
    content = await file.read(_TAMANHO_MAXIMO_PLANILHA_BYTES + 1)
    if len(content) > _TAMANHO_MAXIMO_PLANILHA_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Planilha maior que o limite de 20 MB")
    return content


def filtros_base(
    apenas_primeiro_dia: bool = Query(True, description="Só clientes no primeiro dia da faixa (ex.: 21 dias na faixa 21 A 30)"),
    somente_regra_whatsapp: bool = Query(True, description="Aplica a matriz cluster × faixa do WhatsApp"),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    faixa_compra: list[str] | None = Query(None, description="Quantidade de compras no crediário: 1 a 9 ou 10+"),
    loja: list[str] | None = Query(None, description="Código de 2 caracteres da loja do título (ft.empresa)"),
    regional: list[str] | None = Query(None, description="Regional da loja (planilha de lojas)"),
    estado: list[str] | None = Query(None, description="Estado da loja: TO, PA, MA ou GO"),
    cluster_inad: list[str] | None = Query(None, description="Cluster de inadimplência da loja"),
    cluster_populacao: list[str] | None = Query(None, description="Cluster de população da loja"),
    cobradora: list[str] | None = Query(None, description='Cluster de cobradora da loja (planilha de lojas) ou "Sem cobradora"'),
    status_cliente: list[str] | None = Query(None, description="E, A ou B"),
    restricao_spc: list[str] | None = Query(None, description="sim, nao e/ou indeterminado"),
    vencimento_de: date | None = Query(None, description="Vencimento da parcela mais antiga, a partir de"),
    vencimento_ate: date | None = Query(None, description="Vencimento da parcela mais antiga, até"),
    valor_atraso_min: Decimal | None = Query(None, ge=0, description="Total das parcelas vencidas, a partir de"),
    valor_atraso_max: Decimal | None = Query(None, ge=0, description="Total das parcelas vencidas, até"),
    valor_atraso_com_juros: bool = Query(False, description="O valor em atraso conta multa e juros"),
    db: Session = Depends(get_db),
) -> dict:
    """Filtros comuns à listagem e aos relatórios: os dois enxergam os mesmos clientes."""

    try:
        codigos_loja = lojas_base.combinar_lojas(
            db, loja, regional=regional, estado=estado, cluster_inad=cluster_inad, cluster_populacao=cluster_populacao,
            cobradora=cobradora,
        )
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return dict(
        apenas_primeiro_dia=apenas_primeiro_dia,
        somente_regra_whatsapp=somente_regra_whatsapp,
        faixas=faixa,
        clusters=cluster,
        faixas_compra=faixa_compra,
        lojas=codigos_loja,
        status_cliente=status_cliente,
        restricoes_spc=restricao_spc,
        vencimento_de=vencimento_de,
        vencimento_ate=vencimento_ate,
        valor_atraso_min=valor_atraso_min,
        valor_atraso_max=valor_atraso_max,
        valor_atraso_com_juros=valor_atraso_com_juros,
    )


def buscar_base_ou_erro(db: Session, filtros: dict) -> dict:
    """{"status": "ready", "data": [...]} ou {"status": "processing", "data":
    None} — ver `cobranca_base.buscar_base`."""

    try:
        return cobranca_base.buscar_base(db, **filtros)
    except cobranca_base.FiltroInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


ClienteSortColumn = Literal[
    "codigo",
    "cpfcnpj",
    "nome",
    "vencimento_mais_antigo",
    "valor_cobrar",
    "qtd_parcelas_cobranca",
    "dias_atraso",
    "faixa",
    "cluster",
]


def ordenar_clientes(clientes: list[dict], sort_by: str, sort_dir: str, db: Session) -> list[dict]:
    """Ordena uma cópia da lista já carregada em memória (vinda do cache de
    `cobranca_base.buscar_base`) — não refaz a consulta ao SETA. `faixa`
    ordena pela progressão do atraso, mesmo critério da tela, e dentro da
    faixa pelos dias de atraso (em Antecipado, o vencimento mais distante
    primeiro). Faixa fora das regras (dia sem faixa na campanha com todos da
    planilha) fica onde os dias dela cairiam."""

    if sort_by == "faixa":
        regras = carregar_regras(db)
        ordem_faixa = {nome: i for i, nome in enumerate(regras.nomes_faixa)}

        def valor_fn(c):
            if not c.get("faixa"):
                return None
            ordem = ordem_faixa.get(c["faixa"])
            if ordem is None:
                dias_min = [f.dia_min for f in regras.faixas]
                ordem = sum(1 for d in dias_min if d <= c["dias_atraso"]) - 0.5
            return (ordem, c["dias_atraso"])
    else:
        valor_fn = lambda c: c.get(sort_by)

    # Vazios sempre no fim, nas duas direções
    preenchidos = sorted(
        (c for c in clientes if valor_fn(c) is not None), key=valor_fn, reverse=sort_dir == "desc"
    )
    return preenchidos + [c for c in clientes if valor_fn(c) is None]
