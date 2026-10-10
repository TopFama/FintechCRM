"""Valida a tradução de erros para português, o endpoint de webhook do Chatwoot
e a sincronização de templates sem presumir idioma."""

import hashlib
import hmac
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# Adiciona o diretório do backend ao sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tempfile

# Configura ambiente antes de importar a app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET"] = "segredo-de-teste-muito-seguro-12345"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-12345"
os.environ["ENCRYPTION_KEY"] = "ZXhlbXBsb19jaGF2ZV9mZXJuZXRfMzJfYnl0ZXNfX18="
os.environ["CHATWOOT_WEBHOOK_SECRET"] = "segredo-webhook-teste"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.schemas import TemplateCreate
from app.utils.erros import descrever_erro_envio
from pydantic import ValidationError

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
from app.routers import chatwoot
chatwoot.SessionLocal = TestSession


class TestChatwootWebhookESync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)
        cls.client = TestClient(app)

    def setUp(self):
        self.db = TestSession()

    def tearDown(self):
        self.db.close()

    def test_descrever_erro_envio_meta(self):
        """Verifica a tradução de erros da Meta/WhatsApp para português."""
        erro_132001 = "(#132001) Template name does not exist in the translation"
        desc = descrever_erro_envio(erro_132001)
        self.assertIn("Template ou idioma não encontrado na Meta", desc)
        self.assertIn("132001", desc)

        erro_undeliverable = "131026: Message undeliverable"
        desc = descrever_erro_envio(erro_undeliverable)
        self.assertIn("Mensagem não pôde ser entregue pelo WhatsApp", desc)

        erro_24h = "131047: More than 24 hours have passed"
        desc = descrever_erro_envio(erro_24h)
        self.assertIn("Janela de conversação de 24 horas expirada", desc)

        erro_params = "132000: Number of parameters does not match"
        desc = descrever_erro_envio(erro_params)
        self.assertIn("Quantidade de variáveis diverge", desc)

        erro_desconhecido = "Erro customizado 9999"
        desc = descrever_erro_envio(erro_desconhecido)
        self.assertIn("Falha no envio", desc)
        self.assertIn("Erro customizado 9999", desc)

    def test_webhook_chatwoot_processa_erro(self):
        """Valida que o webhook processa falhas, atualiza a fila e reverte o lead."""
        faixa = models.Faixa(id="faixa-teste-wh", name="Faixa WH", tipo=models.TIPO_REGUA)
        self.db.add(faixa)

        item = models.QueueItem(
            id="item-teste-wh",
            faixa_id="faixa-teste-wh",
            codigo_cliente="00112233",
            nome="Cliente Teste",
            celular="5511999998888",
            celular_original="11999998888",
            status=models.QueueStatus.sent,
            sent_at=datetime.utcnow(),
            whatsapp_message_id="998877",
        )
        self.db.add(item)

        lead = models.Lead(
            id="lead-teste-wh",
            faixa="Faixa WH",
            campanha_id="",
            codigo_cliente="00112233",
            nome="Cliente Teste",
            celular="5511999998888",
            cluster="ESPECIAL",
            dias_atraso=15,
            vencimento_mais_antigo=datetime.utcnow().date(),
            status="cobrado",
            cobrado_em=item.sent_at,
        )
        self.db.add(lead)
        self.db.commit()

        # Monta payload de webhook de erro do Chatwoot
        payload = {
            "event": "message_updated",
            "id": 998877,
            "status": "failed",
            "content_attributes": {
                "external_error": "(#132001) Template name does not exist in the translation"
            },
        }
        raw_bytes = str(payload).replace("'", '"').encode("utf-8")
        timestamp = str(int(datetime.utcnow().timestamp()))
        sig = "sha256=" + hmac.new(
            b"segredo-webhook-teste",
            f"{timestamp}.{raw_bytes.decode('utf-8')}".encode(),
            hashlib.sha256,
        ).hexdigest()

        response = self.client.post(
            "/chatwoot/webhook",
            content=raw_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Chatwoot-Signature": sig,
                "X-Chatwoot-Timestamp": timestamp,
            },
        )
        self.assertEqual(response.status_code, 200)
        dados = response.json()
        self.assertEqual(dados["action"], "marked_error")

        # Confere atualização no banco
        self.db.refresh(item)
        self.assertEqual(item.status, models.QueueStatus.error)
        self.assertIsNone(item.sent_at)
        self.assertIn("Template ou idioma não encontrado na Meta", item.error_message)

        # Confere lead revertido para 'novo'
        self.db.refresh(lead)
        self.assertEqual(lead.status, "novo")
        self.assertIsNone(lead.cobrado_em)

        # Confere ErrorLog gerado
        log = self.db.query(models.ErrorLog).filter(models.ErrorLog.queue_item_id == item.id).first()
        self.assertIsNotNone(log)
        self.assertIn("Template ou idioma não encontrado na Meta", log.message)

    def test_webhook_assinatura_invalida(self):
        """Webhook com assinatura inválida deve retornar 401."""
        response = self.client.post(
            "/chatwoot/webhook",
            json={"event": "message_updated", "id": 123},
            headers={
                "X-Chatwoot-Signature": "sha256=invalida",
                "X-Chatwoot-Timestamp": "123456",
            },
        )
        self.assertEqual(response.status_code, 401)


    def _headers_webhook(self, payload: dict) -> dict:
        import json
        raw_bytes = json.dumps(payload).encode("utf-8")
        timestamp = str(int(datetime.utcnow().timestamp()))
        sig = "sha256=" + hmac.new(
            b"segredo-webhook-teste",
            f"{timestamp}.{raw_bytes.decode('utf-8')}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Chatwoot-Signature": sig,
            "X-Chatwoot-Timestamp": timestamp,
        }

    def test_webhook_eventos_e_validacoes(self):
        """Valida tratamento de eventos não suportados, missing_id, invalid_id e status não falho."""
        p1 = {"event": "conversation_created", "id": 123}
        resp = self.client.post("/chatwoot/webhook", json=p1, headers=self._headers_webhook(p1))
        self.assertEqual(resp.json(), {"status": "ok", "action": "ignored_event"})

        p2 = {"event": "message_created"}
        resp = self.client.post("/chatwoot/webhook", json=p2, headers=self._headers_webhook(p2))
        self.assertEqual(resp.json(), {"status": "ok", "action": "missing_id"})

        p3 = {"event": "message_created", "id": "nao_numerico"}
        resp = self.client.post("/chatwoot/webhook", json=p3, headers=self._headers_webhook(p3))
        self.assertEqual(resp.json(), {"status": "ok", "action": "invalid_id"})

        for st in ("delivered", "read", 1, 2):
            p4 = {"event": "message_updated", "id": 555, "status": st}
            resp = self.client.post("/chatwoot/webhook", json=p4, headers=self._headers_webhook(p4))
            self.assertEqual(resp.json(), {"status": "ok", "action": "status_not_failed"})

    def test_webhook_item_nao_encontrado(self):
        """Webhook com mensagem falha de id inexistente na fila retorna item_not_found."""
        payload = {
            "event": "message_updated",
            "id": 888111222,
            "status": "failed",
            "content_attributes": {"external_error": "Erro"},
        }
        resp = self.client.post("/chatwoot/webhook", json=payload, headers=self._headers_webhook(payload))
        self.assertEqual(resp.json(), {"status": "ok", "action": "item_not_found"})

    def test_webhook_erro_131026_telefone_invalido(self):
        """Valida que o webhook identifica erro 131026 e registra falha de telefone inválido."""
        faixa = models.Faixa(id="faixa-wh-131026", name="Faixa 131026", tipo=models.TIPO_REGUA)
        self.db.add(faixa)
        item = models.QueueItem(
            id="item-wh-131026",
            faixa_id="faixa-wh-131026",
            codigo_cliente="00998877",
            nome="Cliente 131026",
            celular="5511999990001",
            celular_original="11999990001",
            status=models.QueueStatus.sent,
            sent_at=datetime.utcnow(),
            whatsapp_message_id="776655",
        )
        self.db.add(item)
        lead = models.Lead(
            id="lead-wh-131026",
            faixa="Faixa 131026",
            campanha_id="",
            codigo_cliente="00998877",
            nome="Cliente 131026",
            celular="5511999990001",
            cluster="ESPECIAL",
            dias_atraso=20,
            vencimento_mais_antigo=datetime.utcnow().date(),
            status="cobrado",
            cobrado_em=item.sent_at,
        )
        self.db.add(lead)
        self.db.commit()

        payload = {
            "event": "message_updated",
            "id": 776655,
            "status": "failed",
            "content_attributes": {"external_error": "131026: Message undeliverable"},
        }
        resp = self.client.post("/chatwoot/webhook", json=payload, headers=self._headers_webhook(payload))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "marked_error")

        self.db.refresh(item)
        self.assertEqual(item.status, models.QueueStatus.error)
        self.assertIn("131026", item.error_message)
        self.db.refresh(lead)
        self.assertEqual(lead.status, "novo")
        self.assertIsNone(lead.cobrado_em)

    def test_processar_webhook_chatwoot_direto_e_rollback(self):
        """Valida que a função _processar_webhook_chatwoot pode ser chamada diretamente
        e executa rollback seguro ao ocorrer erro."""
        from app.routers.chatwoot import _processar_webhook_chatwoot

        payload = {
            "id": 999999,
            "status": "failed",
            "content_attributes": {"external_error": "Erro teste"},
        }
        res = _processar_webhook_chatwoot(payload)
        self.assertEqual(res, {"status": "ok", "action": "item_not_found"})

        with patch.object(chatwoot, "desmarcar_lead_cobrado", side_effect=RuntimeError("Falha de banco forçada")):
            item = models.QueueItem(
                id="item-wh-rollback",
                faixa_id="faixa-teste-wh",
                codigo_cliente="001199",
                nome="Rollback Teste",
                celular="5511999990002",
                celular_original="11999990002",
                status=models.QueueStatus.sent,
                sent_at=datetime.utcnow(),
                whatsapp_message_id="999999",
            )
            self.db.add(item)
            self.db.commit()

            with self.assertRaises(RuntimeError):
                _processar_webhook_chatwoot(payload)

            self.db.refresh(item)
            self.assertEqual(item.status, models.QueueStatus.sent)

    def test_webhook_delega_para_thread(self):
        """Verifica que o webhook delega o processamento de banco através de asyncio.to_thread."""
        payload = {
            "event": "message_updated",
            "id": 123456,
            "status": "failed",
            "content_attributes": {"external_error": "Erro"},
        }
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = {"status": "ok", "action": "marked_error"}
            resp = self.client.post("/chatwoot/webhook", json=payload, headers=self._headers_webhook(payload))
            self.assertEqual(resp.status_code, 200)
            mock_to_thread.assert_awaited_once()
            args = mock_to_thread.call_args[0]
            self.assertEqual(args[0], chatwoot._processar_webhook_chatwoot)
            self.assertEqual(args[1]["id"], 123456)

    def test_sincronizar_retornos_chatwoot_comita_antes_do_proximo_await(self):
        """Teste de regressão (Seção 13): garante que cada item processado pelo
        sincronizador é comitado no banco ANTES da chamada await client.obter_mensagem
        do próximo item, impedindo transações abertas e locks cruzados."""
        import asyncio
        from app import telefones_invalidos as ti

        conf = self.db.query(models.ConfiguracaoChatwoot).first()
        if not conf:
            conf = models.ConfiguracaoChatwoot(
                base_url="https://chatwoot.teste",
                account_id="1",
                api_access_token_cifrado="cifrado",
            )
            self.db.add(conf)
            self.db.commit()

        faixa = models.Faixa(id="faixa-sync-test", name="Faixa Sync", tipo=models.TIPO_REGUA)
        self.db.add(faixa)

        item1 = models.QueueItem(
            id="item-sync-01",
            faixa_id="faixa-sync-test",
            codigo_cliente="000101",
            celular="5511999990101",
            celular_original="11999990101",
            status=models.QueueStatus.sent,
            sent_at=datetime.utcnow(),
            whatsapp_message_id="chatwoot:1:101",
        )
        lead1 = models.Lead(
            id="lead-sync-01",
            faixa="Faixa Sync",
            campanha_id="",
            codigo_cliente="000101",
            nome="Cliente 101",
            celular="5511999990101",
            cluster="ESPECIAL",
            dias_atraso=10,
            vencimento_mais_antigo=datetime.utcnow().date(),
            status="cobrado",
            cobrado_em=item1.sent_at,
        )
        item2 = models.QueueItem(
            id="item-sync-02",
            faixa_id="faixa-sync-test",
            codigo_cliente="000102",
            celular="5511999990102",
            celular_original="11999990102",
            status=models.QueueStatus.sent,
            sent_at=datetime.utcnow(),
            whatsapp_message_id="chatwoot:1:102",
        )
        lead2 = models.Lead(
            id="lead-sync-02",
            faixa="Faixa Sync",
            campanha_id="",
            codigo_cliente="000102",
            nome="Cliente 102",
            celular="5511999990102",
            cluster="ESPECIAL",
            dias_atraso=10,
            vencimento_mais_antigo=datetime.utcnow().date(),
            status="cobrado",
            cobrado_em=item2.sent_at,
        )
        self.db.add_all([item1, lead1, item2, lead2])
        self.db.commit()

        estado_durante_segundo_await = {}

        class FakeClient:
            async def obter_mensagem(self, conversation_id: int, message_id: int):
                if message_id == 101:
                    return {"content_attributes": {"external_error": "131026: Message undeliverable"}}
                if message_id == 102:
                    db_check = TestSession()
                    try:
                        i1 = db_check.get(models.QueueItem, "item-sync-01")
                        l1 = db_check.get(models.Lead, "lead-sync-01")
                        estado_durante_segundo_await["item1_status"] = i1.status
                        estado_durante_segundo_await["lead1_status"] = l1.status
                    finally:
                        db_check.close()
                    return {"status": "delivered"}
                return None

        ti._proxima_sincronizacao = datetime.min
        ti._ultimo_id = ""

        with patch.object(ti.chatwoot_client, "is_configured", return_value=True), \
             patch.object(ti.chatwoot_client, "cliente_configurado", return_value=FakeClient()):
            alterados = asyncio.run(ti.sincronizar_retornos_chatwoot(self.db))

        self.assertEqual(alterados, 2)
        self.assertEqual(estado_durante_segundo_await.get("item1_status"), models.QueueStatus.error)
        self.assertEqual(estado_durante_segundo_await.get("lead1_status"), "novo")


    def test_template_create_idioma_fixo(self):
        """O cadastro não recebe idioma: todo template criado na plataforma é pt_BR."""
        tc = TemplateCreate(
            name="teste",
            meta_template_name="teste",
            language="en_US",
            body_text="Olá {{1}}, tudo bem?",
            variables=[{"position": 1, "internal_name": "variavel_1"}],
        )
        self.assertFalse(hasattr(tc, "language"))
        # Rascunho aceita incompleto, mas não sem nome interno
        with self.assertRaises(ValidationError):
            TemplateCreate(name=" ", meta_template_name="teste", body_text="Olá.")


if __name__ == "__main__":
    unittest.main()
