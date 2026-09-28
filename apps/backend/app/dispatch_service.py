"""Envio de uma cobrança individual (monta os parâmetros do template e manda
pela Meta ou pelo Chatwoot, conforme o número). Extraído de worker.py: este
módulo só sabe *como* enviar um item; *quando* rodar o ciclo de disparo é
responsabilidade de worker.py (agendamento)."""

import logging
import mimetypes
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from . import campanhas_fixas, chatwoot_client, models, telefones_invalidos
from .config import settings
from .meta_client import MetaAPIError, MetaClient, MetaTokenConfigError, token_do_numero
from .utils.erros import descrever_erro_envio

logger = logging.getLogger("dispatch_worker")

# A Meta guarda a mídia enviada por 30 dias; renova antes disso.
_VALIDADE_MIDIA_META = timedelta(days=20)
# (phone_number_id, arquivo, mtime, tamanho) -> (media id, quando subiu)
_midias_meta: dict[tuple, tuple[str, datetime]] = {}


def arquivo_imagem(template: models.Template) -> str | None:
    """Arquivo local da imagem de cabeçalho (subida em Configurações → Templates)."""
    if not template.image_url:
        return None
    caminho = os.path.join(settings.media_dir, os.path.basename(urlparse(template.image_url).path))
    return caminho if os.path.isfile(caminho) else None


def link_publico_imagem(template: models.Template) -> str | None:
    """Link da imagem que um serviço de fora (Chatwoot) consegue baixar."""
    url = template.image_url
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/") + url
    return None


def _chave_midia(phone_number_id: str, caminho: str) -> tuple:
    info = os.stat(caminho)
    return (phone_number_id, caminho, info.st_mtime_ns, info.st_size)


async def media_id_da_imagem(client: MetaClient, phone_number_id: str, caminho: str) -> str:
    """Sobe a imagem do template na Meta uma vez por número (e de novo quando
    o arquivo muda ou a mídia fica velha) e reaproveita o id nos envios."""
    chave = _chave_midia(phone_number_id, caminho)
    guardado = _midias_meta.get(chave)
    if guardado and datetime.utcnow() - guardado[1] < _VALIDADE_MIDIA_META:
        return guardado[0]
    with open(caminho, "rb") as arquivo:
        conteudo = arquivo.read()
    mime = mimetypes.guess_type(caminho)[0] or "image/jpeg"
    media_id = await client.upload_media(phone_number_id, os.path.basename(caminho), conteudo, mime)
    _midias_meta[chave] = (media_id, datetime.utcnow())
    return media_id


def _esquecer_midia(phone_number_id: str, caminho: str | None) -> None:
    if caminho and os.path.isfile(caminho):
        _midias_meta.pop(_chave_midia(phone_number_id, caminho), None)


def _erro_antes_do_envio(envio: models.FaixaEnvio, item: models.QueueItem, db: Session, mensagem: str) -> None:
    """Nada saiu para o cliente: o item vira erro e o cliente fica livre no dia."""
    item.status = models.QueueStatus.error
    item.error_message = mensagem
    db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=mensagem))
    logger.warning("Envio %s não saiu: %s", item.id, mensagem)


def _sem_imagem(template: models.Template) -> str:
    return (
        f'O template "{template.name}" tem cabeçalho de imagem e nenhuma imagem foi subida '
        "(Configurações → Templates)"
    )


def montar_parametros_envio(template: models.Template, variables_json: dict) -> tuple[list[str], str | None]:
    """Body params (na ordem das variáveis do template) e link da imagem de
    cabeçalho, a partir de um dict variavel.internal_name -> valor. Usado no
    disparo de verdade (variables_json de QueueItem) e no teste de envio
    manual (Templates → Testar envio).

    Uma faixa com um único template ativo grava `variables_json` "achatado"
    (internal_name -> valor, formato de sempre). Uma faixa com mais de um
    template ativo (vários pares número+template, ver FaixaEnvio) grava por
    template — `{template_id: {internal_name: valor}}` — já que cada item
    da fila pode acabar sendo enviado por qualquer um dos envios ativos da
    faixa; aqui resolve pra qual formato veio e usa o dict certo."""

    dados = variables_json or {}
    if dados and all(isinstance(v, dict) for v in dados.values()):
        dados = dados.get(template.id, {})

    ordered_variables = sorted(template.variables, key=lambda v: v.position)
    body_params = [str(dados.get(v.internal_name, "")) for v in ordered_variables]

    header_image_link = None
    if template.header_type == models.TemplateHeaderType.image:
        header_image_link = link_publico_imagem(template)

    return body_params, header_image_link


async def enviar_item(envio: models.FaixaEnvio, item: models.QueueItem, db: Session) -> None:
    number = envio.whatsapp_number
    template = envio.template
    tpl_waba = getattr(template, "waba_id", None)
    num_waba = getattr(number, "waba_id", None)
    meta_name = getattr(template, "meta_template_name", None)
    if tpl_waba and num_waba and tpl_waba != num_waba and meta_name and hasattr(db, "query"):
        template_correto = (
            db.query(models.Template)
            .filter(
                models.Template.waba_id == num_waba,
                models.Template.meta_template_name == meta_name,
                models.Template.status == models.TemplateStatus.approved,
            )
            .first()
        )
        if template_correto:
            template = template_correto


    item.whatsapp_number_id = number.id
    item.reserved_by = envio.id

    body_params, header_image_link = montar_parametros_envio(template, item.variables_json)
    vazias = [
        v.internal_name
        for v, valor in zip(sorted(template.variables, key=lambda v: v.position), body_params)
        if not valor.strip()
    ]
    if vazias:
        # Item gravado para outro template da faixa (ou variável sem valor): a Meta
        # recusaria ou a mensagem sairia com lacuna; erro claro, sem chamar ninguém
        _erro_antes_do_envio(
            envio, item, db, f"Variável sem valor para o template {template.meta_template_name}: {', '.join(vazias)}"
        )
        return

    # Número com inbox do Chatwoot vinculada (Configurações) envia por lá;
    # os demais seguem direto pela Graph API da Meta, como sempre.
    if number.chatwoot_inbox_id:
        await _enviar_via_chatwoot(envio, item, db, number, template, body_params, header_image_link)
    else:
        await _enviar_via_meta(envio, item, db, number, template, body_params, header_image_link)


def _marcar_lead_cobrado(db: Session, item: models.QueueItem) -> None:
    """Envio real marca o lead como cobrado — é o que alimenta "Leads enviados".
    Envio de campanha marca o lead da campanha (que fica na faixa de atraso do
    cliente); envio da régua, o lead da régua daquela faixa."""
    faixa = db.get(models.Faixa, item.faixa_id)
    if faixa is None:
        return
    if faixa.tipo == models.TIPO_CAMPANHA:
        filtro = [models.Lead.campanha_id == faixa.campanha_id]
    elif faixa.tipo == models.TIPO_REMARKETING and faixa.remarketing_segmento:
        filtro = [models.Lead.campanha_id == campanhas_fixas.id_campanha(faixa.remarketing_segmento)]
    else:
        filtro = [models.Lead.faixa == faixa.name, models.Lead.campanha_id == ""]
    db.query(models.Lead).filter(
        models.Lead.codigo_cliente == item.codigo_cliente,
        *filtro,
        models.Lead.status == "novo",
    ).update({"status": "cobrado", "cobrado_em": item.sent_at}, synchronize_session=False)


def desmarcar_lead_cobrado(db: Session, item: models.QueueItem) -> None:
    """Reverte o status do lead para 'novo' quando a entrega da mensagem falha
    posteriormente (ex: notificação via webhook do Chatwoot)."""
    faixa = db.get(models.Faixa, item.faixa_id)
    if faixa is None:
        return
    if faixa.tipo == models.TIPO_CAMPANHA:
        filtro = [models.Lead.campanha_id == faixa.campanha_id]
    elif faixa.tipo == models.TIPO_REMARKETING and faixa.remarketing_segmento:
        filtro = [models.Lead.campanha_id == campanhas_fixas.id_campanha(faixa.remarketing_segmento)]
    else:
        filtro = [models.Lead.faixa == faixa.name, models.Lead.campanha_id == ""]
    db.query(models.Lead).filter(
        models.Lead.codigo_cliente == item.codigo_cliente,
        *filtro,
        models.Lead.status == "cobrado",
    ).update({"status": "novo", "cobrado_em": None}, synchronize_session=False)


def _depois_do_envio(db: Session, item: models.QueueItem) -> None:
    """Fora do try do envio: uma falha aqui não pode transformar em erro uma
    mensagem que já saiu (erro libera o cliente para outra base no mesmo dia)."""
    if item.status != models.QueueStatus.sent:
        return
    try:
        with db.begin_nested():
            _marcar_lead_cobrado(db, item)
    except Exception:  # noqa: BLE001 - o envio vale mesmo sem atualizar o lead
        logger.exception("Mensagem %s enviada, mas o lead não foi marcado como cobrado", item.id)


async def _enviar_via_meta(
    envio: models.FaixaEnvio,
    item: models.QueueItem,
    db: Session,
    number: models.WhatsappNumber,
    template: models.Template,
    body_params: list[str],
    header_image_link: str | None,
) -> None:
    try:
        token = token_do_numero(db, number)
    except MetaTokenConfigError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.warning("Falha ao obter token da Meta para envio %s: %s", item.id, exc)
        return

    client = MetaClient(access_token=token)
    # Cabeçalho de imagem: a imagem subida no sistema vai para a Meta como
    # mídia (media id), sem depender de um link público do backend.
    header_image_id = None
    caminho_imagem = None
    if template.header_type == models.TemplateHeaderType.image:
        caminho_imagem = arquivo_imagem(template)
        if caminho_imagem:
            try:
                header_image_id = await media_id_da_imagem(client, number.phone_number_id, caminho_imagem)
            except Exception as exc:  # noqa: BLE001 - sem a imagem a Meta recusaria o template
                _erro_antes_do_envio(envio, item, db, f"Falha ao subir a imagem do template para a Meta: {exc}")
                return
        elif not header_image_link:
            _erro_antes_do_envio(envio, item, db, _sem_imagem(template))
            return

    try:
        result = await client.send_template_message(
            phone_number_id=number.phone_number_id,
            to=item.celular,
            template_name=template.meta_template_name,
            language_code=template.language,
            body_params=body_params,
            header_image_link=header_image_link,
            header_image_id=header_image_id,
        )
        item.status = models.QueueStatus.sent
        item.sent_at = datetime.utcnow()
        messages = result.get("messages") or []
        if messages:
            item.whatsapp_message_id = messages[0].get("id")
    except MetaAPIError as exc:
        item.status = models.QueueStatus.error
        item.error_message = descrever_erro_envio(str(exc))
        if _falha_do_servidor(exc.status_code):
            item.sent_at = datetime.utcnow()
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.warning("Falha ao enviar cobrança %s: %s", item.id, item.error_message)
        if header_image_id:
            # mídia expirada ou recusada: o próximo envio sobe a imagem de novo
            _esquecer_midia(number.phone_number_id, caminho_imagem)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config não pode travar o item em "reserved"
        item.status = models.QueueStatus.error
        item.error_message = f"Falha inesperada ao enviar: {exc}"
        # Timeout ou queda de rede: a mensagem pode ter chegado. sent_at marca a
        # tentativa e segura o cliente pelo resto do dia (elegibilidade._cobrado_hoje).
        item.sent_at = datetime.utcnow()
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.exception("Falha inesperada ao enviar cobrança %s", item.id)
    _depois_do_envio(db, item)


def _falha_do_servidor(status_code: int) -> bool:
    """5xx ou timeout do lado da Meta/Chatwoot: a mensagem pode ter saído. Como
    na falha inesperada, sent_at segura o cliente pelo resto do dia
    (elegibilidade._cobrado_hoje). Recusa 4xx libera o cliente."""
    return status_code >= 500 or status_code == 408


async def _enviar_via_chatwoot(
    envio: models.FaixaEnvio,
    item: models.QueueItem,
    db: Session,
    number: models.WhatsappNumber,
    template: models.Template,
    body_params: list[str],
    header_image_link: str | None,
) -> None:
    try:
        client = chatwoot_client.cliente_configurado(db)
    except chatwoot_client.ChatwootConfigError as exc:
        item.status = models.QueueStatus.error
        item.error_message = str(exc)
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.warning("Falha ao obter configuração do Chatwoot para envio %s: %s", item.id, exc)
        return

    if template.header_type == models.TemplateHeaderType.image and not header_image_link:
        if not template.image_url:
            _erro_antes_do_envio(envio, item, db, _sem_imagem(template))
        else:
            _erro_antes_do_envio(
                envio, item, db,
                "O Chatwoot precisa de um link público para a imagem do template: "
                "suba a imagem de novo em Configurações → Templates",
            )
        return

    try:
        contact_id, source_id = await client.buscar_ou_criar_contato(
            number.chatwoot_inbox_id, item.celular, item.nome
        )
        conversation_id = await client.buscar_ou_criar_conversa(number.chatwoot_inbox_id, contact_id, source_id)
        result = await client.enviar_mensagem_template(
            conversation_id,
            template.body_text,
            template_name=template.meta_template_name,
            category=template.category,
            language=template.language,
            body_params=body_params,
            header_image_url=header_image_link,
        )
        result = result or {}
        if result.get("id") is not None:
            item.whatsapp_message_id = telefones_invalidos.identificador_chatwoot(conversation_id, result["id"])
        detalhe = telefones_invalidos.detalhe_telefone_invalido(result)
        if detalhe:
            telefones_invalidos.registrar_falha(db, item, detalhe)
        else:
            item.status = models.QueueStatus.sent
            item.sent_at = datetime.utcnow()
    except chatwoot_client.ChatwootAPIError as exc:
        item.status = models.QueueStatus.error
        detalhe = telefones_invalidos.detalhe_telefone_invalido(exc.payload)
        item.error_message = (
            telefones_invalidos.mensagem_telefone_invalido(detalhe) if detalhe else descrever_erro_envio(str(exc))
        )
        if detalhe:
            telefones_invalidos.registrar_falha(db, item, detalhe)
        else:
            if _falha_do_servidor(exc.status_code):
                item.sent_at = datetime.utcnow()
            db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.warning("Falha ao enviar cobrança %s via Chatwoot: %s", item.id, exc)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config não pode travar o item em "reserved"
        item.status = models.QueueStatus.error
        item.error_message = f"Falha inesperada ao enviar via Chatwoot: {exc}"
        # Timeout ou queda de rede: a mensagem pode ter chegado. sent_at marca a
        # tentativa e segura o cliente pelo resto do dia (elegibilidade._cobrado_hoje).
        item.sent_at = datetime.utcnow()
        db.add(models.ErrorLog(faixa_id=envio.faixa_id, queue_item_id=item.id, message=item.error_message))
        logger.exception("Falha inesperada ao enviar cobrança %s via Chatwoot", item.id)
    _depois_do_envio(db, item)
