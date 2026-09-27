from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from .. import itens_fila, models, schemas, upload_service
from ..database import get_db
from ..deps import get_current_user
from ..utils.spreadsheet import parse_uploaded_spreadsheet, read_spreadsheet_preview
from .comum import ler_planilha_limitada
from ..variaveis_template import (
    extrair_placeholders,
    normalizar_chave,
    validar_sintaxe,
)

router = APIRouter(prefix="/faixas", tags=["uploads"])

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
    content = await ler_planilha_limitada(file)
    try:
        columns, sample_row = read_spreadsheet_preview(file.filename or "planilha.xlsx", content)
    except Exception as exc:  # noqa: BLE001 - erro de parsing vira 400 explícito
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Não foi possível ler a planilha: {exc}") from exc
    if not columns:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A planilha está vazia ou sem cabeçalho")
    return schemas.UploadColumnsOut(columns=columns, sample_row=sample_row)


@router.post("/{faixa_id}/uploads", response_model=schemas.UploadResult)
async def upload_planilha(
    faixa_id: str,
    file: UploadFile,
    mapping: str = Form(..., description="JSON de UploadFieldMapping"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    faixa = _load_faixa(db, faixa_id)
    if faixa.tipo != models.TIPO_REGUA:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Faixa de campanha ou de remarketing recebe clientes pela tela Campanhas, não por planilha",
        )
    templates_ativos = itens_fila.templates_ativos(faixa)
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
    # Na importação toda variável vem de coluna da planilha; "campo_cliente"
    # da config do envio só vale pra envios gerados dentro do sistema.
    auto_resolved_vids = {
        vid for vid, m in mapping_by_vid.items() if m.fonte_tipo == "expressao" and m.expressao
    }
    mapped_var_ids = set(field_mapping.variables) | set(field_mapping.expressoes) | auto_resolved_vids
    missing_vars = set(variable_by_id) - mapped_var_ids
    if missing_vars:
        names = ", ".join(variable_by_id[v].internal_name for v in missing_vars)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Faltando coluna mapeada para a(s) variável(is): {names}"
        )

    content = await ler_planilha_limitada(file)
    filename = file.filename or "planilha.xlsx"
    try:
        headers, _ = read_spreadsheet_preview(filename, content)
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

    return upload_service.importar_planilha(
        db, faixa, rows, field_mapping, filename=file.filename or "planilha.xlsx", usuario_id=user.id
    )


QueueSortColumn = Literal["codigo_cliente", "nome", "cpf", "celular", "valor", "status", "error_message"]

_QUEUE_SORT_COLUNAS = {
    "codigo_cliente": models.QueueItem.codigo_cliente,
    "nome": models.QueueItem.nome,
    "cpf": models.QueueItem.cpf,
    "celular": models.QueueItem.celular,
    "valor": models.QueueItem.valor,
    "status": models.QueueItem.status,
    "error_message": models.QueueItem.error_message,
}


@router.get("/{faixa_id}/queue", response_model=schemas.QueueItemPage)
def list_queue(
    faixa_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: QueueSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = db.query(models.QueueItem).filter(models.QueueItem.faixa_id == faixa_id)
    total = query.count()
    coluna = _QUEUE_SORT_COLUNAS.get(sort_by) if sort_by else None
    if coluna is not None:
        # id como desempate: mantém a ordem estável entre páginas
        query = query.order_by(coluna.desc() if sort_dir == "desc" else coluna.asc(), models.QueueItem.id)
    else:
        query = query.order_by(models.QueueItem.created_at.desc())
    itens = query.offset(offset).limit(limit).all()
    return schemas.QueueItemPage(total=total, itens=itens)
