"""Gerenciamento de segredos cifrados no banco de dados.

Chamado na subida do backend (lifespan): re-cifra com a ENCRYPTION_KEY os
segredos que ainda estejam sob a chave legada. Tokens da Meta vêm só do banco,
cadastrados na tela de Configurações — nunca do ambiente.
"""

import logging

from sqlalchemy.orm import Session

from . import crypto, models

logger = logging.getLogger(__name__)


def recifrar_segredos(db: Session) -> int:
    """Re-cifra segredos no banco que ainda estão sob a chave legada.

    Segredos que já abrem com a chave nova são ignorados (idempotente).
    Segredos que não abrem com nenhuma chave são deixados intocados com log de aviso.
    Nunca loga o valor dos segredos.
    """
    total_recifrados = 0

    tokens = db.query(models.MetaToken).all()
    for token in tokens:
        if not token.token_cifrado:
            continue
        if crypto.decifrar_chave_nova(token.token_cifrado) is not None:
            continue
        recifrado = crypto.recifrar(token.token_cifrado)
        if recifrado is not None:
            token.token_cifrado = recifrado
            total_recifrados += 1
        else:
            logger.warning(
                "Segredo do MetaToken id=%s não pôde ser decifrado com nenhuma chave disponível",
                token.id,
            )

    integracoes = db.query(models.IntegracaoGoogle).all()
    for integracao in integracoes:
        if not integracao.refresh_token_cifrado:
            continue
        if crypto.decifrar_chave_nova(integracao.refresh_token_cifrado) is not None:
            continue
        recifrado = crypto.recifrar(integracao.refresh_token_cifrado)
        if recifrado is not None:
            integracao.refresh_token_cifrado = recifrado
            total_recifrados += 1
        else:
            logger.warning(
                "Segredo do IntegracaoGoogle id=%s não pôde ser decifrado com nenhuma chave disponível",
                integracao.id,
            )

    config_chatwoot = db.query(models.ConfiguracaoChatwoot).first()
    if config_chatwoot and config_chatwoot.api_access_token_cifrado:
        if crypto.decifrar_chave_nova(config_chatwoot.api_access_token_cifrado) is None:
            recifrado = crypto.recifrar(config_chatwoot.api_access_token_cifrado)
            if recifrado is not None:
                config_chatwoot.api_access_token_cifrado = recifrado
                total_recifrados += 1
            else:
                logger.warning(
                    "Segredo do ConfiguracaoChatwoot não pôde ser decifrado com nenhuma chave disponível"
                )

    if total_recifrados > 0:
        db.commit()

    logger.info("Re-criptografia concluída: %d segredo(s) atualizado(s)", total_recifrados)
    return total_recifrados

