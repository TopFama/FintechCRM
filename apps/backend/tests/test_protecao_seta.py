"""Proteção do SETA contra consultas simultâneas ou repetidas (app/cache.py,
seta_client.consulta_pesada, relatórios em cache).

Redis de verdade (a trava usa script Lua) e Postgres de verdade; o SETA é um
motor falso que dorme em cada consulta e anota quantas vezes foi consultado
e quantas consultas pesadas rodaram ao mesmo tempo. Os asserts contam
chamadas ao SETA, não só o status HTTP. Executa com asserts simples, sem
pytest, e encerra imprimindo 'OK'.
"""

import json
import os
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_protecao"
os.environ["JWT_SECRET"] = "segredo-de-teste-protecao-seta-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-protecao-seta"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import redis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app import cache, models, seta_client
from app.database import SessionLocal
from app.main import app
from app.routers import dashboard
from app.services import pagamentos_seta
from app.timezone import hoje_br

with TestClient(app):  # sobe o schema e cria o admin
    pass

# Sem `with`: não sobe o worker, que mexeria no SETA no meio do teste
client = TestClient(app)
res = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": os.environ["ADMIN_PASSWORD"]})
assert res.status_code == 200, res.text
auth = {"Authorization": f"Bearer {res.json()['access_token']}"}

# --- SETA falso ------------------------------------------------------------------

DEMORA = 0.4  # segundos por consulta ao SETA
chamadas: Counter = Counter()  # consultas pesadas, por tipo
execucoes = Counter()  # execute() no motor falso
simultaneas = {"agora": 0, "maximo": 0}
_trava_contagem = threading.Lock()
motor_falho = {"ligado": False}


class ResultadoFalso:
    def mappings(self):
        return self

    def all(self):
        return []

    def __iter__(self):
        return iter([])


class ConexaoFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *args, **kwargs):
        with _trava_contagem:
            execucoes["total"] += 1
        time.sleep(DEMORA)
        if motor_falho["ligado"]:
            raise OperationalError("select", {}, Exception("SETA fora do ar"))
        return ResultadoFalso()


class MotorFalso:
    def connect(self):
        return ConexaoFalsa()


seta_client.engine_ou_erro = lambda: MotorFalso()
_consulta_pesada_real = seta_client.consulta_pesada


@contextmanager
def espiao(nome, **detalhes):
    """Conta cada consulta pesada e quantas estão dentro da vaga ao mesmo tempo."""

    with _consulta_pesada_real(nome, **detalhes) as info:
        with _trava_contagem:
            chamadas[nome] += 1
            simultaneas["agora"] += 1
            simultaneas["maximo"] = max(simultaneas["maximo"], simultaneas["agora"])
        try:
            yield info
        finally:
            with _trava_contagem:
                simultaneas["agora"] -= 1


seta_client.consulta_pesada = espiao
LIMITE = seta_client.settings.seta_max_consultas_pesadas
assert LIMITE == 2, LIMITE

hoje = hoje_br()
HOJE = hoje.isoformat()


def esperar(condicao, tempo=20.0):
    fim = time.monotonic() + tempo
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.05)
    raise AssertionError("condição não ocorreu a tempo")


def parado():
    m = cache.metricas()
    return m["jobs_ativos"] == 0 and m["jobs_aguardando"] == 0


def limpar():
    """Estado limpo entre cenários: Redis, contadores e cópia local de pagamentos."""

    esperar(parado)
    cache._redis().flushdb()
    cache._contadores.clear()
    seta_client._contadores.clear()
    chamadas.clear()
    execucoes.clear()
    simultaneas.update(agora=0, maximo=0)
    motor_falho["ligado"] = False
    db = SessionLocal()
    try:
        db.query(models.PagamentoSeta).delete()
        db.query(models.PagamentoSetaCliente).delete()
        db.commit()
    finally:
        db.close()


db = SessionLocal()
lead = models.Lead(
    codigo_cliente="00100001", nome="CLIENTE A", cluster="TOP", faixa="11 A 20", dias_atraso=15,
    vencimento_mais_antigo=hoje - timedelta(days=15), status="cobrado", cobrado_em=datetime.utcnow(),
    valor_cobrar=Decimal("100.00"),
)
lead.parcelas = [
    models.LeadParcela(titulo_codigo="TIT1", empresa="01", vencimento=hoje - timedelta(days=15), valor=Decimal("50"), valor_cobrar=Decimal("55")),
    models.LeadParcela(titulo_codigo="TIT2", empresa="02", vencimento=hoje - timedelta(days=15), valor=Decimal("50"), valor_cobrar=Decimal("55")),
]
db.add(lead)
db.commit()
db.close()

EFETIVIDADE = f"/reports/efetividade?cobrado_de={HOJE}&cobrado_ate={HOJE}&dias_janela=7"


def get(url):
    return client.get(url, headers=auth)


def em_paralelo(funcoes):
    with ThreadPoolExecutor(max_workers=len(funcoes)) as pool:
        return [f.result() for f in [pool.submit(f) for f in funcoes]]


# --- Chaves ---------------------------------------------------------------------

a = cache.chave("x", {"faixa": ["21 A 30", "11 A 20"], "loja": None, "de": hoje, "n": []})
b = cache.chave("x", {"de": hoje.isoformat(), "faixa": ["11 A 20", "21 A 30"]})
assert a == b, "ordem dos filtros e filtro vazio não mudam a chave"
assert cache.chave("x", {"faixa": ["11 A 20"]}) != cache.chave("x", {"faixa": ["21 A 30"]})

# --- Cenários 1, 2 e 8: pedidos idênticos ao mesmo tempo (2, 5 e duas abas) ---------

for quantos in (2, 5):
    limpar()
    respostas = em_paralelo([lambda: get(EFETIVIDADE)] * quantos)
    assert all(r.status_code == 200 for r in respostas), [r.text for r in respostas]
    assert all(r.json() == respostas[0].json() for r in respostas)
    assert chamadas["situacao_titulos"] == 1, f"{quantos} pedidos iguais: {dict(chamadas)}"
    assert chamadas["baixas_de_clientes"] == 1, dict(chamadas)
    assert respostas[0].json()["total"]["parcelas_cobradas"] == 2
    assert respostas[0].json()["desatualizado"] is False and respostas[0].json()["gerado_em"]

# --- Cenário 7: exportar e abrir por cliente depois do relatório não consulta mais -----

limpar()
assert get(EFETIVIDADE).status_code == 200
antes = (dict(chamadas), execucoes["total"])
sufixo = f"cobrado_de={HOJE}&cobrado_ate={HOJE}&dias_janela=7"
for url in (
    f"/reports/efetividade.xlsx?{sufixo}",
    f"/reports/efetividade/clientes?{sufixo}",
    f"/reports/efetividade/clientes.xlsx?{sufixo}",
    f"{EFETIVIDADE}&sort_by=valor_pago&sort_dir=desc",  # ordenar não reconsulta
    f"{EFETIVIDADE}&loja=01",  # filtro de loja recorta o snapshot
    f"/relatorios/efetividade?{sufixo}",
):
    r = get(url)
    assert r.status_code == 200, (url, r.text)
assert (dict(chamadas), execucoes["total"]) == antes, "exportação, ordenação e filtro de loja consultaram o SETA"
assert get(f"{EFETIVIDADE}&loja=01").json()["total"]["parcelas_cobradas"] == 1

# --- Cenário 4: Dashboard + Efetividade + base de cobrança ao mesmo tempo ----------------

limpar()


def base_cobranca_pronta():
    fim = time.monotonic() + 20
    while time.monotonic() < fim:
        r = get("/cobranca/relatorio")
        assert r.status_code == 200, r.text
        if r.json()["status"] == "ready":
            return r
        time.sleep(0.2)
    raise AssertionError("base de cobrança não ficou pronta")


respostas = em_paralelo([
    lambda: get(f"/dashboard/summary?de={HOJE}&ate={HOJE}"),
    lambda: get(f"/dashboard/janela-pagamento?de={HOJE}&ate={HOJE}"),
    lambda: get(EFETIVIDADE),
    base_cobranca_pronta,
    lambda: get(f"/reports/pagamentos?cobrado_de={HOJE}&cobrado_ate={HOJE}&dias_janela=7"),
])
assert all(r.status_code == 200 for r in respostas), [r.text for r in respostas]
assert chamadas["base_cobranca"] == 1, dict(chamadas)
assert chamadas["baixas_de_clientes"] == 1, dict(chamadas)  # a cópia dos pagamentos é uma só
assert chamadas["situacao_titulos"] == 1, dict(chamadas)
assert 1 <= simultaneas["maximo"] <= LIMITE, simultaneas
# Card de pagamentos (janela padrão 7) e Quem pagou (mesmo período e janela) leem a mesma lista em cache
assert len(list(cache._redis().scan_iter("snap:relatorio-pagamentos:*"))) == 1

# --- Janela do card configurada em Indicadores: o card bate com Quem pagou da mesma janela ---

for janela in (15, None):
    r = client.put("/config/cobranca/parametros", json={"dias_janela_dashboard": janela}, headers=auth)
    assert r.status_code == 200 and r.json()["parametros"]["dias_janela_dashboard"] == janela, r.text
    card = get(f"/dashboard/janela-pagamento?de={HOJE}&ate={HOJE}").json()
    sufixo = "" if janela is None else f"&dias_janela={janela}"
    rel = get(f"/reports/pagamentos?cobrado_de={HOJE}&cobrado_ate={HOJE}{sufixo}").json()
    assert card["dias_janela"] == janela and card["qtd_pagaram"] == rel["total_clientes"], (card, rel)
assert card["qtd_em_maturacao"] == 0  # sem janela não há prazo a esperar
assert client.put("/config/cobranca/parametros", json={"dias_janela_dashboard": 7}, headers=auth).status_code == 200

# --- Cenário 5: cinco cliques em "Atualizar agora" = um cálculo ------------------------------

limpar()
calculos = Counter()
_resumo_real = dashboard._resumo


def _resumo_contado(*args, **kwargs):
    calculos["resumo"] += 1
    time.sleep(0.5)
    return _resumo_real(*args, **kwargs)


dashboard._resumo = _resumo_contado
respostas = em_paralelo([lambda: get(f"/dashboard/summary?de={HOJE}&ate={HOJE}")] * 5)  # auto=false = forçado
assert all(r.status_code == 200 for r in respostas), [r.text for r in respostas]
assert calculos["resumo"] == 1, calculos
get(f"/dashboard/summary?de={HOJE}&ate={HOJE}")  # outro clique logo depois também reaproveita
assert calculos["resumo"] == 1, calculos
dashboard._resumo = _resumo_real

# --- Cenário 3 e 12: filtros diferentes ao mesmo tempo e fila cheia ----------------------------

limpar()
DEMORA = 0.5
chaves = [cache.chave("base-teste", {"faixa": i}) for i in range(12)]
pronto: dict[str, bool] = {}


def pedir(i):
    def calcular():
        return seta_client.buscar_base_cobranca(faixas=[(i, i + 9)])

    return cache.buscar_ou_iniciar(chaves[i], calcular)


inicio = time.monotonic()
primeira = [pedir(i) for i in range(12)]
assert time.monotonic() - inicio < 1.0, "pedir não pode esperar o SETA: a aplicação continua responsiva"
m = cache.metricas()
assert all(r["status"] == "processing" for r in primeira)
assert m["jobs_iniciados"] <= cache.JOBS_SIMULTANEOS + cache.JOBS_AGUARDANDO, m
assert m["jobs_recusados"] >= 12 - (cache.JOBS_SIMULTANEOS + cache.JOBS_AGUARDANDO), m
assert m["jobs_ativos"] + m["jobs_aguardando"] <= cache.JOBS_SIMULTANEOS + cache.JOBS_AGUARDANDO, m
# quem foi recusado volta a pedir (como o pollAsync) e acaba calculado, sem passar do limite
fim = time.monotonic() + 40
faltam = set(range(12))
while faltam and time.monotonic() < fim:
    for i in sorted(faltam):
        if pedir(i)["status"] == "ready":
            faltam.discard(i)
    time.sleep(0.1)
assert not faltam, f"não terminaram: {faltam}"
assert chamadas["base_cobranca"] == 12, dict(chamadas)
assert simultaneas["maximo"] <= LIMITE, simultaneas
DEMORA = 0.4

# --- Job que ninguém pede mais é descartado sem consultar o SETA --------------------------------

limpar()
cache.INTERESSE_SEGUNDOS = 0.3
DEMORA = 0.8
for i in range(6):
    pedir(i)
time.sleep(0.5)  # o usuário trocou de filtro: ninguém mais pede os que estavam na fila
esperar(parado)
assert chamadas["base_cobranca"] == cache.JOBS_SIMULTANEOS, dict(chamadas)
assert cache.metricas()["jobs_descartados"] == 6 - cache.JOBS_SIMULTANEOS, cache.metricas()
cache.INTERESSE_SEGUNDOS = 45
DEMORA = 0.4

# --- Falha do cálculo: nada é guardado e não há tempestade de tentativas -------------------------

limpar()
tentativas = Counter()


def falha():
    tentativas["n"] += 1
    raise seta_client.SetaIndisponivel("Falha ao consultar o SETA (OperationalError)")


k = cache.chave("falha", {"a": 1})
assert cache.buscar_ou_iniciar(k, falha)["status"] == "processing"
esperar(parado)
for _ in range(3):  # os próximos polls recebem o erro na hora
    try:
        cache.buscar_ou_iniciar(k, falha)
        raise AssertionError("devia levantar CalculoFalhou")
    except cache.CalculoFalhou as exc:
        assert "SETA" in str(exc)
assert tentativas["n"] == 1, tentativas
assert cache._redis().get(f"snap:{k}") is None, "erro não vira snapshot"

# --- Cenário 11: a trava que venceu não é apagada por quem a perdeu ------------------------------

limpar()
a, b = cache._Trava("chave-trava"), cache._Trava("chave-trava")
assert a.adquirir()
assert not b.adquirir(), "só um dono por vez"
cache._redis().delete(a.nome)  # o TTL de A venceu
assert b.adquirir(), "B pega a trava nova"
a.liberar()  # A termina depois
assert cache._redis().get(b.nome) == b.token, "A não pode apagar a trava de B"
b.liberar()
assert cache._redis().get(b.nome) is None

# o batimento mantém a trava de um job longo
cache.TRAVA_TTL_SEGUNDOS, cache.TRAVA_RENOVA_A_CADA_SEGUNDOS = 1, 0.2
c = cache._Trava("chave-longa")
assert c.adquirir()
time.sleep(2.5)
assert cache._redis().get(c.nome) == c.token, "trava renovada enquanto o job vive"
c.liberar()
assert cache._redis().get(c.nome) is None
cache.TRAVA_TTL_SEGUNDOS, cache.TRAVA_RENOVA_A_CADA_SEGUNDOS = 60, 20

# --- obter_ou_calcular: sem estouro de cache -------------------------------------------------------

limpar()
calculos.clear()


def lento():
    calculos["n"] += 1
    time.sleep(0.6)
    return {"valor": calculos["n"]}


k = cache.chave("stampede", {"a": 1})
resultados = em_paralelo([lambda: cache.obter_ou_calcular(k, lento)] * 8)
assert calculos["n"] == 1 and all(r == {"valor": 1} for r in resultados), (calculos, resultados)

# erro no recálculo forçado não troca o snapshot bom
cache.obter_ou_calcular(k, lento)


def quebra():
    raise RuntimeError("falhou")


try:
    cache.obter_ou_calcular(k, quebra, reaproveitar=False)
except RuntimeError:
    pass
else:
    # logo após o cálculo o snapshot tem menos de 5 s e é reaproveitado: força a idade
    envelope = json.loads(cache._redis().get(f"snap:{k}"))
    envelope["g"] -= 60
    cache._redis().set(f"snap:{k}", json.dumps(envelope), ex=300)
    try:
        cache.obter_ou_calcular(k, quebra, reaproveitar=False)
        raise AssertionError("devia levantar")
    except RuntimeError:
        pass
assert json.loads(cache._redis().get(f"snap:{k}"))["d"] == {"valor": 1}, "o snapshot anterior permanece"

# --- Cenário 10: SETA falha na atualização, o snapshot anterior continua --------------------------

limpar()
assert get(EFETIVIDADE).status_code == 200
chave_efet = next(cache._redis().scan_iter("snap:efetividade:*"))
envelope = json.loads(cache._redis().get(chave_efet))
envelope["g"] -= 400  # passou de 5 min (fresco) e está dentro de 30 min (velho)
cache._redis().set(chave_efet, json.dumps(envelope), ex=1800)
motor_falho["ligado"] = True
total_antes = execucoes["total"]
r = get(EFETIVIDADE)  # devolve o velho na hora; a atualização em segundo plano falha
assert r.status_code == 200 and r.json()["desatualizado"] is True, r.text
esperar(parado)
assert json.loads(cache._redis().get(chave_efet))["g"] == envelope["g"], "falha não troca o snapshot"
assert cache._redis().exists(chave_efet.replace("snap:", "erro:", 1)), "falha em quarentena"
consultas_da_falha = execucoes["total"] - total_antes
assert consultas_da_falha >= 1
for _ in range(3):  # a quarentena evita nova consulta a cada clique
    r = get(EFETIVIDADE)
    assert r.status_code == 200 and r.json()["desatualizado"] is True
esperar(parado)
assert execucoes["total"] - total_antes == consultas_da_falha, "tentou o SETA de novo durante a quarentena"
# SETA volta: a atualização em segundo plano troca o snapshot
motor_falho["ligado"] = False
cache._redis().delete(chave_efet.replace("snap:", "erro:", 1))
assert get(EFETIVIDADE).json()["desatualizado"] is True
esperar(parado)
assert get(EFETIVIDADE).json()["desatualizado"] is False

# --- Cenário 9: Redis fora não vira consulta direta ao SETA ---------------------------------------

limpar()
cliente_original = cache._client
cache._client = redis.from_url("redis://localhost:1/0", decode_responses=True, socket_connect_timeout=0.5)
for url in (EFETIVIDADE, f"/dashboard/janela-pagamento?de={HOJE}&ate={HOJE}", "/cobranca/relatorio",
            f"/reports/pagamentos?cobrado_de={HOJE}&cobrado_ate={HOJE}"):
    r = get(url)
    assert r.status_code == 503 and "Redis" in r.json()["detail"], (url, r.status_code, r.text)
    assert r.json()["codigo"] == "cache_indisponivel" and "x-seta-fora" not in r.headers, r.text
r = get(f"/dashboard/summary?de={HOJE}&ate={HOJE}")  # só dados locais
assert r.status_code == 200, r.text
assert sum(chamadas.values()) == 0 and execucoes["total"] == 0, "Redis fora: nenhuma consulta ao SETA"
cache._client = cliente_original

# --- Cenário 13 e capacidade: sincronização de pagamentos junto de consultas pesadas ------------------

limpar()
DEMORA = 0.8
for i in range(2):
    pedir(i)
esperar(lambda: simultaneas["agora"] == LIMITE)  # as duas vagas ocupadas pela base de cobrança


def sincronizar_agora():
    s = SessionLocal()
    try:
        return pagamentos_seta.sincronizar(s, {"00100001"})
    finally:
        s.close()


inicio = time.monotonic()
sincronizar_agora()  # espera uma vaga (não passa do limite) e conclui
assert time.monotonic() - inicio >= 0.3, "a cópia dos pagamentos esperou vaga"
assert chamadas["baixas_de_clientes"] == 1
assert simultaneas["maximo"] <= LIMITE, simultaneas
esperar(parado)

# duas vagas ocupadas, fila de espera zerada: recusa na hora e o HTTP responde 429
limpar()
liberar = threading.Event()


def segurar():
    with seta_client.consulta_pesada("segurando"):
        liberar.wait(10)


segurando = [threading.Thread(target=segurar) for _ in range(LIMITE)]
for t in segurando:
    t.start()
esperar(lambda: simultaneas["agora"] == LIMITE)
seta_client.MAX_AGUARDANDO = 0
r = get(EFETIVIDADE)
assert r.status_code == 429 and r.headers["retry-after"] == "10", (r.status_code, r.text)
assert not list(cache._redis().scan_iter("erro:*")) and not list(cache._redis().scan_iter("snap:*")), "ocupado não é falha nem snapshot"
# espera por vaga com prazo curto
seta_client.MAX_AGUARDANDO, seta_client.ESPERA_MAXIMA_SEGUNDOS = 4, 0.3
inicio = time.monotonic()
r = get(EFETIVIDADE)
assert r.status_code == 429 and time.monotonic() - inicio < 5, r.text
assert seta_client.metricas()["recusadas"] == 2, seta_client.metricas()
liberar.set()
for t in segurando:
    t.join()
seta_client.ESPERA_MAXIMA_SEGUNDOS = 60
esperar(lambda: simultaneas["agora"] == 0)
assert get(EFETIVIDADE).status_code == 200, "liberou a capacidade: o mesmo pedido agora passa"

# --- SETA sem conexão: 503 com código e aviso em toda resposta até reconectar ---------------------

limpar()


@app.get("/_teste/seta-fora")
def _seta_fora():
    raise seta_client.SetaIndisponivel("Falha ao consultar o SETA (OperationalError)")


r = get("/_teste/seta-fora")
assert r.status_code == 503 and r.json()["codigo"] == "seta_indisponivel", r.text
assert "x-seta-fora" not in r.headers, "erro de consulta sem falha de conexão não é SETA fora"

seta_client.is_configured = lambda: True
sem_conexao = create_engine("postgresql+psycopg://u:p@localhost:1/x", connect_args={"connect_timeout": 2})
com_conexao = create_engine(os.environ["DATABASE_URL"])
for motor in (sem_conexao, com_conexao):
    seta_client._monitorar_conexao(motor)
seta_client.engine_ou_erro = lambda: sem_conexao
r = get("/seta/status")
assert r.json()["conectado"] is False and r.headers["x-seta-fora"], (r.text, r.headers)
desde = r.headers["x-seta-fora"]
assert get("/dashboard/summary?de={0}&ate={0}".format(HOJE)).headers["x-seta-fora"] == desde, "toda resposta avisa"
get("/seta/status")
assert seta_client.fora_desde().isoformat() == desde, "nova falha não muda o início"
seta_client.engine_ou_erro = lambda: com_conexao
r = get("/seta/status")
assert r.json()["conectado"] is True and "x-seta-fora" not in r.headers, (r.text, r.headers)

print("OK")
