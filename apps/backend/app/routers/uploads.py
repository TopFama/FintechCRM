from datetime import datetime, time

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.document import extract_first_name, format_cpf, normalize_seta_code
from ..utils.phone import is_valid_phone, normalize_phone
from ..timezone import hoje_br
from ..utils.spreadsheet import parse_uploaded_spreadsheet, read_spreadsheet_headers
from ..variaveis_template import (
    contexto_cliente,
    extrair_placeholders,
    normalizar_chave,
    normalizar_para_meta,
    renderizar_expressao,
    validar_sintaxe,
)

router = APIRouter(prefix="/faixas", tags=["uploads"])

_TAMANHO_MAXIMO_PLANILHA_BYTES = 20 * 1024 * 1024


async def _ler_planilha_limitada(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > _TAMANHO_MAXIMO_PLANILHA_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Planilha maior que o limite de 20 MB")
    return content


def _load_faixa(db: Session, faixa_id: str) -> models.Faixa:
    faixa = (
        db.query(models.Faixa)
        .options(
            selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.template).selectinload(
                models.Template.variables
            ),
            selectinload(models.Faixa.variable_mappings),
        )
        .filter(models.Faixa.id == faixa_id)
        .first()
    )
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    return faixa


def _templates_ativos(faixa: models.Faixa) -> dict[str, models.Template]:
    """Templates distintos entre os envios ativos da faixa — a planilha
    subida precisa alimentar as variáveis de todos eles, já que qualquer um
    pode acabar processando um item da fila (ver worker.run_dispatch_cycle)."""

    return {e.template_id: e.template for e in faixa.envios if e.active and e.template_id}


@router.post("/{faixa_id}/uploads/columns", response_model=schemas.UploadColumnsOut)
async def read_upload_columns(
    faixa_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Lê só o cabeçalho da planilha enviada, para o usuário escolher em uma
    lista suspensa qual coluna alimenta cada variável/campo."""

    _load_faixa(db, faixa_id)
    content = await _ler_planilha_limitada(file)
    try:
        columns = read_spreadsheet_headers(file.filename or "planilha.xlsx", content)
    except Exception as exc:  # noqa: BLE001 - erro de parsing vira 400 explícito
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Não foi possível ler a planilha: {exc}") from exc
    if not columns:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A planilha está vazia ou sem cabeçalho")
    return schemas.UploadColumnsOut(columns=columns)


@router.post("/{faixa_id}/uploads", response_model=schemas.UploadResult)
async def upload_planilha(
    faixa_id: str,
    file: UploadFile,
    mapping: str = Form(..., description="JSON de UploadFieldMapping"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    faixa = _load_faixa(db, faixa_id)
    templates_ativos = _templates_ativos(faixa)
    if not templates_ativos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Atribua ao menos um número e template à faixa antes de subir a planilha"
        )

    try:
        field_mapping = schemas.UploadFieldMapping.model_validate_json(mapping)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Mapeamento inválido: {exc}") from exc

    # União das variáveis de todos os templates ativos: a planilha só precisa
    # ser subida uma vez, mesmo com mais de um número/template na faixa.
    variable_by_id = {v.id: v for tpl in templates_ativos.values() for v in tpl.variables}

    # Mapeamento persistido por variável (config da faixa/template): decide se
    # a variável vem de uma coluna da planilha, de um campo fixo do cadastro
    # do cliente (Lead) ou de uma expressão — "campo_cliente" e "expressao"
    # (quando já tem expressão salva) não exigem coluna escolhida no upload.
    mapping_by_vid = {m.template_variable_id: m for m in faixa.variable_mappings}
    auto_resolved_vids = {
        vid
        for vid, m in mapping_by_vid.items()
        if m.fonte_tipo == "campo_cliente" or (m.fonte_tipo == "expressao" and m.expressao)
    }
    mapped_var_ids = set(field_mapping.variables) | set(field_mapping.expressoes) | auto_resolved_vids
    missing_vars = set(variable_by_id) - mapped_var_ids
    if missing_vars:
        names = ", ".join(variable_by_id[v].internal_name for v in missing_vars)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Faltando coluna mapeada para a(s) variável(is): {names}"
        )

    content = await _ler_planilha_limitada(file)
    filename = file.filename or "planilha.xlsx"
    try:
        headers = read_spreadsheet_headers(filename, content)
        rows = parse_uploaded_spreadsheet(filename, content)
    except Exception as exc:  # noqa: BLE001 - erro de parsing vira 400 explícito
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Não foi possível ler a planilha: {exc}") from exc

    norm_headers = {normalizar_chave(h) for h in headers if h}
    for vid, expr in field_mapping.expressoes.items():
        var = variable_by_id.get(vid)
        var_name = var.internal_name if var else vid
        erro_sintaxe = validar_sintaxe(expr)
        if erro_sintaxe:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Expressão inválida para a variável '{var_name}': {erro_sintaxe}",
            )
        placeholders = extrair_placeholders(expr)
        for p in placeholders:
            if normalizar_chave(p) not in norm_headers:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Variável '{var_name}': coluna '{p}' não encontrada na planilha",
                )

    accepted = 0
    rejected = 0
    invalid_phone_count = 0
    reasons: list[str] = []

    # Não cobrar o mesmo cliente na mesma faixa mais de uma vez por dia: bloqueia
    # quem já está pendente/reservado (nunca chegou a sair) em qualquer data, e
    # quem já foi enviado hoje — enviado em dia anterior pode voltar (cobrança
    # recorrente da mesma faixa em dias diferentes).
    inicio_hoje = datetime.combine(hoje_br(), time.min)
    clientes_bloqueados = {
        codigo
        for (codigo,) in db.query(models.QueueItem.codigo_cliente).filter(
            models.QueueItem.faixa_id == faixa_id,
            or_(
                models.QueueItem.status.in_([models.QueueStatus.pending, models.QueueStatus.reserved]),
                and_(models.QueueItem.status == models.QueueStatus.sent, models.QueueItem.sent_at >= inicio_hoje),
            ),
        )
    }

    # Base de leads (Cobrança → Leads) desta faixa, pra resolver variáveis com
    # fonte_tipo="campo_cliente" direto do cadastro, sem depender da planilha
    # subida. Quando o mesmo código aparece em mais de um lead da faixa (datas
    # de vencimento diferentes), usa o mais recente.
    leads_por_codigo: dict[str, models.Lead] = {}
    if auto_resolved_vids:
        for lead in db.query(models.Lead).filter(models.Lead.faixa == faixa.name):
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
            reasons.append(f"Linha {i}: cliente já está na fila ou já foi cobrado nesta faixa hoje")
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
            db.add(
                models.InvalidPhoneRecord(
                    faixa_id=faixa_id,
                    codigo_cliente=codigo_cliente,
                    celular_original=celular_original,
                    celular_normalizado=normalize_phone(celular_original) or None,
                    motivo="Telefone fora do padrão 55DD9XXXXXXXX (dígitos insuficientes ou inválidos)",
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
                    }
                )
            )

        missing_var_cols = []
        # Chaveado por template_variable_id (não por internal_name) — dois
        # templates distintos podem usar o mesmo internal_name pra coisas
        # diferentes, então resolver por nome colidiria entre eles.
        resolved_by_vid: dict[str, str] = {}
        for vid, v in variable_by_id.items():
            mapping = mapping_by_vid.get(vid)
            fonte_tipo = mapping.fonte_tipo if mapping else "coluna"

            if fonte_tipo == "campo_cliente":
                val = normalizar_para_meta(contexto.get(mapping.column_name or "", ""))
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

        if missing_var_cols:
            rejected += 1
            reasons.append(f"Linha {i}: faltando coluna(s) {', '.join(missing_var_cols)}")
            continue

        # Faixa com um único template ativo: dict "achatado" (formato de
        # sempre). Mais de um template ativo: um dict por template_id, já
        # que qualquer um dos envios da faixa pode processar este item (ver
        # dispatch_service.montar_parametros_envio).
        if len(templates_ativos) <= 1:
            variables_json = {
                v.internal_name: resolved_by_vid[v.id]
                for tpl in templates_ativos.values()
                for v in tpl.variables
            }
        else:
            variables_json = {
                tid: {v.internal_name: resolved_by_vid[v.id] for v in tpl.variables}
                for tid, tpl in templates_ativos.items()
            }
        db.add(
            models.QueueItem(
                faixa_id=faixa_id,
                codigo_cliente=codigo_cliente,
                nome=nome,
                cpf=cpf,
                valor=valor or None,
                celular=celular,
                celular_original=celular_original,
                variables_json=variables_json,
                status=models.QueueStatus.pending,
            )
        )
        clientes_bloqueados.add(codigo_cliente)
        accepted += 1

    faixa.upload_field_mapping = field_mapping.model_dump()

    db.add(
        models.UploadLog(
            faixa_id=faixa_id,
            filename=file.filename or "planilha.xlsx",
            uploaded_by=user.id,
            row_count=len(rows),
            accepted_count=accepted,
            rejected_count=rejected,
            invalid_phone_count=invalid_phone_count,
        )
    )
    db.commit()

    return schemas.UploadResult(
        filename=file.filename or "planilha.xlsx",
        row_count=len(rows),
        accepted_count=accepted,
        rejected_count=rejected,
        invalid_phone_count=invalid_phone_count,
        rejected_reasons=reasons[:50],
    )


@router.get("/{faixa_id}/queue", response_model=list[schemas.QueueItemOut])
def list_queue(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return (
        db.query(models.QueueItem)
        .filter(models.QueueItem.faixa_id == faixa_id)
        .order_by(models.QueueItem.created_at.desc())
        .limit(500)
        .all()
    )
