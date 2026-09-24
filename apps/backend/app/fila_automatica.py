"""Fila automática: leads extraídos pelo agendador entram direto na fila de
disparo da faixa (sem exportar/subir planilha), e o que não saiu até o fim
da janela é descartado — os dados (valor, dias de atraso) ficam obsoletos
de um dia pro outro."""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, selectinload

from . import models
from .pausas import lojas_formatadas
from .regras_db import carregar_regras
from .timezone import BUSINESS_TZ
from .utils.leads_xlsx import formatar_codigo, formatar_cpf, primeiro_nome
from .utils.phone import is_valid_phone, normalize_phone
from .variaveis_template import FonteVariavel, contexto_cliente, resolver_variaveis

logger = logging.getLogger("fila_automatica")


def _utc_ingenuo(local: datetime) -> datetime:
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def inicio_hoje_utc() -> datetime:
    """Meia-noite de hoje em Brasília, em UTC ingênuo (como sent_at é gravado)."""
    return _utc_ingenuo(datetime.combine(datetime.now(BUSINESS_TZ).date(), time.min, BUSINESS_TZ))


def clientes_bloqueados_hoje(db: Session) -> set[str]:
    """Códigos que não podem entrar na fila agora, em QUALQUER faixa: quem já
    está pendente/reservado (vai sair) e quem já foi cobrado hoje (GMT-3).
    Cliente cobrado em dia anterior pode voltar."""

    return {
        codigo
        for (codigo,) in db.query(models.QueueItem.codigo_cliente).filter(
            or_(
                models.QueueItem.status.in_([models.QueueStatus.pending, models.QueueStatus.reserved]),
                and_(models.QueueItem.status == models.QueueStatus.sent, models.QueueItem.sent_at >= inicio_hoje_utc()),
            )
        )
    }


def cobrados_hoje(db: Session) -> set[str]:
    """Códigos que já receberam cobrança hoje (GMT-3), em qualquer faixa."""

    return {
        codigo
        for (codigo,) in db.query(models.QueueItem.codigo_cliente).filter(
            models.QueueItem.status == models.QueueStatus.sent, models.QueueItem.sent_at >= inicio_hoje_utc()
        )
    }


def ja_cobrado_hoje(db: Session, item: models.QueueItem) -> bool:
    """Checagem final antes do envio: outro item do mesmo cliente já saiu hoje (qualquer faixa)."""

    return (
        db.query(models.QueueItem.id)
        .filter(
            models.QueueItem.codigo_cliente == item.codigo_cliente,
            models.QueueItem.id != item.id,
            models.QueueItem.status == models.QueueStatus.sent,
            models.QueueItem.sent_at >= inicio_hoje_utc(),
        )
        .first()
        is not None
    )


def _contexto_lead(lead: models.Lead, juros=None) -> dict[str, str]:
    # Colunas da planilha de leads exportada vêm primeiro: um mapeamento
    # "coluna Nome" resolve pro primeiro nome, igual ao upload manual dessa planilha.
    contexto = {
        "Codigo": formatar_codigo(lead.codigo_cliente),
        "Nome": primeiro_nome(lead.nome),
        "CPF": formatar_cpf(lead.cpf),
        "Celular": lead.celular or "",
    }
    contexto.update(
        contexto_cliente(
            {
                "codigo": lead.codigo_cliente,
                "nome": lead.nome,
                "cpf": lead.cpf,
                "celular": lead.celular,
                "cluster": lead.cluster,
                "faixa": lead.faixa,
                "dias_atraso": lead.dias_atraso,
                "qtd_parcelas": lead.qtd_parcelas,
                "valor_cobrar": lead.valor_cobrar,
                "valor_em_aberto": lead.valor_em_aberto,
                "vencimento_mais_antigo": lead.vencimento_mais_antigo,
                "parcelas": lead.parcelas,
                "juros": juros,
            }
        )
    )
    return contexto


def _fontes(faixa: models.Faixa, template: models.Template) -> list[tuple[models.TemplateVariable, FonteVariavel | None]]:
    mapas = {m.template_variable_id: m for m in faixa.variable_mappings if m.template_id == template.id}
    fontes = []
    for v in template.variables:
        m = mapas.get(v.id)
        if m is None:
            fontes.append((v, None))
        elif m.fonte_tipo == "expressao":
            fontes.append((v, FonteVariavel(v.internal_name, "expressao", m.expressao or "")))
        else:
            fontes.append((v, FonteVariavel(v.internal_name, m.fonte_tipo, m.column_name or "")))
    return fontes


def enfileirar_leads(db: Session, clientes: list[dict]) -> int:
    """Coloca na fila da faixa correspondente os clientes da base do dia
    (já filtrada por primeiro dia da faixa + matriz do WhatsApp). Usa o Lead
    salvo de cada cliente pra resolver as variáveis do template. Mesmo
    bloqueio do upload: não duplica quem está pendente/reservado nem quem já
    foi cobrado hoje em qualquer faixa. Devolve quantos entraram na fila."""

    if not clientes:
        return 0

    faixas = {
        f.name: f
        for f in db.query(models.Faixa)
        .options(
            selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.template).selectinload(
                models.Template.variables
            ),
            selectinload(models.Faixa.variable_mappings),
        )
        .filter(models.Faixa.active.is_(True))
    }

    bloqueados = clientes_bloqueados_hoje(db)
    juros = carregar_regras(db).juros
    total = 0

    por_faixa: dict[str, list[dict]] = {}
    for c in clientes:
        por_faixa.setdefault(c["faixa"], []).append(c)

    for nome_faixa, lista in por_faixa.items():
        faixa = faixas.get(nome_faixa)
        if faixa is None:
            logger.warning("Fila automática: faixa '%s' não existe ou está inativa; %s cliente(s) ignorado(s)", nome_faixa, len(lista))
            continue
        templates = {e.template_id: e.template for e in faixa.envios if e.active and e.template_id}
        if not templates:
            logger.warning("Fila automática: faixa '%s' sem número/template ativo; %s cliente(s) ignorado(s)", nome_faixa, len(lista))
            continue
        fontes_por_template = {tid: _fontes(faixa, tpl) for tid, tpl in templates.items()}

        chaves = {(c["codigo"], c["vencimento_mais_antigo"]) for c in lista}
        leads = {
            (l.codigo_cliente, l.vencimento_mais_antigo): l
            for l in db.query(models.Lead)
            .options(selectinload(models.Lead.parcelas))
            .filter(models.Lead.faixa == nome_faixa, models.Lead.codigo_cliente.in_([k[0] for k in chaves]))
        }

        for chave in chaves:
            lead = leads.get(chave)
            if lead is None or lead.codigo_cliente in bloqueados:
                continue
            if not lead.celular or not is_valid_phone(lead.celular):
                continue  # sem telefone válido: fica só em Leads
            contexto = _contexto_lead(lead, juros)

            faltando: list[str] = []
            por_template: dict[str, dict[str, str]] = {}
            for tid, fontes in fontes_por_template.items():
                valores: dict[str, str] = {}
                for v, fonte in fontes:
                    val = resolver_variaveis([fonte], contexto)[v.internal_name] if fonte else ""
                    if not val:
                        faltando.append(v.internal_name)
                    valores[v.internal_name] = val
                por_template[tid] = valores
            # Mesmo formato do upload: achatado com um template, um dict por template com mais de um.
            variables_json = next(iter(por_template.values())) if len(por_template) == 1 else por_template

            item = models.QueueItem(
                faixa_id=faixa.id,
                codigo_cliente=lead.codigo_cliente,
                nome=primeiro_nome(lead.nome),
                cpf=formatar_cpf(lead.cpf),
                valor=str(lead.valor_cobrar),
                celular=normalize_phone(lead.celular),
                celular_original=lead.celular_original or lead.celular,
                variables_json=variables_json,
                status=models.QueueStatus.pending,
                lojas=lojas_formatadas(lead.lojas),
            )
            if faltando:
                item.status = models.QueueStatus.error
                item.error_message = f"Variável sem valor na extração automática: {', '.join(sorted(set(faltando)))}"
            db.add(item)
            bloqueados.add(lead.codigo_cliente)
            if not faltando:
                total += 1

    db.commit()
    return total


def ultimo_fim_de_janela(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> datetime:
    """Instante (UTC ingênuo) do fim de janela mais recente já passado."""

    local_now = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ)
    fim = time.fromisoformat(global_config.schedule_end)
    fim_hoje = datetime.combine(local_now.date(), fim, BUSINESS_TZ)
    if local_now < fim_hoje:
        fim_hoje -= timedelta(days=1)
    return _utc_ingenuo(fim_hoje)


def expirar_nao_enviados(db: Session, global_config: models.GlobalDispatchConfig, now_utc: datetime) -> tuple[int, int]:
    """Exclui da fila o que entrou antes do último fim de janela e não saiu
    (pendente), e os leads da extração automática desse período que não
    chegaram a ser cobrados. Devolve (itens_excluidos, leads_excluidos)."""

    corte = ultimo_fim_de_janela(global_config, now_utc)
    itens = (
        db.query(models.QueueItem)
        .filter(models.QueueItem.status == models.QueueStatus.pending, models.QueueItem.created_at < corte)
        .delete(synchronize_session=False)
    )
    leads = 0
    for lead in db.query(models.Lead).filter(
        models.Lead.created_by.is_(None),  # só os da extração automática
        models.Lead.status == "novo",
        models.Lead.created_at < corte,
    ):
        db.delete(lead)  # ORM, pra levar as parcelas junto
        leads += 1
    if itens or leads:
        db.commit()
        logger.info("Expirados após o horário final: %s item(ns) da fila, %s lead(s)", itens, leads)
    return itens, leads
