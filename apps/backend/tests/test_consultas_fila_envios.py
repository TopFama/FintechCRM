"""Envios da fila por período (consultas_fila): clientes cobrados = clientes
distintos com mensagem enviada no período, por faixa de atraso (base do card
Mensagens por faixa e do "Pagaram após cobrança"), envios por dia e faixa (base do
custo por envio do ROAS da Efetividade) e os cards do Dashboard (GET /dashboard/summary).

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

from app import consultas_fila, models
from app.database import SessionLocal
from app.main import app
from app.services import custo_whatsapp
from app.timezone import hoje_br, inicio_do_dia_utc

with TestClient(app):  # sobe o schema e cria o admin
    pass

# Sem `with`: não sobe o worker, que mexeria na fila no meio do teste
client = TestClient(app)
res = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": os.environ["ADMIN_PASSWORD"]})
assert res.status_code == 200, res.text
auth = {"Authorization": f"Bearer {res.json()['access_token']}"}

db = SessionLocal()
fa, fb, campanha = models.Faixa(name="FA"), models.Faixa(name="FB"), models.Faixa(name="CAMPANHA X", tipo="campanha")
fr = models.Faixa(name="FR")  # reenvio a cliente cobrado ontem
fh = models.Faixa(name="FH")  # limite de horário do dia
db.add_all([fa, fb, campanha, fr, fh])
db.flush()

agora = datetime.utcnow()
hoje = hoje_br()
ontem = agora - timedelta(days=1)
dia_h = hoje - timedelta(days=10)
S = models.QueueStatus


def item(faixa: models.Faixa, codigo: str, status: models.QueueStatus, faixa_atraso: str | None = None, sent_at=agora,
         valor: str | None = None):
    return models.QueueItem(
        faixa_id=faixa.id, codigo_cliente=codigo, celular="5511999999999", celular_original="11999999999",
        status=status, sent_at=sent_at if status == S.sent else None, created_at=agora, faixa_atraso=faixa_atraso,
        valor=valor,
    )


db.add_all([
    item(fa, "1", S.sent), item(fa, "1", S.sent),  # cliente 1: duas mensagens hoje
    item(fa, "2", S.sent),
    item(campanha, "2", S.sent, faixa_atraso="FA"),  # campanha conta na faixa de atraso do cliente
    item(campanha, "6", S.sent, faixa_atraso="FA"),  # só pela campanha: cobrado em FA
    item(fa, "3", S.error), item(fa, "10", S.invalid_phone),  # sem mensagem enviada: fora
    item(fa, "9", S.sent),
    item(fb, "4", S.sent), item(fb, "5", S.pending),
    item(fb, "1", S.sent),  # cliente 1 também em FB: um em cada faixa
    item(fa, "1", S.sent, sent_at=agora - timedelta(days=5)),  # fora do período
    item(fr, "R", S.sent, sent_at=ontem), item(fr, "R", S.sent, valor="1.500,00"),
    # 23:59 e 00:01 de Brasília em volta da virada de dia_h
    item(fh, "H1", S.sent, sent_at=inicio_do_dia_utc(dia_h + timedelta(days=1)) - timedelta(minutes=1)),
    item(fh, "H2", S.sent, sent_at=inicio_do_dia_utc(dia_h + timedelta(days=1)) + timedelta(minutes=1)),
])
db.commit()


def cobrados(de, ate):
    return {faixa: set(clientes) for faixa, clientes in consultas_fila.clientes_com_envio_no_periodo(db, de, ate).items()}


# Clientes cobrados = clientes distintos com mensagem enviada no período, por faixa de atraso
hoje_cobrados = cobrados(hoje, hoje)
assert hoje_cobrados["FA"] == {"1", "2", "6", "9"}, hoje_cobrados  # o 3 e o 10 (sem envio) ficam fora
assert hoje_cobrados["FB"] == {"4", "1"} and hoje_cobrados["FR"] == {"R"}, hoje_cobrados
assert consultas_fila.clientes_com_envio_no_periodo(db, hoje, hoje)["FA"]["1"].mensagens == 2  # cliente 1: duas mensagens

# Ontem e hoje: o cliente R recebeu duas mensagens e é um cliente
dia_ontem = hoje - timedelta(days=1)
assert consultas_fila.clientes_com_envio_no_periodo(db, dia_ontem, hoje)["FR"]["R"].mensagens == 2

# Rateio do custo da Meta: custo do dia ÷ mensagens enviadas no dia (todas as faixas);
# dia sem envio fica de fora
assert consultas_fila.envios_por_dia(db, dia_h, dia_h) == {(dia_h, "FH"): 1}  # 23:59 de Brasília conta no dia
assert consultas_fila.envios_por_dia(db, hoje, hoje)[(hoje, "FA")] == 6
dia_sem_envio = hoje - timedelta(days=3)
with patch.object(custo_whatsapp, "gasto_diario_brl", return_value=({hoje: Decimal("1.80"), dia_sem_envio: Decimal("5")}, None)):
    por_envio, _motivo = custo_whatsapp.custo_por_envio(db, dia_sem_envio, hoje)
assert por_envio == {hoje: Decimal("0.20"), dia_ontem: Decimal("0")}, por_envio  # hoje: 9 envios
with patch.object(custo_whatsapp, "gasto_diario_brl", return_value=(None, "Meta fora")):
    assert custo_whatsapp.custo_por_envio(db, hoje, hoje) == (None, "Meta fora")

# Limite do dia em Brasília: 23:59 conta, 00:01 do dia seguinte não
assert cobrados(dia_h, dia_h) == {"FH": {"H1"}}

# Cards do Dashboard no período
res = client.get(f"/dashboard/summary?de={hoje.isoformat()}&ate={hoje.isoformat()}", headers=auth)
assert res.status_code == 200, res.text
dados = res.json()
assert dados["total_enviados"] == 9 and dados["total_erros"] == 1 and dados["total_pendentes"] == 1, dados
assert "por_faixa" not in dados and "total_por_faixa" not in dados, dados

print("OK")
