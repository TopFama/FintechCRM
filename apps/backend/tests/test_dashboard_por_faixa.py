"""Tabela "Por faixa" do Dashboard (GET /dashboard/summary): clientes cobrados
na mesma base do "Pagaram após cobrança" e as mensagens do período só a esses
clientes (base da Frequência), por faixa de atraso.

Executa com assert simples, sem pytest. Encerra imprimindo 'OK'.
"""

import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_dash"
os.environ["JWT_SECRET"] = "segredo-de-teste-dashboard-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-dashboard"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.main import app
from app.timezone import hoje_br

with TestClient(app):  # sobe o schema e cria o admin
    pass

# Sem `with`: não sobe o worker, que mexeria na fila no meio do teste
client = TestClient(app)
res = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": os.environ["ADMIN_PASSWORD"]})
assert res.status_code == 200, res.text
auth = {"Authorization": f"Bearer {res.json()['access_token']}"}

db = SessionLocal()
fa, fb, campanha = models.Faixa(name="FA"), models.Faixa(name="FB"), models.Faixa(name="CAMPANHA X", tipo="campanha")
db.add_all([fa, fb, campanha])
db.flush()

agora = datetime.utcnow()
S = models.QueueStatus


def item(faixa: models.Faixa, codigo: str, status: models.QueueStatus, faixa_atraso: str | None = None, sent_at=agora):
    return models.QueueItem(
        faixa_id=faixa.id, codigo_cliente=codigo, celular="5511999999999", celular_original="11999999999",
        status=status, sent_at=sent_at if status == S.sent else None, created_at=agora, faixa_atraso=faixa_atraso,
    )


def lead(codigo: str, faixa: str, venc_dias: int = 10, cobrado_em=agora):
    return models.Lead(
        codigo_cliente=codigo, nome="X", cluster="TOP", faixa=faixa, dias_atraso=10,
        vencimento_mais_antigo=hoje_br() - timedelta(days=venc_dias), status="cobrado", cobrado_em=cobrado_em,
    )


db.add_all([
    item(fa, "1", S.sent), item(fa, "1", S.sent),  # cliente 1: duas mensagens hoje
    item(fa, "2", S.sent),
    item(campanha, "2", S.sent, faixa_atraso="FA"),  # campanha conta na faixa de atraso do cliente
    item(fa, "3", S.error),
    item(fa, "9", S.sent),  # cobrado dias atrás: entra no Enviado, fica fora da Frequência
    item(fb, "4", S.sent), item(fb, "5", S.pending),
    item(fa, "1", S.sent, sent_at=agora - timedelta(days=5)),  # fora do período
    lead("1", "FA"), lead("1", "FA", venc_dias=40),  # duas parcelas: um cliente só
    lead("2", "FA"), lead("4", "FB"),
    lead("9", "FA", cobrado_em=agora - timedelta(days=5)),
])
db.commit()

pagaram = [{"codigo_cliente": "1", "faixa": "FA", "valor_pago": Decimal("10")}]
hoje = hoje_br().isoformat()
with patch("app.services.pagamentos_service.clientes_que_pagaram", return_value=pagaram):
    res = client.get(f"/dashboard/summary?de={hoje}&ate={hoje}", headers=auth)
assert res.status_code == 200, res.text
por_faixa = {r["faixa"]: r for r in res.json()["por_faixa"]}
assert set(por_faixa) == {"FA", "FB"}, por_faixa

f = por_faixa["FA"]
assert f["sent"] == 5 and f["error"] == 1, f
assert f["clientes_cobrados"] == 2, f  # clientes 1 e 2
assert f["enviados_cobrados"] == 4, f  # 2 do cliente 1 + 2 do cliente 2 (régua e campanha); o 9 fica fora
assert f["pagaram"] == 1 and f["valor_pago"] == "10.00", f

f = por_faixa["FB"]
assert f["sent"] == 1 and f["pending"] == 1, f
assert f["clientes_cobrados"] == 1 and f["enviados_cobrados"] == 1 and f["pagaram"] == 0, f

db.close()
print("OK")
