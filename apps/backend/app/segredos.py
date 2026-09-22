"""Gerenciamento de segredos cifrados no banco de dados.

Contém as rotinas de inicialização chamadas no lifespan: re-criptografia de
segredos legados para a nova chave primária e importação pontual de token
legado presente em variável de ambiente.
"""

import logging
import os

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

    if total_recifrados > 0:
        db.commit()

    logger.info("Re-criptografia concluída: %d segredo(s) atualizado(s)", total_recifrados)
    return total_recifrados


def importar_token_legado(db: Session) -> bool:
    """Importa o token de META_ACCESS_TOKEN do ambiente para a tabela meta_tokens.

    Executado na subida se a variável de ambiente existir e nenhum registro
    no banco contiver esse mesmo token. Idempotente.
    """
    env_token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not env_token:
        return False

    tokens_existentes = db.query(models.MetaToken).all()
    for t in tokens_existentes:
        if crypto.decifrar(t.token_cifrado) == env_token:
            return False

    ultimos4 = env_token[-4:] if len(env_token) >= 4 else env_token
    novo = models.MetaToken(
        nome="Token importado do .env",
        token_cifrado=crypto.cifrar(env_token),
        ultimos4=ultimos4,
        ativo=True,
    )
    db.add(novo)
    db.commit()

    logger.warning(
        "Token da Meta importado do .env para a tabela meta_tokens ('Token importado do .env'). "
        "Remova META_ACCESS_TOKEN do .env e vincule os números a ele na tela Números."
    )
    return True
