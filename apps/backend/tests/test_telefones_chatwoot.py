"""Retentativas 131026 com Postgres real e integrações simuladas."""
import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/test_telefones_chatwoot"
os.environ["JWT_SECRET"] = "segredo-local-teste-telefones-chatwoot"
os.environ["ADMIN_PASSWORD"] = "senha-local-teste"
from cryptography.fernet import Fernet
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from alembic import command
from alembic.config import Config
from app import models, telefones_invalidos as fluxo, chatwoot_client
from app.database import SessionLocal
from app.routers.reports import list_invalid_phones, export_invalid_phones

cfg = Config("alembic.ini")
command.upgrade(cfg, "head")
command.downgrade(cfg, "base")
command.upgrade(cfg, "head")
command.check(cfg)

db = SessionLocal()
faixa = models.Faixa(name="Teste telefones")
db.add(faixa)
db.flush()

def item(codigo, **campos):
    obj = models.QueueItem(
        faixa_id=faixa.id, codigo_cliente=codigo, cpf="123.456.789-01",
        nome="Ana", celular="5511999990001", celular_original="11999990001",
        status=models.QueueStatus.error, error_message="Chatwoot: 131026: Message undeliverable",
        **campos,
    )
    db.add(obj)
    db.commit()
    return obj

cadastro = {"telefone2": "11999990001", "telefone1": "11999990001",
            "telefone3": "1133334444", "telefone4": "11999990002"}
q = item("00000001", created_at=datetime.utcnow() - timedelta(days=3))
identificador = q.id
with patch.object(fluxo.seta_client, "telefones_por_codigo", return_value={q.codigo_cliente: cadastro}):
    assert fluxo.reprocessar_erros_chatwoot(db) == 1
    assert q.id == identificador and q.status == models.QueueStatus.pending
    assert q.celular == "5511999990002"
    assert q.created_at > datetime.utcnow() - timedelta(minutes=1)
    assert q.telefones_tentados == ["5511999990001"]
    assert db.query(models.InvalidPhoneRecord).count() == 0
    assert db.query(models.ErrorLog).count() == 0
    assert fluxo.reprocessar_erros_chatwoot(db) == 0
    fluxo.registrar_falha(db, q, "131026: Message undeliverable")
    db.commit()
    fluxo.reprocessar_erros_chatwoot(db)
    assert q.status == models.QueueStatus.invalid_phone
    assert db.query(models.InvalidPhoneRecord).count() == 1
    assert fluxo.reprocessar_erros_chatwoot(db) == 0
    assert db.query(models.QueueItem).count() == 1

# Outro envio já bem-sucedido impede recuperar uma falha histórica.
q2 = item("00000002")
outro = item("00000002")
outro.status, outro.sent_at, outro.error_message = models.QueueStatus.sent, datetime.utcnow(), None
db.commit()
with patch.object(fluxo.seta_client, "telefones_por_codigo", return_value={q2.codigo_cliente: cadastro}):
    fluxo.reprocessar_erros_chatwoot(db)
assert q2.status != models.QueueStatus.pending

# Uma indisponibilidade do SETA não perde a tentativa.
q3 = item("00000003")
with patch.object(fluxo.seta_client, "telefones_por_codigo", side_effect=fluxo.seta_client.SetaIndisponivel):
    try:
        fluxo.reprocessar_erros_chatwoot(db)
        raise AssertionError("deveria adiar")
    except fluxo.seta_client.SetaIndisponivel:
        db.rollback()
assert q3.status == models.QueueStatus.error
assert fluxo.detalhe_telefone_invalido({"content": "CPF 131026", "id": 131026}) is None
assert fluxo.detalhe_telefone_invalido({"content_attributes": {"external_error": "131026: Message undeliverable"}})
assert fluxo.detalhe_telefone_invalido("9913102699") is None

# Paginação e ID exato; não atribui falha de outra mensagem ao cliente.
class Cliente(chatwoot_client.ChatwootClient):
    async def _request(self, method, path, **kwargs):
        if kwargs["params"].get("before") == 20:
            return {"payload": [{"id": 10, "status": "delivered"}]}
        return {"payload": [{"id": 20, "content_attributes": {"external_error": "131026"}}]}
res = asyncio.run(Cliente("https://teste", "1", "teste").obter_mensagem(2, 10))
assert res["id"] == 10 and res["status"] == "delivered"

pagina = list_invalid_phones(faixa_id=None, campanha=None, de=None, ate=None,
                            limit=50, offset=0, sort_by="cpf", sort_dir="asc", db=db, _user=None)
assert pagina.itens[0].cpf == "123.456.789-01"
import io
import openpyxl
arquivo = export_invalid_phones(faixa_id=None, campanha=None, de=None, ate=None, db=db, _user=None)
ws = openpyxl.load_workbook(io.BytesIO(arquivo.body)).active
assert ws.cell(1, 2).value == "CPF"
db.close()
print("OK")
