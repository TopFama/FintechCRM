"""Tabela "Por faixa" do Dashboard (GET /dashboard/summary): clientes cobrados
na mesma base do "Pagaram após cobrança" e, só entre eles, as mensagens do
período e quantos receberam alguma (base da Frequência), por faixa de atraso.

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
fc = models.Faixa(name="FC")  # só lead marcado como cobrado à mão, sem fila
db.add_all([fa, fb, campanha, fc])
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
    lead("7", "FA"),  # marcado como cobrado à mão: sem mensagem
    lead("9", "FA", cobrado_em=agora - timedelta(days=5)),
    lead("8", "FC"),
])
db.commit()

pagaram = [
    {"codigo_cliente": "1", "faixa": "FA", "valor_pago": Decimal("10")},
    # mesmo cliente cobrado de novo noutro dia: a linha traz o mesmo pagamento
    {"codigo_cliente": "1", "faixa": "FA", "valor_pago": Decimal("10")},
    # cobrado em duas faixas no mesmo dia: conta nas duas linhas, uma vez no total
    {"codigo_cliente": "4", "faixa": "FA, FB", "valor_pago": Decimal("25")},
]
hoje = hoje_br().isoformat()
with patch("app.services.pagamentos_service.clientes_que_pagaram", return_value=pagaram):
    res = client.get(f"/dashboard/summary?de={hoje}&ate={hoje}", headers=auth)
assert res.status_code == 200, res.text
por_faixa = {r["faixa"]: r for r in res.json()["por_faixa"]}
assert set(por_faixa) == {"FA", "FB", "FC"}, por_faixa

f = por_faixa["FA"]
assert f["sent"] == 5 and f["error"] == 1, f
assert f["clientes_cobrados"] == 3, f  # clientes 1, 2 e 7
assert f["enviados_cobrados"] == 4, f  # 2 do cliente 1 + 2 do cliente 2 (régua e campanha); o 9 fica fora
assert f["clientes_com_envio"] == 2, f  # o 7 não recebeu mensagem: fica fora da Frequência
assert f["pagaram"] == 2 and f["valor_pago"] == "35.00", f

f = por_faixa["FB"]
assert f["sent"] == 1 and f["pending"] == 1, f
assert f["clientes_cobrados"] == 1 and f["enviados_cobrados"] == 1 and f["clientes_com_envio"] == 1, f
assert f["pagaram"] == 1 and f["valor_pago"] == "25.00", f

# Total: cada cliente e cada pagamento uma vez (cliente 4 está em FA e FB)
total = res.json()["total_por_faixa"]
assert total == {
    "clientes_cobrados": 5,  # 1, 2, 7 (FA), 4 (FB), 8 (FC)
    "enviados_cobrados": 5,
    "clientes_com_envio": 3,  # 1, 2 e 4
    "pagaram": 2,  # 1 e 4
    "valor_pago": "35.00",
}, total

# Faixa sem fila no período, só com cliente cobrado: aparece com os cobrados
f = por_faixa["FC"]
assert f["faixa_id"] == fc.id and f["sent"] == 0 and f["pending"] == 0, f
assert f["clientes_cobrados"] == 1 and f["enviados_cobrados"] == 0 and f["clientes_com_envio"] == 0, f

db.close()
print("OK")
