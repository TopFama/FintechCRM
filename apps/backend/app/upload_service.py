"""Importação da planilha de clientes na fila de uma faixa da régua
(POST /faixas/{id}/uploads). O router valida o mapeamento e lê o arquivo;
aqui cada linha vira item da fila, com o mesmo bloqueio de uma cobrança por
cliente por dia e a mesma blacklist dos outros caminhos."""

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session, selectinload

from . import itens_fila, models, schemas, seta_client
from .blacklist import Blacklist
from .elegibilidade import clientes_bloqueados_hoje
from .pausas import lojas_formatadas
from .regras_db import carregar_regras
from .timezone import hoje_br
from .utils.document import extract_first_name, format_cpf, normalize_seta_code
from .utils.phone import eh_fixo, escolher_telefone, is_valid_phone, normalize_phone
from .variaveis_template import normalizar_chave, normalizar_para_meta, renderizar_expressao


def _valor_decimal(valor: str | None) -> Decimal:
    """Aceita "1.234,56", "1234.56" ou "R$ 10" — o que vier na planilha."""
    texto = (valor or "").replace("R$", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _zerado(valor: str | None) -> bool:
    """Valor com número e igual a zero ("0", "0,00", "R$ 0,00"). Vazio não conta."""
    texto = (valor or "").strip()
    return any(c.isdigit() for c in texto) and _valor_decimal(texto) == 0


def importar_planilha(
    db: Session,
    faixa: models.Faixa,
    rows: list[dict],
    field_mapping: schemas.UploadFieldMapping,
    *,
    filename: str,
    usuario_id: str,
) -> schemas.UploadResult:
    """Põe na fila as linhas aceitas, registra telefone inválido e o log do
    upload, e comita. Devolve o resumo mostrado na tela."""

    templates_ativos = itens_fila.templates_ativos(faixa)
    variable_by_id = {v.id: v for tpl in templates_ativos.values() for v in tpl.variables}
    mapping_by_vid = {m.template_variable_id: m for m in faixa.variable_mappings}

    accepted = 0
    rejected = 0
    invalid_phone_count = 0
    reasons: list[str] = []

    # Celular da planilha inválido: tenta telefone2, telefone1, telefone3 e telefone4 do
    # cadastro no SETA (mesma ordem da base de cobrança). Uma consulta só.
    codigos_sem_celular = sorted(
        {
            c
            for row in rows
            if not is_valid_phone((row.get(field_mapping.celular) or "").strip())
            and (c := normalize_seta_code((row.get(field_mapping.codigo_cliente) or "").strip()))
        }
    )
    try:
        telefones_seta = seta_client.telefones_por_codigo(codigos_sem_celular)
    except seta_client.SetaIndisponivel:
        telefones_seta = {}  # SETA fora: segue como antes, telefone inválido vai pro relatório

    # Não cobrar o mesmo cliente mais de uma vez por dia, em nenhuma faixa: bloqueia
    # quem já está pendente/reservado e quem já foi enviado hoje (GMT-3).
    # Fica depois da consulta ao SETA para não segurar a trava da fila enquanto ela roda.
    clientes_bloqueados = clientes_bloqueados_hoje(db)
    blacklist = Blacklist(db)

    # Base de leads (Cobrança → Leads) desta faixa, pra resolver variáveis com
    # fonte_tipo="campo_cliente" direto do cadastro, sem depender da planilha
    # subida. Quando o mesmo código aparece em mais de um lead da faixa (datas
    # de vencimento diferentes), usa o mais recente.
    # Também usada pra criar o Lead de quem só existe na planilha: todo
    # cliente cobrado precisa aparecer em "Leads enviados".
    juros = carregar_regras(db).juros
    leads_por_codigo: dict[str, models.Lead] = {}
    for lead in (
        db.query(models.Lead)
        .options(selectinload(models.Lead.parcelas))
        .filter(models.Lead.faixa == faixa.name, models.Lead.campanha_id == "")
    ):
        atual = leads_por_codigo.get(lead.codigo_cliente)
        if atual is None or lead.created_at > atual.created_at:
            leads_por_codigo[lead.codigo_cliente] = lead

    for i, row in enumerate(rows, start=2):  # linha 1 = cabeçalho
        codigo_raw = (row.get(field_mapping.codigo_cliente) or "").strip()
        celular_original = (row.get(field_mapping.celular) or "").strip()
        nome_raw = (row.get(field_mapping.nome) or "").strip()
        cpf_raw = (row.get(field_mapping.cpf) or "").strip()
        valor = (row.get(field_mapping.valor) or "").strip() if field_mapping.valor else None

        codigo_cliente = normalize_seta_code(codigo_raw)
        if not codigo_cliente:
            rejected += 1
            reasons.append(
                f"Linha {i}: código SETA inválido ({codigo_raw or 'vazio'}) — use até 8 dígitos numéricos"
            )
            continue

        if codigo_cliente in clientes_bloqueados:
            rejected += 1
            reasons.append(f"Linha {i}: cliente já está na fila ou já foi cobrado hoje")
            continue

        if blacklist.contem(codigo_cliente, cpf_raw):
            rejected += 1
            reasons.append(f"Linha {i}: cliente na blacklist")
            continue

        if not nome_raw:
            rejected += 1
            reasons.append(f"Linha {i}: nome é obrigatório")
            continue
        nome = extract_first_name(nome_raw)

        cpf = format_cpf(cpf_raw)
        if not cpf:
            rejected += 1
            reasons.append(f"Linha {i}: CPF inválido ({cpf_raw or 'vazio'}) — use até 11 dígitos numéricos")
            continue

        if not is_valid_phone(celular_original):
            cadastro = telefones_seta.get(codigo_cliente) or {}
            alternativo, _campo = escolher_telefone(
                telefone2=cadastro.get("telefone2"),
                telefone1=cadastro.get("telefone1"),
                telefone3=cadastro.get("telefone3"),
                telefone4=cadastro.get("telefone4"),
            )
            if alternativo:
                celular_original = alternativo
        if not is_valid_phone(celular_original):
            db.add(
                models.InvalidPhoneRecord(
                    faixa_id=faixa.id,
                    codigo_cliente=codigo_cliente,
                    celular_original=celular_original,
                    celular_normalizado=normalize_phone(celular_original) or None,
                    motivo=(
                        "Telefone fixo (não recebe WhatsApp)"
                        if eh_fixo(celular_original)
                        else "Telefone fora do padrão 55DD9XXXXXXXX (dígitos insuficientes ou inválidos)"
                    ),
                )
            )
            invalid_phone_count += 1
            rejected += 1
            reasons.append(f"Linha {i}: telefone inválido ({celular_original}) — enviado ao relatório de telefones inválidos")
            continue

        celular = normalize_phone(celular_original)

        # Contexto de resolução = linha da planilha + (se existir) o cadastro
        # do cliente nesta faixa — permite variável "campo_cliente" (base
        # direta de leads, sem depender da planilha) e expressão referenciando
        # tanto coluna da planilha quanto campo do cliente.
        lead = leads_por_codigo.get(codigo_cliente)
        contexto = dict(row)
        if lead is not None:
            contexto.update(itens_fila.contexto_do_lead(lead, juros))

        missing_var_cols = []
        valor_zerado = bool(valor) and _zerado(valor)
        # Chaveado por template_variable_id (não por internal_name) — dois
        # templates distintos podem usar o mesmo internal_name pra coisas
        # diferentes, então resolver por nome colidiria entre eles.
        resolved_by_vid: dict[str, str] = {}
        for vid, v in variable_by_id.items():
            mapping = mapping_by_vid.get(vid)
            fonte_tipo = mapping.fonte_tipo if mapping else "coluna"

            coluna_valor = bool(
                vid in field_mapping.variables
                and field_mapping.valor
                and field_mapping.variables[vid] == field_mapping.valor
            )
            if coluna_valor and contexto.get("valor_atraso") and not _zerado(contexto["valor_atraso"]):
                # Variável ligada à coluna de valor da planilha passa a usar o
                # valor em atraso com juros do cliente (mesma conta da fila).
                # Cadastro sem parcelas dá zero: aí vale o da planilha.
                val = contexto["valor_atraso"]
            elif vid in field_mapping.variables:
                coluna = field_mapping.variables[vid]
                raw_val = (row.get(coluna) or "").strip()
                # Coluna "Nome"/"NOME"/"nome" no template vira só o primeiro nome
                if normalizar_chave(coluna) == "nome":
                    raw_val = extract_first_name(raw_val)
                val = normalizar_para_meta(raw_val)
            elif vid in field_mapping.expressoes:
                val = renderizar_expressao(field_mapping.expressoes[vid], contexto)
            elif fonte_tipo == "expressao" and mapping and mapping.expressao:
                val = renderizar_expressao(mapping.expressao, contexto)
            else:
                raw_val = (row.get(field_mapping.variables.get(vid, "")) or "").strip()
                val = normalizar_para_meta(raw_val)

            if not val:
                missing_var_cols.append(v.internal_name)
            else:
                resolved_by_vid[vid] = val
                if coluna_valor and _zerado(val):
                    valor_zerado = True

        variables_json = itens_fila.formato_variaveis(
            {
                tid: {v.internal_name: resolved_by_vid.get(v.id, "") for v in tpl.variables}
                for tid, tpl in templates_ativos.items()
            }
        )

        # Campo essencial do template em branco: mantém o cliente na fila,
        # mas já como erro de envio (não silenciosamente descartado do
        # upload), pra aparecer na fila/relatórios com o motivo.
        if missing_var_cols:
            itens_fila.novo_item(
                db,
                erro=f"Faltando coluna(s) {', '.join(missing_var_cols)}",
                faixa_id=faixa.id,
                codigo_cliente=codigo_cliente,
                nome=nome,
                cpf=cpf,
                valor=valor or None,
                celular=celular,
                celular_original=celular_original,
                variables_json=variables_json,
            )
            rejected += 1
            reasons.append(f"Linha {i}: faltando coluna(s) {', '.join(missing_var_cols)}")
            continue

        # Valor zerado não é cobrado: vai para os erros com o motivo.
        if valor_zerado:
            itens_fila.novo_item(
                db,
                erro="Valor zerado",
                faixa_id=faixa.id,
                codigo_cliente=codigo_cliente,
                nome=nome,
                cpf=cpf,
                valor=valor or None,
                celular=celular,
                celular_original=celular_original,
                variables_json=variables_json,
            )
            rejected += 1
            reasons.append(f"Linha {i}: valor zerado — enviado aos erros")
            continue

        itens_fila.novo_item(
            db,
            faixa_id=faixa.id,
            codigo_cliente=codigo_cliente,
            nome=nome,
            cpf=cpf,
            valor=valor or None,
            celular=celular,
            celular_original=celular_original,
            variables_json=variables_json,
        )
        # A mesma planilha pode repetir o cliente: só a primeira linha entra
        clientes_bloqueados.add(codigo_cliente)
        if lead is None:
            lead = models.Lead(
                codigo_cliente=codigo_cliente,
                nome=nome_raw,
                cpf=cpf,
                celular=celular,
                celular_origem="planilha",
                celular_original=celular_original,
                cluster="Planilha",
                faixa=faixa.name,
                dias_atraso=0,
                valor_cobrar=_valor_decimal(valor),
                valor_em_aberto=_valor_decimal(valor),
                vencimento_mais_antigo=hoje_br(),
                status="novo",
                created_by=usuario_id,
            )
            db.add(lead)
            leads_por_codigo[codigo_cliente] = lead
        clientes_bloqueados.add(codigo_cliente)
        accepted += 1

    faixa.upload_field_mapping = field_mapping.model_dump()

    # Loja do item vem do Lead do cliente (qualquer faixa, o mais recente com
    # loja), numa consulta só. Sem Lead fica "," e pausa por loja não o pega.
    novos = [o for o in db.new if isinstance(o, models.QueueItem)]
    if novos:
        lojas_por_codigo: dict[str, str] = {}
        for codigo, lojas in (
            db.query(models.Lead.codigo_cliente, models.Lead.lojas)
            .filter(models.Lead.codigo_cliente.in_({i.codigo_cliente for i in novos}), models.Lead.lojas != ",")
            .order_by(models.Lead.created_at.asc())
        ):
            lojas_por_codigo[codigo] = lojas
        for item in novos:
            item.lojas = lojas_formatadas(lojas_por_codigo.get(item.codigo_cliente, ","))

    db.add(
        models.UploadLog(
            faixa_id=faixa.id,
            filename=filename,
            uploaded_by=usuario_id,
            row_count=len(rows),
            accepted_count=accepted,
            rejected_count=rejected,
            invalid_phone_count=invalid_phone_count,
        )
    )
    db.commit()

    return schemas.UploadResult(
        filename=filename,
        row_count=len(rows),
        accepted_count=accepted,
        rejected_count=rejected,
        invalid_phone_count=invalid_phone_count,
        rejected_reasons=reasons[:50],
    )
