"""Retenta o erro 131026 no mesmo item, sem duplicar a cobrança do cliente."""

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import campanhas_fixas, chatwoot_client, elegibilidade, models, seta_client
from .utils.phone import ORDEM_TELEFONES, is_valid_phone, normalize_phone

logger = logging.getLogger("dispatch_worker")
PREFIXO_MENSAGEM_CHATWOOT = "chatwoot:"
_proxima_sincronizacao = datetime.min
_ultimo_id = ""


def detalhe_telefone_invalido(valor) -> str | None:
    """Lê apenas campos de erro: conteúdo, CPF e IDs podem conter 131026."""
    if isinstance(valor, dict):
        atributos = valor.get("content_attributes")
        candidatos = [valor.get(c) for c in ("external_error", "error", "message", "detail", "code", "errors")]
        if isinstance(atributos, dict):
            candidatos.insert(0, atributos.get("external_error"))
        return next((d for v in candidatos if (d := detalhe_telefone_invalido(v))), None)
    if isinstance(valor, (list, tuple)):
        return next((d for v in valor if (d := detalhe_telefone_invalido(v))), None)
    texto = str(valor or "")
    if re.search(r"(?<!\d)131026(?!\d)", texto) or "message undeliverable" in texto.lower():
        return texto
    return None


def mensagem_telefone_invalido(detalhe: str) -> str:
    if detalhe.startswith("Chatwoot:"):
        return detalhe
    return f"Chatwoot: mensagem não entregue pelo WhatsApp — Detalhes: {detalhe}"


def identificador_chatwoot(conversation_id: int, message_id: object) -> str:
    return f"{PREFIXO_MENSAGEM_CHATWOOT}{conversation_id}:{message_id}"


def _filtro_erro():
    return or_(
        models.QueueItem.error_message.ilike("%131026%"),
        models.QueueItem.error_message.ilike("%message undeliverable%"),
    )


def _desmarcar_lead(db: Session, item: models.QueueItem) -> None:
    if not item.sent_at:
        return
    faixa = db.get(models.Faixa, item.faixa_id)
    if faixa is None:
        return
    if faixa.tipo == models.TIPO_CAMPANHA:
        filtros = [models.Lead.campanha_id == faixa.campanha_id]
    elif faixa.tipo == models.TIPO_REMARKETING and faixa.remarketing_segmento:
        filtros = [models.Lead.campanha_id == campanhas_fixas.id_campanha(faixa.remarketing_segmento)]
    else:
        filtros = [models.Lead.faixa == faixa.name, models.Lead.campanha_id == ""]
    db.query(models.Lead).filter(
        models.Lead.codigo_cliente == item.codigo_cliente,
        models.Lead.status == "cobrado",
        models.Lead.cobrado_em == item.sent_at,
        *filtros,
    ).update({"status": "novo", "cobrado_em": None}, synchronize_session=False)


def registrar_falha(db: Session, item: models.QueueItem, detalhe: str) -> None:
    _desmarcar_lead(db, item)
    item.status = models.QueueStatus.error
    item.error_message = mensagem_telefone_invalido(detalhe)
    item.sent_at = None


def _substituir_variaveis(valor, anterior: str, novo: str):
    if isinstance(valor, dict):
        return {k: _substituir_variaveis(v, anterior, novo) for k, v in valor.items()}
    if isinstance(valor, str) and normalize_phone(valor) == anterior:
        return novo
    return valor


def reprocessar_erros_chatwoot(db: Session, limite: int = 200) -> int:
    itens = db.query(models.QueueItem).filter(
        models.QueueItem.status.in_((models.QueueStatus.error, models.QueueStatus.sent)),
        _filtro_erro(),
    ).order_by(models.QueueItem.created_at, models.QueueItem.id).limit(limite).all()
    itens = [i for i in itens if detalhe_telefone_invalido(i.error_message)]
    if not itens:
        return 0
    # Consulta externa antes da trava compartilhada com as outras entradas na fila.
    cadastros = seta_client.telefones_por_codigo(sorted({i.codigo_cliente for i in itens}))
    elegibilidade.travar_entrada_na_fila(db)
    for item in itens:
        db.refresh(item, with_for_update=True)
        if item.status not in (models.QueueStatus.error, models.QueueStatus.sent):
            continue
        detalhe = detalhe_telefone_invalido(item.error_message)
        if not detalhe:
            continue
        anterior = normalize_phone(item.celular)
        tentados = set(item.telefones_tentados or [])
        tentados.add(anterior)
        item.telefones_tentados = sorted(tentados)
        _desmarcar_lead(db, item)
        item.sent_at = None
        item.status = models.QueueStatus.invalid_phone
        db.flush()
        # Quem já voltou por outra base ou recebeu depois desta tentativa não é reenviado.
        outro = db.query(models.QueueItem.id).filter(
            models.QueueItem.codigo_cliente == item.codigo_cliente,
            models.QueueItem.id != item.id,
            or_(
                models.QueueItem.status.in_((models.QueueStatus.pending, models.QueueStatus.reserved)),
                models.QueueItem.sent_at >= item.created_at,
            ),
        ).first()
        registro_id = f"chatwoot-131026-{item.id}"
        db.query(models.InvalidPhoneRecord).filter_by(id=registro_id).delete(synchronize_session=False)
        db.query(models.ErrorLog).filter(
            models.ErrorLog.queue_item_id == item.id,
            or_(models.ErrorLog.message.ilike("%131026%"),
                models.ErrorLog.message.ilike("%message undeliverable%")),
        ).delete(synchronize_session=False)
        if outro:
            item.error_message = None
            continue
        cadastro = cadastros.get(item.codigo_cliente, {})
        novo = next((
            (normalize_phone(raw), raw)
            for campo in ORDEM_TELEFONES
            if (raw := cadastro.get(campo)) and is_valid_phone(raw)
            and normalize_phone(raw) not in tentados
        ), None)
        if novo:
            item.celular, item.celular_original = novo
            item.variables_json = _substituir_variaveis(item.variables_json or {}, anterior, novo[0])
            item.status = models.QueueStatus.pending
            item.error_message = None
            item.whatsapp_message_id = None
            item.whatsapp_number_id = None
            item.reserved_by = None
            # A expiração diária não deve apagar uma retentativa recém-criada.
            item.created_at = datetime.utcnow()
        else:
            db.add(models.InvalidPhoneRecord(
                id=registro_id, faixa_id=item.faixa_id, codigo_cliente=item.codigo_cliente,
                cpf=item.cpf or "", celular_original=item.celular_original or item.celular,
                celular_normalizado=anterior, motivo=mensagem_telefone_invalido(detalhe),
            ))
        db.flush()
    db.commit()
    return len(itens)


async def sincronizar_retornos_chatwoot(db: Session, limite: int = 100) -> int:
    """Percorre os IDs em rodízio para mensagens sem retorno não bloquearem as novas."""
    global _proxima_sincronizacao, _ultimo_id
    agora = datetime.utcnow()
    if agora < _proxima_sincronizacao:
        return 0
    _proxima_sincronizacao = agora + timedelta(seconds=30)
    if not chatwoot_client.is_configured(db):
        return 0
    consulta = db.query(models.QueueItem).filter(
        models.QueueItem.status == models.QueueStatus.sent,
        models.QueueItem.whatsapp_message_id.like(f"{PREFIXO_MENSAGEM_CHATWOOT}%"),
    )
    itens = consulta.filter(models.QueueItem.id > _ultimo_id).order_by(models.QueueItem.id).limit(limite).all()
    if not itens:
        _ultimo_id = ""
        return 0
    _ultimo_id = itens[-1].id
    client = chatwoot_client.cliente_configurado(db)
    alterados = 0
    for item in itens:
        identificador = item.whatsapp_message_id
        partes = identificador.split(":")
        if len(partes) != 3 or not partes[1].isdigit() or not partes[2].isdigit():
            continue
        try:
            mensagem = await client.obter_mensagem(int(partes[1]), int(partes[2]))
        except Exception:  # noqa: BLE001 - falha de consulta não autoriza outro envio
            logger.exception("Falha ao consultar retorno do envio %s", item.id)
            continue
        if not mensagem:
            continue
        db.refresh(item)
        if item.status != models.QueueStatus.sent or item.whatsapp_message_id != identificador:
            continue
        if mensagem.get("status") in ("delivered", "read", 1, 2):
            item.whatsapp_message_id = identificador.replace("chatwoot:", "chatwoot-ok:", 1)
            alterados += 1
        elif (detalhe := detalhe_telefone_invalido(mensagem)):
            registrar_falha(db, item, detalhe)
            alterados += 1
    db.commit()
    return alterados
