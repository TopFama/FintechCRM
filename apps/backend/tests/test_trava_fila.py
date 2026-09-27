"""Duas rotinas colocando clientes na fila ao mesmo tempo ("Buscar agora" do
remarketing e a rotina diária do worker) não podem pôr o mesmo cliente duas
vezes. `clientes_bloqueados_hoje` trava a entrada na fila até o commit: a
segunda rotina espera a primeira gravar e já enxerga o cliente como bloqueado.

Executa com assert simples, sem pytest. Encerra imprimindo 'OK'.
"""

import os
import tempfile
import threading

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_trava"
os.environ["JWT_SECRET"] = "segredo-de-teste-trava-fila-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-trava"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal
from app.elegibilidade import clientes_bloqueados_hoje
from app.main import app

CODIGO = "00000777"

with TestClient(app):  # sobe o schema
    pass

db_a = SessionLocal()
db_b = SessionLocal()
faixa = db_a.query(models.Faixa).first()
if faixa is None:
    faixa = models.Faixa(name="TESTE TRAVA")
    db_a.add(faixa)
    db_a.commit()
db_a.query(models.QueueItem).filter(models.QueueItem.codigo_cliente == CODIGO).delete()
db_a.commit()

# Rotina A lê a fila (e pega a trava), mas ainda não gravou.
assert CODIGO not in clientes_bloqueados_hoje(db_a)

# Rotina B tenta ler ao mesmo tempo: tem que esperar A terminar.
resultado_b: dict[str, set[str]] = {}
b = threading.Thread(target=lambda: resultado_b.update(bloqueados=clientes_bloqueados_hoje(db_b)))
b.start()
b.join(timeout=1.0)
assert b.is_alive(), "a segunda rotina leu a fila sem esperar a primeira gravar"

# A coloca o cliente na fila e dá commit: solta a trava.
db_a.add(
    models.QueueItem(
        faixa_id=faixa.id,
        codigo_cliente=CODIGO,
        celular="5511999990777",
        celular_original="11999990777",
    )
)
db_a.commit()
b.join(timeout=10)
assert not b.is_alive(), "a segunda rotina continuou travada depois do commit"
assert CODIGO in resultado_b["bloqueados"], "a segunda rotina não viu o cliente que a primeira pôs na fila"
db_b.rollback()

# Limpa.
db_a.query(models.QueueItem).filter(models.QueueItem.codigo_cliente == CODIGO).delete()
db_a.commit()
db_a.close()
db_b.close()
print("OK")
