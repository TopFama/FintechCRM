"""Fila automática: leads extraídos pelo agendador entram direto na fila de
disparo da faixa (sem exportar/subir planilha), e o que não saiu até o fim
da janela é descartado — os dados (valor, dias de atraso) ficam obsoletos
de um dia pro outro."""

import logging
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session, selectinload

from . import itens_fila, models, seta_client
from .elegibilidade import clientes_bloqueados_hoje
from .pausas import lojas_formatadas
from .regras_db import carregar_regras
from .timezone import BUSINESS_TZ, inicio_hoje_utc, para_br, utc_ingenuo
from .utils.leads_xlsx import formatar_cpf, primeiro_nome
from .utils.phone import is_valid_phone, normalize_phone
from .variaveis_template import contexto_cliente, resolver_variaveis

logger = logging.getLogger("fila_automatica")


def enfileirar_clientes(
    db: Session,
    faixa: models.Faixa,
    clientes: list[dict],
    *,
    bloqueados: set[str],
    juros,
    parcelas: dict[str, list[dict]],
    origem: str,
    colunas_extras: dict[str, dict[str, str]] | None = None,
    enfileirados: list[dict] | None = None,
) -> int:
    """Coloca na fila de `faixa` clientes vindos direto do SETA (formato de
    `cobranca_base._montar_cliente`), resolvendo as variáveis de cada template
    ativo. Pula quem está em `bloqueados` (e o acrescenta ali) ou não tem
    telefone válido; variável sem valor vira item com erro.
    `colunas_extras` (por código) entram no contexto das variáveis como
    colunas de planilha, valendo mais que os campos do cliente. Não comita.
    Devolve quantos entraram como pendentes (e os acrescenta a `enfileirados`)."""

    templates = itens_fila.templates_ativos(faixa)
    if not templates:
        logger.warning("%s: faixa '%s' sem número/template ativo; %s cliente(s) ignorado(s)", origem, faixa.name, len(clientes))
        return 0
    fontes_por_template = itens_fila.fontes_por_template(faixa, templates)
    total = 0
    for cliente in clientes:
        if cliente["codigo"] in bloqueados or not cliente.get("celular") or not is_valid_phone(cliente["celular"]):
            continue
        contexto = contexto_cliente({**cliente, "parcelas": parcelas.get(cliente["codigo"], []), "juros": juros})
        if colunas_extras and cliente["codigo"] in colunas_extras:
            contexto.update(colunas_extras[cliente["codigo"]])
        variables_json, faltando = itens_fila.resolver_por_template(fontes_por_template, contexto)
        itens_fila.novo_item(
            db,
            erro=f"Variável sem valor {origem}: {', '.join(sorted(set(faltando)))}" if faltando else None,
            faixa_id=faixa.id,
            codigo_cliente=cliente["codigo"],
            nome=primeiro_nome(cliente["nome"]),
            cpf=formatar_cpf(cliente["cpfcnpj"]),
            valor=str(cliente["valor_cobrar"]),
            celular=normalize_phone(cliente["celular"]),
            celular_original=cliente.get("celular_original") or cliente["celular"],
            variables_json=variables_json,
            lojas=lojas_formatadas(cliente.get("lojas")),
            faixa_atraso=cliente.get("faixa") or None,
        )
        if not faltando:
            total += 1
            if enfileirados is not None:
                enfileirados.append(cliente)
        bloqueados.add(cliente["codigo"])
    return total


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
        .filter(models.Faixa.active.is_(True), models.Faixa.tipo == models.TIPO_REGUA)
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
        templates = itens_fila.templates_ativos(faixa)
        if not templates:
            logger.warning("Fila automática: faixa '%s' sem número/template ativo; %s cliente(s) ignorado(s)", nome_faixa, len(lista))
            continue
        fontes_por_template = itens_fila.fontes_por_template(faixa, templates)

        chaves = {(c["codigo"], c["vencimento_mais_antigo"]) for c in lista}
        leads = {
            (l.codigo_cliente, l.vencimento_mais_antigo): l
            for l in db.query(models.Lead)
            .options(selectinload(models.Lead.parcelas))
            .filter(
                models.Lead.faixa == nome_faixa,
                models.Lead.campanha_id == "",
                models.Lead.codigo_cliente.in_([k[0] for k in chaves]),
            )
        }

        # Lead de outro dia (mesma faixa e vencimento): os dados dele são os do
        # dia em que foi criado. A mensagem usa os da base de hoje e as parcelas
        # atuais, sem mexer no Lead (as parcelas dele são o retrato da cobrança
        # daquele dia, usado na efetividade).
        cliente_por_chave = {(c["codigo"], c["vencimento_mais_antigo"]): c for c in lista}
        antigos = [
            l.codigo_cliente
            for k, l in leads.items()
            if k in chaves and l.created_at < inicio_hoje_utc() and "dias_atraso" in cliente_por_chave[k]
        ]
        parcelas_atuais = seta_client.buscar_parcelas_cobranca(antigos, juros=juros) if antigos else {}

        for chave in chaves:
            lead = leads.get(chave)
            if lead is None or lead.codigo_cliente in bloqueados:
                continue
            if not lead.celular or not is_valid_phone(lead.celular):
                continue  # sem telefone válido: fica só em Leads
            contexto = itens_fila.contexto_lead_exportado(lead, juros)
            valor = lead.valor_cobrar
            if lead.codigo_cliente in parcelas_atuais:
                atual = cliente_por_chave[chave]
                contexto.update(
                    contexto_cliente({**atual, "parcelas": parcelas_atuais[lead.codigo_cliente], "juros": juros})
                )
                valor = atual["valor_cobrar"]
            variables_json, faltando = itens_fila.resolver_por_template(fontes_por_template, contexto)
            itens_fila.novo_item(
                db,
                erro=(
                    f"Variável sem valor na extração automática: {', '.join(sorted(set(faltando)))}"
                    if faltando
                    else None
                ),
                faixa_id=faixa.id,
                codigo_cliente=lead.codigo_cliente,
                nome=primeiro_nome(lead.nome),
                cpf=formatar_cpf(lead.cpf),
                valor=str(valor),
                celular=normalize_phone(lead.celular),
                celular_original=lead.celular_original or lead.celular,
                variables_json=variables_json,
                lojas=lojas_formatadas(lead.lojas),
            )
            bloqueados.add(lead.codigo_cliente)
            if not faltando:
                total += 1

    db.commit()
    return total


def reaplicar_variaveis(db: Session, faixa: models.Faixa) -> tuple[int, int]:
    """Recalcula as variáveis dos pendentes da faixa com o mapeamento atual
    (usado depois de editar as variáveis de uma faixa pausada). A fonte é o
    Lead do cliente; variável que não resolve pelo Lead (ex.: coluna que só
    existia na planilha) mantém o valor que já estava. Devolve
    (itens_atualizados, itens_sem_cadastro)."""

    templates = itens_fila.templates_ativos(faixa)
    itens = (
        db.query(models.QueueItem)
        .filter(
            models.QueueItem.faixa_id == faixa.id,
            models.QueueItem.status.in_((models.QueueStatus.pending, models.QueueStatus.reserved)),
        )
        .all()
    )
    if not templates or not itens:
        return 0, 0
    leads: dict[str, models.Lead] = {}
    for lead in (
        db.query(models.Lead)
        .options(selectinload(models.Lead.parcelas))
        .filter(models.Lead.codigo_cliente.in_({i.codigo_cliente for i in itens}))
        .order_by(models.Lead.created_at.asc())
    ):
        # o da própria faixa vale mais; entre iguais, o mais recente
        atual = leads.get(lead.codigo_cliente)
        if atual is None or lead.faixa == faixa.name or atual.faixa != faixa.name:
            leads[lead.codigo_cliente] = lead
    juros = carregar_regras(db).juros
    fontes_por_template = itens_fila.fontes_por_template(faixa, templates)

    atualizados = sem_cadastro = 0
    for item in itens:
        lead = leads.get(item.codigo_cliente)
        if lead is None:
            sem_cadastro += 1
            continue
        contexto = itens_fila.contexto_lead_exportado(lead, juros)
        antigo = item.variables_json or {}
        por_template: dict[str, dict[str, str]] = {}
        for tid, fontes in fontes_por_template.items():
            anterior = antigo.get(tid) if isinstance(antigo.get(tid), dict) else antigo
            valores: dict[str, str] = {}
            for v, fonte in fontes:
                val = resolver_variaveis([fonte], contexto)[v.internal_name] if fonte else ""
                valores[v.internal_name] = val or str(anterior.get(v.internal_name, "") or "")
            por_template[tid] = valores
        novo = itens_fila.formato_variaveis(por_template)
        if novo != antigo:
            item.variables_json = novo
            atualizados += 1
    db.commit()
    return atualizados, sem_cadastro


def ultimo_fim_de_janela(global_config: models.GlobalDispatchConfig, now_utc: datetime) -> datetime:
    """Instante (UTC ingênuo) do fim de janela mais recente já passado."""

    local_now = para_br(now_utc)
    fim = time.fromisoformat(global_config.schedule_end)
    fim_hoje = datetime.combine(local_now.date(), fim, BUSINESS_TZ)
    if local_now < fim_hoje:
        fim_hoje -= timedelta(days=1)
    return utc_ingenuo(fim_hoje)


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
    # Reservado de antes do corte = envio interrompido (backend reiniciou no meio
    # do lote). Sem isso ficava reservado para sempre e bloqueava o cliente em
    # toda fila. Vira erro, que não segura o cliente e aparece em Erros.
    interrompidos = (
        db.query(models.QueueItem)
        .filter(models.QueueItem.status == models.QueueStatus.reserved, models.QueueItem.created_at < corte)
        .update(
            {
                models.QueueItem.status: models.QueueStatus.error,
                models.QueueItem.error_message: "Envio interrompido (o sistema reiniciou durante o disparo); confira se a mensagem chegou antes de reenviar",
            },
            synchronize_session=False,
        )
    )
    leads = 0
    for lead in db.query(models.Lead).filter(
        models.Lead.created_by.is_(None),  # só os da extração automática
        models.Lead.status == "novo",
        models.Lead.created_at < corte,
    ):
        db.delete(lead)  # ORM, pra levar as parcelas junto
        leads += 1
    if itens or leads or interrompidos:
        db.commit()
        logger.info("Expirados após o horário final: %s item(ns) da fila, %s lead(s)", itens, leads)
    return itens, leads


def descartar_pendentes(db: Session, ids: list[str]) -> int:
    """"Descartar fila": apaga os pendentes escolhidos, como a expiração do fim
    do dia faz (sem registro "parado"); o cliente pode voltar à fila depois.
    Item que um envio já reservou fica. Comita e devolve quantos saíram."""

    total = 0
    for i in range(0, len(ids), 1000):
        lote = ids[i : i + 1000]
        db.query(models.ErrorLog).filter(models.ErrorLog.queue_item_id.in_(lote)).update(
            {models.ErrorLog.queue_item_id: None}, synchronize_session=False
        )
        total += (
            db.query(models.QueueItem)
            .filter(models.QueueItem.id.in_(lote), models.QueueItem.status == models.QueueStatus.pending)
            .delete(synchronize_session=False)
        )
    db.commit()
    return total
