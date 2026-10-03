"""Dashboard em tempo real: as triggers do Postgres avisam toda mudança da
fila, dos telefones inválidos e das pausas; o ouvinte soma nos contadores do
Redis e o WebSocket /dashboard/ws manda os números. Depois de cada transição
real (criar, reservar, enviar, erro, parar, descartar, expirar, telefone
inválido, pausar, vários itens no mesmo commit, commit durante a carga) o
contador tem que ser igual à contagem do card/relatório.

Executa com assert simples, sem pytest. Encerra imprimindo 'OK'.
"""

import asyncio
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_painel"
os.environ["JWT_SECRET"] = "segredo-de-teste-painel-1234567890"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-painel"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import cache, consultas_fila, fila_automatica, models, painel_tempo_real, pausas
from app.database import SessionLocal, engine
from app.main import app
from app.timezone import hoje_br

with TestClient(app):  # sobe o schema (com as triggers) e cria o admin
    pass

# Sem `with`: não sobe o worker, que mexeria na fila no meio do teste. O
# ouvinte roda à parte, como o lifespan faria.
threading.Thread(target=asyncio.run, args=(painel_tempo_real.ouvir(),), daemon=True).start()
client = TestClient(app)
res = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": os.environ["ADMIN_PASSWORD"]})
assert res.status_code == 200, res.text
cookie = {"cookie": f"access_token={res.json()['access_token']}"}

r = cache.redis_cliente()
inicio = time.time()
while not r.exists("lock:painel-ouvinte"):
    assert time.time() - inicio < 15, "ouvinte não pegou a trava"
    time.sleep(0.1)

hoje, ontem, anteontem = hoje_br(), hoje_br() - timedelta(days=1), hoje_br() - timedelta(days=2)
S = models.QueueStatus
db = SessionLocal()
faixa = models.Faixa(name="F1")
db.add(faixa)
db.commit()
agora = datetime.utcnow()


def item(status: S, criado=None, codigo="1") -> models.QueueItem:
    return models.QueueItem(
        faixa_id=faixa.id, codigo_cliente=codigo, celular="5511999999999", celular_original="11999999999",
        status=status, created_at=criado or agora, sent_at=agora if status == S.sent else None,
    )


def invalido() -> models.InvalidPhoneRecord:
    return models.InvalidPhoneRecord(faixa_id=faixa.id, codigo_cliente="9", celular_original="1", motivo="x")


def prontos(de, ate) -> dict:
    """O primeiro pedido de um dia só pede a carga ao ouvinte ({}); espera os números."""
    inicio = time.time()
    while not (n := painel_tempo_real.numeros(de, ate)):
        assert time.time() - inicio < 5, "o ouvinte não carregou o dia"
        time.sleep(0.05)
    return n


def conferir(passo: str) -> None:
    """Espera o ouvinte aplicar o aviso e compara cada dia com a contagem do banco."""
    for dia in (anteontem, ontem, hoje):
        esperado = consultas_fila.contar_cards(db, dia, dia)
        inicio = time.time()
        while True:
            guardado = {k: int(v) for k, v in r.hgetall(f"painel:dia:{dia}").items()}
            if guardado == esperado:
                break
            assert time.time() - inicio < 5, f"{passo}: {dia} Redis {guardado} != banco {esperado}"
            time.sleep(0.05)


# Estado inicial, antes de alguém olhar: o primeiro pedido carrega pelo banco
db.add_all([item(S.pending), item(S.reserved, codigo="2"), item(S.error, codigo="3"), invalido()])
velho = item(S.pending, criado=agora - timedelta(days=1), codigo="4")
db.add(velho)
db.commit()
assert painel_tempo_real.numeros(anteontem, hoje) == {}  # pediu a carga
numeros = prontos(anteontem, hoje)
esperado = consultas_fila.contar_cards(db, anteontem, hoje)
assert numeros == {**esperado, "total_pausados": 0}, numeros
assert numeros["total_pendentes"] == 3 and numeros["total_erros"] == 1 and numeros["total_telefones_invalidos"] == 1
conferir("carga inicial")

# Item novo e pendente de ontem enviado hoje: sai de pendentes de ontem, entra em enviados de hoje
db.add(item(S.pending, codigo="5"))
db.commit()
conferir("item novo")
velho.status, velho.sent_at = S.sent, datetime.utcnow()
db.commit()
conferir("envio")
assert int(r.hget(f"painel:dia:{hoje}", "total_enviados")) == 1
assert int(r.hget(f"painel:dia:{ontem}", "total_pendentes")) == 0

# Vários itens no mesmo commit (o ORM manda um UPDATE por item, com o mesmo
# saldo): o Postgres juntaria avisos de texto igual e o card contaria um só
quatro = [item(S.pending, codigo=str(i)) for i in range(60, 64)]
db.add_all(quatro)
db.commit()
conferir("quatro itens")
for i in quatro:
    i.status = S.error
db.commit()
conferir("quatro itens com erro no mesmo commit")

# Commit no meio da carga: transação aberta quando o dia é contado entra uma
# vez só (pelo aviso); o snapshot da carga diz quais avisos já estão contados
r.delete(f"painel:dia:{hoje}")
with engine.connect() as outra:
    outra.execute(
        models.QueueItem.__table__.insert().values(
            id="no-meio", faixa_id=faixa.id, codigo_cliente="70", celular="5511999999999",
            celular_original="11999999999", status="pending", created_at=agora, lojas="",
        )
    )
    assert painel_tempo_real.numeros(hoje, hoje) == {}
    inicio = time.time()
    while not r.exists(f"painel:dia:{hoje}"):
        assert time.time() - inicio < 5, "o ouvinte não carregou o dia"
        time.sleep(0.05)
    outra.commit()
conferir("commit no meio da carga")
assert painel_tempo_real._ja_contada(5, (10, 20, set()))
assert painel_tempo_real._ja_contada(12, (10, 20, {11}))
assert not painel_tempo_real._ja_contada(11, (10, 20, {11}))
assert not painel_tempo_real._ja_contada(20, (10, 20, set()))

# Webhook do Chatwoot: enviado vira erro
velho.status = S.error
db.commit()
conferir("erro do webhook")

# Em massa: parar (cancelled), descartar (delete), expirar (reservado antigo vira erro)
db.add_all([item(S.pending, codigo=str(i)) for i in range(10, 15)])
db.commit()
pausas.parar(db, "cliente", "10", "teste")
conferir("parar")
pendentes = [i.id for i in db.query(models.QueueItem).filter(models.QueueItem.status == S.pending)]
assert fila_automatica.descartar_pendentes(db, pendentes) == len(pendentes)
conferir("descartar")
db.add(item(S.reserved, criado=agora - timedelta(days=2), codigo="20"))  # antes do último fim de janela
db.commit()
config = models.GlobalDispatchConfig(schedule_end="18:30")
fila_automatica.expirar_nao_enviados(db, config, datetime.utcnow())
conferir("expirar")

# Telefone inválido: entra e sai
registro = invalido()
db.add(registro)
db.commit()
conferir("telefone inválido")
db.delete(registro)
db.commit()
conferir("telefone inválido apagado")

# Rollback não conta
db.add(item(S.pending, codigo="30"))
db.flush()
db.rollback()
time.sleep(0.5)
conferir("rollback")

# Pausados: pausa não muda status, mas avisa; a recontagem segue a do card
db.add(item(S.pending, codigo="40"))
db.commit()
assert prontos(hoje, hoje)["total_pausados"] == 0  # fica em cache
pausas.pausar(db, "cliente", "40", "teste", None, "teste")
db.commit()
inicio = time.time()
while prontos(hoje, hoje)["total_pausados"] != 1:  # mudança de pausa renova o cache na hora
    assert time.time() - inicio < 5, "pausados não mudou com a pausa"
    time.sleep(0.05)

# Aviso grande demais para o NOTIFY: recomeça (descarta os dias; as telas pedem de novo)
painel_tempo_real.aplicar('{"recontar": true}')
assert not r.exists(f"painel:dia:{hoje}")
prontos(anteontem, hoje)
conferir("recomeço")

# WebSocket: mesmos números e mudança chega sem pedir de novo
with client.websocket_connect(f"/dashboard/ws?de={hoje}&ate={hoje}", headers=cookie) as ws:
    primeiro = ws.receive_json()
    while not primeiro:
        primeiro = ws.receive_json()
    assert primeiro == prontos(hoje, hoje), primeiro
    db.add(item(S.error, codigo="50"))
    db.commit()
    novo = ws.receive_json()
    while not novo:  # {} = manter a conexão viva
        novo = ws.receive_json()
    assert novo["total_erros"] == primeiro["total_erros"] + 1, novo


def fechamento(caminho: str, headers: dict) -> int:
    try:
        with client.websocket_connect(caminho, headers=headers) as ws:
            ws.receive_json()
    except WebSocketDisconnect as exc:
        return exc.code
    raise AssertionError("o WebSocket devia ter fechado")


assert fechamento(f"/dashboard/ws?de={hoje}&ate={hoje}", {}) == 4401
assert fechamento(f"/dashboard/ws?de={hoje}&ate={hoje}", {**cookie, "origin": "https://outro.com"}) == 1008
antigo = hoje - timedelta(days=painel_tempo_real.DIAS_GUARDADOS)
assert fechamento(f"/dashboard/ws?de={antigo}&ate={hoje}", cookie) == 4000

db.close()
print("OK")
