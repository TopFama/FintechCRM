"""Gráfico do card Orçamento do Dashboard (GET /dashboard/orcamento-progressao):
a linha de realizado vai só até hoje (GMT-3). Dia que ainda não aconteceu fica
no eixo com gasto_acumulado_brl nulo, e o total realizado não muda.

Executa com assert simples, sem pytest. Encerra imprimindo 'OK'.
"""

import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_orcamento"
os.environ["JWT_SECRET"] = "segredo-de-teste-orcamento-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-orcamento"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.routers import dashboard
from app.services.custo_whatsapp import CustoWhatsapp

with TestClient(app):  # sobe o schema
    pass

HOJE = date(2026, 10, 4)


def orcamento(inicio: date, fim: date):
    # R$ 1,00 por dia em todo o período, inclusive "dias futuros" (não podem entrar)
    por_dia = {inicio + timedelta(days=i): Decimal("1.00") for i in range((fim - inicio).days + 1)}
    with (
        patch.object(dashboard, "hoje_br", lambda: HOJE),
        patch.object(dashboard.custo_whatsapp, "custo_detalhado", lambda db, i, f: CustoWhatsapp(por_dia)),
    ):
        db = SessionLocal()
        try:
            return dashboard._orcamento(db, inicio, fim)
        finally:
            db.close()


# Mês corrente: valor até hoje, nulo depois; eixo continua com o mês inteiro
o = orcamento(date(2026, 10, 1), date(2026, 10, 31))
assert len(o.dias) == 31
assert [d.gasto_acumulado_brl for d in o.dias[:4]] == [Decimal("1.00"), Decimal("2.00"), Decimal("3.00"), Decimal("4.00")]
assert all(d.gasto_acumulado_brl is None for d in o.dias[4:]), o.dias[4:]
assert o.valor_gasto_brl == Decimal("4.00")

# Mês passado: todos os dias com valor
o = orcamento(date(2026, 9, 1), date(2026, 9, 30))
assert all(d.gasto_acumulado_brl is not None for d in o.dias)
assert o.valor_gasto_brl == Decimal("30.00")

# Período que ainda não começou (personalizado): nenhum valor, total zero
o = orcamento(date(2026, 11, 1), date(2026, 11, 5))
assert len(o.dias) == 5 and all(d.gasto_acumulado_brl is None for d in o.dias)
assert o.valor_gasto_brl == Decimal("0.00")

print("OK")
