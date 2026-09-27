"""Geração de leads a partir da base de cobrança (clientes que passam nos
filtros de `/cobranca/clientes`). Extraído de routers/leads.py pra poder ser
chamado tanto pelo endpoint manual quanto por um job agendado (ver Tarefa 2
do plano de extração automática de leads antes do disparo)."""

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from . import models, seta_client
from .elegibilidade import travar_entrada_na_fila
from .regras_db import carregar_regras
from .utils.spc import parse_spc

LOTE = 1000  # tamanho dos lotes de IN (...) ao consultar o banco


def _em_lotes(itens: list, tamanho: int = LOTE):
    for i in range(0, len(itens), tamanho):
        yield itens[i : i + tamanho]


def gerar_leads_de_clientes(
    db: Session,
    clientes: list[dict[str, Any]],
    *,
    created_by: str | None,
    campanha_id: str = "",
    parcelas: dict[str, list[dict]] | None = None,
) -> tuple[int, int, int]:
    """Cria um Lead por cliente que ainda não é lead da mesma faixa+parcela
    (da régua, ou da campanha `campanha_id`). `parcelas`, quando quem chama
    já buscou, evita consultar o SETA de novo.
    Retorna (criados, ja_existiam, sem_celular). Levanta seta_client.SetaIndisponivel
    se a consulta de SPC/parcelas ao ERP falhar."""

    # Mesma trava da entrada na fila: "Gerar leads" e a extração automática ao
    # mesmo tempo liam os mesmos "novos" e a segunda caía na constraint única
    travar_entrada_na_fila(db)
    ja_existem: set[tuple[str, str, date]] = set()
    for lote in _em_lotes([c["codigo"] for c in clientes]):
        rows = db.query(
            models.Lead.codigo_cliente, models.Lead.faixa, models.Lead.vencimento_mais_antigo
        ).filter(models.Lead.codigo_cliente.in_(lote), models.Lead.campanha_id == campanha_id)
        ja_existem.update((r[0], r[1], r[2]) for r in rows)

    novos = [c for c in clientes if (c["codigo"], c["faixa"], c["vencimento_mais_antigo"]) not in ja_existem]

    # a data da consulta SPC só existe no texto bruto: busca só de quem vira lead
    datas_spc: dict[str, date | None] = {}
    parcelas_map: dict[str, list[dict]] = {}
    if novos:
        codigos_novos = [c["codigo"] for c in novos]
        for lote in _em_lotes(codigos_novos, 5000):
            for codigo, texto in seta_client.buscar_spc(lote).items():
                datas_spc[codigo] = parse_spc(texto)[1]
        if parcelas is not None:
            parcelas_map = parcelas
        else:
            parcelas_map = seta_client.buscar_parcelas_cobranca(codigos_novos, juros=carregar_regras(db).juros)

    leads_para_salvar = []
    for c in novos:
        lead = models.Lead(
            codigo_cliente=c["codigo"],
            nome=c["nome"],
            cpf=c["cpfcnpj"],
            celular=c["celular"],
            celular_origem=c["celular_origem"],
            celular_original=c["celular_original"],
            cluster=c["cluster"],
            faixa=c["faixa"],
            faixa_compra=c["faixa_compra"],
            qtd_compras=c["qtd_compras"],
            dias_atraso=c["dias_atraso"],
            qtd_parcelas=c["qtd_parcelas_cobranca"],
            valor_em_aberto=c["valor_em_aberto"],
            valor_cobrar=c["valor_cobrar"],
            vencimento_mais_antigo=c["vencimento_mais_antigo"],
            lojas="," + ",".join(c["lojas"]) + ",",
            portadores="," + ",".join(c["portadores"]) + ",",
            status_cliente=c["status"],
            spc_restricao=c["spc_restricao"],
            spc_data_consulta=datas_spc.get(c["codigo"]),
            campanha_id=campanha_id,
            created_by=created_by,
        )
        vistos_titulos = set()
        for p in parcelas_map.get(c["codigo"], []):
            t_cod = str(p["titulo_codigo"]).strip()
            if t_cod in vistos_titulos:
                continue
            vistos_titulos.add(t_cod)
            lead.parcelas.append(
                models.LeadParcela(
                    titulo_codigo=t_cod,
                    empresa=str(p["empresa"]).strip(),
                    vencimento=p["vencimento"],
                    valor=p["valor"],
                    valor_cobrar=p["valor_cobrar"],
                )
            )
        leads_para_salvar.append(lead)

    db.add_all(leads_para_salvar)
    db.commit()

    return len(novos), len(clientes) - len(novos), sum(1 for c in novos if not c["celular"])
