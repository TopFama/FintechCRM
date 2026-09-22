"""Carrega as regras de cobrança das 4 tabelas de configuração do banco.

Sem cache de propósito: são 4 consultas pequenas por requisição, e a tela de
configuração pode alterar as regras a qualquer momento.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from . import models
from .cobranca_regras import (
    Cluster,
    FaixaAtraso,
    ParametrosJuros,
    Regras,
)


def carregar_regras(db: Session) -> Regras:
    """Monta objeto Regras a partir do banco de dados (tabelas config_*)."""

    clusters_db = db.query(models.ClusterCobranca).order_by(models.ClusterCobranca.valor_min).all()
    faixas_db = db.query(models.FaixaAtrasoCobranca).order_by(models.FaixaAtrasoCobranca.dia_min).all()
    regras_db = db.query(models.RegraWhatsapp).all()
    params_db = db.query(models.ParametrosCobranca).first()

    clusters = tuple(
        Cluster(nome=c.nome, valor_min=Decimal(str(c.valor_min)))
        for c in clusters_db
    )
    faixas = tuple(
        FaixaAtraso(nome=f.nome, dia_min=f.dia_min, dia_max=f.dia_max)
        for f in faixas_db
    )

    # Mapeia id -> nome para montar os pares por nome
    cluster_por_id = {c.id: c.nome for c in clusters_db}
    faixa_por_id = {f.id: f.nome for f in faixas_db}
    whatsapp: frozenset[tuple[str, str]] = frozenset(
        (cluster_por_id[r.cluster_id], faixa_por_id[r.faixa_id])
        for r in regras_db
        if r.cluster_id in cluster_por_id and r.faixa_id in faixa_por_id
    )

    if params_db is None:
        juros = ParametrosJuros()
    else:
        juros = ParametrosJuros(
            juros_mes_percentual=Decimal(str(params_db.juros_mes_percentual)),
            multa_percentual=Decimal(str(params_db.multa_percentual)),
            dias_min=params_db.dias_min_juros,
        )

    return Regras(clusters=clusters, faixas=faixas, whatsapp=whatsapp, juros=juros)
