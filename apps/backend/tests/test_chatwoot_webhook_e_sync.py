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


    def test_template_create_exige_idioma(self):
        """Valida que a criação de template não presume idioma e exige do usuário."""
        with self.assertRaises(ValidationError):
            TemplateCreate(
                name="teste",
                meta_template_name="teste",
                language="",
                body_text="Olá {{1}}",
            )
        # Com idioma explícito deve validar com sucesso
        tc = TemplateCreate(
            name="teste",
            meta_template_name="teste",
            language="pt_BR",
            body_text="Olá {{1}}",
        )
        self.assertEqual(tc.language, "pt_BR")


if __name__ == "__main__":
    unittest.main()
