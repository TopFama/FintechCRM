"""Testes de segredos, criptografia e tokens da Meta (Tarefa K).

Executado com asserts simples sem pytest, encerrando com 'OK'.
"""

import asyncio
import base64
import hashlib
import os
import tempfile
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
import httpx

TEST_DB_URL = "postgresql+psycopg://postgres:t@localhost:15432/agy_k"
TEST_JWT_SECRET = "jwt-secret-para-testes-de-segredos-123456789"
TEST_ENC_KEY = Fernet.generate_key().decode()

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ["ADMIN_PASSWORD"] = "test-admin-password-xyz-987"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = TEST_ENC_KEY
os.environ.pop("META_ACCESS_TOKEN", None)

from app import crypto, models
from app.config import settings
from app.database import SessionLocal
from app.main import EXEMPLO_ENCRYPTION_KEY, _check_secrets, _run_migrations
from app.meta_client import MetaAPIError, MetaClient, MetaTokenConfigError, token_da_waba, token_do_numero
from app.segredos import importar_token_legado, recifrar_segredos
from app.worker import run_dispatch_cycle

# 1. Migrações antes de qualquer operação de banco
_run_migrations()

# Limpa registros de execuções anteriores
_cleanup_db = SessionLocal()
try:
    _cleanup_db.query(models.ErrorLog).delete()
    _cleanup_db.query(models.QueueItem).delete()
    _cleanup_db.query(models.DispatchConfig).delete()
    _cleanup_db.query(models.FaixaNumber).delete()
    _cleanup_db.query(models.Faixa).delete()
    _cleanup_db.query(models.TemplateVariable).delete()
    _cleanup_db.query(models.Template).delete()
    _cleanup_db.query(models.WhatsappNumber).delete()
    _cleanup_db.query(models.MetaToken).delete()
    _cleanup_db.query(models.IntegracaoGoogle).delete()
    _cleanup_db.commit()
finally:
    _cleanup_db.close()

# ============================================================================
# Teste 1: Crypto (legado, recifrar com nova chave, garbage)
# ============================================================================
legacy_raw_key = base64.urlsafe_b64encode(hashlib.sha256(TEST_JWT_SECRET.encode()).digest())
legacy_fernet = Fernet(legacy_raw_key)

plain_secret = "meu_segredo_super_confidencial"
cifrado_legado = legacy_fernet.encrypt(plain_secret.encode()).decode()

# Decifra valor cifrado com chave legada
assert crypto.decifrar(cifrado_legado) == plain_secret, "Deveria decifrar com a chave legada"
# Mas NÃO abre com a chave nova diretamente
assert crypto.decifrar_chave_nova(cifrado_legado) is None, "Não deveria abrir com a chave nova ainda"

# recifrar transforma em valor da nova chave que abre com Fernet(new_key) sozinha
cifrado_recifrado = crypto.recifrar(cifrado_legado)
assert cifrado_recifrado is not None, "recifrar falhou para token legado válido"
new_fernet = Fernet(TEST_ENC_KEY.encode())
assert new_fernet.decrypt(cifrado_recifrado.encode()).decode() == plain_secret
assert crypto.decifrar_chave_nova(cifrado_recifrado) == plain_secret
assert crypto.decifrar(cifrado_recifrado) == plain_secret

# Lixo / corrompido -> None
assert crypto.recifrar("lixo_total_invalido") is None
assert crypto.decifrar("lixo_total_invalido") is None
assert crypto.decifrar_chave_nova("lixo_total_invalido") is None

# ============================================================================
# Teste 2: Startup check (_check_secrets)
# ============================================================================
# Vazia
settings.encryption_key = ""
error_empty = False
try:
    _check_secrets()
except RuntimeError as e:
    error_empty = True
    assert "ENCRYPTION_KEY não pode ser vazia" in str(e)
    assert "Fernet.generate_key()" in str(e)
assert error_empty, "Esperava RuntimeError para ENCRYPTION_KEY vazia"

# Inválida
settings.encryption_key = "chave-invalida-que-nao-tem-32-bytes"
error_invalid = False
try:
    _check_secrets()
except RuntimeError as e:
    error_invalid = True
    assert "não é uma chave Fernet válida" in str(e)
    assert "Fernet.generate_key()" in str(e)
assert error_invalid, "Esperava RuntimeError para ENCRYPTION_KEY inválida"

# Valor de exemplo do .env.example
settings.encryption_key = EXEMPLO_ENCRYPTION_KEY
error_example = False
try:
    _check_secrets()
except RuntimeError as e:
    error_example = True
    assert "não pode ser o valor de exemplo" in str(e)
    assert "Fernet.generate_key()" in str(e)
assert error_example, "Esperava RuntimeError para valor de exemplo do .env.example"

# Chave gerada válida passa sem exceção
valid_generated = Fernet.generate_key().decode()
settings.encryption_key = valid_generated
_check_secrets()

# Restaura a chave do teste
settings.encryption_key = TEST_ENC_KEY

# ============================================================================
# Teste 3: recifrar_segredos
# ============================================================================
db = SessionLocal()
try:
    db.query(models.MetaToken).delete()
    db.query(models.IntegracaoGoogle).delete()
    db.commit()

    # Cria segredos legados
    token_legado = models.MetaToken(
        nome="Token Antigo Teste",
        token_cifrado=cifrado_legado,
        ultimos4="cial",
        ativo=True,
    )
    google_legado = models.IntegracaoGoogle(
        email="antigo@topfama.com.br",
        refresh_token_cifrado=cifrado_legado,
    )
    token_lixo = models.MetaToken(
        nome="Token Lixo",
        token_cifrado="conteudo-lixo-irrecuperavel",
        ultimos4="lixo",
        ativo=True,
    )
    db.add_all([token_legado, google_legado, token_lixo])
    db.commit()

    # Executa recifrar_segredos
    recifrados = recifrar_segredos(db)
    assert recifrados == 2, f"Esperado 2 segredos recifrados, obteve {recifrados}"

    # Ambos agora devem abrir com Fernet(TEST_ENC_KEY) sozinha
    db.refresh(token_legado)
    db.refresh(google_legado)
    db.refresh(token_lixo)

    assert new_fernet.decrypt(token_legado.token_cifrado.encode()).decode() == plain_secret
    assert new_fernet.decrypt(google_legado.refresh_token_cifrado.encode()).decode() == plain_secret
    assert crypto.decifrar_chave_nova(token_legado.token_cifrado) == plain_secret
    assert crypto.decifrar_chave_nova(google_legado.refresh_token_cifrado) == plain_secret

    # Segunda chamada: idempotente (retorna 0)
    segunda_chamada = recifrar_segredos(db)
    assert segunda_chamada == 0, f"Segunda chamada deveria recifrar 0, obteve {segunda_chamada}"

    # Registro de lixo não foi alterado
    assert token_lixo.token_cifrado == "conteudo-lixo-irrecuperavel"
finally:
    db.close()

# ============================================================================
# Teste 4: importar_token_legado
# ============================================================================
db = SessionLocal()
try:
    # Sem a variável de ambiente -> não faz nada
    os.environ.pop("META_ACCESS_TOKEN", None)
    assert importar_token_legado(db) is False

    # Com META_ACCESS_TOKEN no os.environ -> importa
    os.environ["META_ACCESS_TOKEN"] = "EAAX_token_do_env_legado_9999"
    importado = importar_token_legado(db)
    assert importado is True, "Deveria ter importado o token do ambiente"

    # Confere que o registro foi criado cifrado e com o valor correto
    t_importado = (
        db.query(models.MetaToken)
        .filter(models.MetaToken.nome == "Token importado do .env")
        .first()
    )
    assert t_importado is not None
    assert "EAAX_token_do_env_legado_9999" not in t_importado.token_cifrado
    assert crypto.decifrar(t_importado.token_cifrado) == "EAAX_token_do_env_legado_9999"
    assert t_importado.ultimos4 == "9999"
    assert t_importado.ativo is True

    # Segunda execução -> não duplica
    assert importar_token_legado(db) is False

    os.environ.pop("META_ACCESS_TOKEN", None)
finally:
    db.close()

# ============================================================================
# Teste 5: token_da_waba / token_do_numero
# ============================================================================
db = SessionLocal()
try:
    waba_k = "waba_k_test_123"

    tok_proprio = models.MetaToken(
        nome="Token Proprio Numero",
        token_cifrado=crypto.cifrar("TOKEN_PROPRIO_NUMERO_AAA"),
        ultimos4="AAAA",
        ativo=True,
    )
    tok_waba = models.MetaToken(
        nome="Token WABA Geral",
        token_cifrado=crypto.cifrar("TOKEN_WABA_GERAL_BBB"),
        ultimos4="BBBB",
        ativo=True,
    )
    db.add_all([tok_proprio, tok_waba])
    db.commit()

    # Número 1 (mais antigo da WABA) com tok_waba
    num1 = models.WhatsappNumber(
        waba_id=waba_k,
        phone_number_id="phone_waba_fallback",
        display_phone_number="+55 11 97777-0001",
        meta_token_id=tok_waba.id,
        active=True,
        created_at=datetime.utcnow() - timedelta(days=10),
    )
    # Número 2 com token próprio
    num2 = models.WhatsappNumber(
        waba_id=waba_k,
        phone_number_id="phone_token_proprio",
        display_phone_number="+55 11 97777-0002",
        meta_token_id=tok_proprio.id,
        active=True,
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    # Número 3 sem token próprio (deve usar token_da_waba como fallback)
    num3 = models.WhatsappNumber(
        waba_id=waba_k,
        phone_number_id="phone_sem_token_proprio",
        display_phone_number="+55 11 97777-0003",
        meta_token_id=None,
        active=True,
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    # Número 4 em WABA sem nenhum token
    waba_vazia = "waba_sem_token_nenhum"
    num4 = models.WhatsappNumber(
        waba_id=waba_vazia,
        phone_number_id="phone_waba_sem_token",
        display_phone_number="+55 11 97777-0004",
        meta_token_id=None,
        active=True,
    )
    db.add_all([num1, num2, num3, num4])
    db.commit()

    # Número com token próprio vence
    assert token_do_numero(db, num2) == "TOKEN_PROPRIO_NUMERO_AAA"

    # Número sem token próprio usa fallback da WABA
    assert token_do_numero(db, num3) == "TOKEN_WABA_GERAL_BBB"

    # token_da_waba retorna o token da WABA
    assert token_da_waba(db, waba_k) == "TOKEN_WABA_GERAL_BBB"

    # Nada configurado: mesmo com META_ACCESS_TOKEN no os.environ, lança MetaTokenConfigError
    os.environ["META_ACCESS_TOKEN"] = "TOKEN_DE_ENV_QUE_NAO_DEVE_SER_USADO"
    err_waba = False
    try:
        token_da_waba(db, waba_vazia)
    except MetaTokenConfigError as exc:
        err_waba = True
        assert f"Nenhum token da Meta cadastrado para a WABA {waba_vazia}: cadastre um em Números" in str(exc)
    assert err_waba, "token_da_waba deveria falhar sem fallback para env"

    err_num = False
    try:
        token_do_numero(db, num4)
    except MetaTokenConfigError as exc:
        err_num = True
        assert f"Nenhum token da Meta cadastrado para a WABA {waba_vazia}: cadastre um em Números" in str(exc)
    assert err_num, "token_do_numero deveria falhar sem fallback para env"

    os.environ.pop("META_ACCESS_TOKEN", None)
finally:
    db.close()

# ============================================================================
# Teste 6: Worker dispatch cycle com token por número e tratamento de erro
# ============================================================================
captured_auth_headers: list[str] = []


def worker_mock_handler(request: httpx.Request) -> httpx.Response:
    captured_auth_headers.append(request.headers.get("authorization", ""))
    return httpx.Response(
        200,
        json={"messages": [{"id": f"wamid.worker.test.{len(captured_auth_headers)}"}]},
    )


MetaClient.default_transport = httpx.MockTransport(worker_mock_handler)

db = SessionLocal()
try:
    # 6.1: Envio com sucesso usando token do número
    tok_worker = models.MetaToken(
        nome="Token Worker Envio",
        token_cifrado=crypto.cifrar("TOKEN_SECRETO_WORKER_XYZ"),
        ultimos4="_XYZ",
        ativo=True,
    )
    db.add(tok_worker)
    db.commit()

    num_worker_ok = models.WhatsappNumber(
        waba_id="waba_worker_ok",
        phone_number_id="phone_worker_ok_id",
        display_phone_number="+55 11 96666-0001",
        meta_token_id=tok_worker.id,
        active=True,
    )
    db.add(num_worker_ok)
    db.commit()

    tpl_worker = models.Template(
        name="tpl_worker_test",
        meta_template_name="tpl_worker_test",
        language="pt_BR",
        category="UTILITY",
        status=models.TemplateStatus.approved,
        waba_id="waba_worker_ok",
        body_text="Olá {{1}}",
    )
    db.add(tpl_worker)
    db.commit()

    faixa_worker_ok = models.Faixa(
        name="Faixa Worker OK",
        template_id=tpl_worker.id,
        active=True,
    )
    db.add(faixa_worker_ok)
    db.commit()

    db.add(models.FaixaNumber(faixa_id=faixa_worker_ok.id, whatsapp_number_id=num_worker_ok.id))
    db.add(
        models.DispatchConfig(
            faixa_id=faixa_worker_ok.id,
            active=True,
            force_run=True,
            batch_size=10,
            interval_seconds=1,
        )
    )
    item_ok = models.QueueItem(
        faixa_id=faixa_worker_ok.id,
        codigo_cliente="00123456",
        nome="Cliente Teste",
        cpf="12345678901",
        celular="5511999992222",
        celular_original="11999992222",
        status=models.QueueStatus.pending,
        variables_json={},
    )
    db.add(item_ok)
    db.commit()

    # Executa o ciclo de envio
    asyncio.run(run_dispatch_cycle())

    db.refresh(item_ok)
    assert item_ok.status == models.QueueStatus.sent, f"Item deveria estar sent, status={item_ok.status}"
    assert item_ok.whatsapp_number_id == num_worker_ok.id
    assert item_ok.whatsapp_message_id is not None
    assert len(captured_auth_headers) == 1
    assert captured_auth_headers[0] == "Bearer TOKEN_SECRETO_WORKER_XYZ", (
        f"Header Authorization incorreto: {captured_auth_headers[0]}"
    )

    # 6.2: Envio com número sem nenhum token -> marca item como error sem quebrar o ciclo
    waba_sem_tok = "waba_sem_token_worker"
    num_sem_tok = models.WhatsappNumber(
        waba_id=waba_sem_tok,
        phone_number_id="phone_worker_no_token",
        display_phone_number="+55 11 96666-0002",
        meta_token_id=None,
        active=True,
    )
    db.add(num_sem_tok)
    db.commit()

    faixa_no_token = models.Faixa(
        name="Faixa Sem Token",
        template_id=tpl_worker.id,
        active=True,
    )
    db.add(faixa_no_token)
    db.commit()

    db.add(models.FaixaNumber(faixa_id=faixa_no_token.id, whatsapp_number_id=num_sem_tok.id))
    db.add(
        models.DispatchConfig(
            faixa_id=faixa_no_token.id,
            active=True,
            force_run=True,
            batch_size=10,
            interval_seconds=1,
        )
    )
    item_no_tok = models.QueueItem(
        faixa_id=faixa_no_token.id,
        codigo_cliente="00123457",
        nome="Cliente Sem Token",
        cpf="98765432100",
        celular="5511999993333",
        celular_original="11999993333",
        status=models.QueueStatus.pending,
        variables_json={},
    )
    db.add(item_no_tok)
    db.commit()

    # O ciclo NÃO deve levantar exceção
    asyncio.run(run_dispatch_cycle())

    db.refresh(item_no_tok)
    assert item_no_tok.status == models.QueueStatus.error, (
        f"Item deveria estar com status error, status={item_no_tok.status}"
    )
    assert "Nenhum token da Meta cadastrado para a WABA" in (item_no_tok.error_message or ""), (
        f"Mensagem de erro incorreta: {item_no_tok.error_message}"
    )

finally:
    db.close()

print("OK")
