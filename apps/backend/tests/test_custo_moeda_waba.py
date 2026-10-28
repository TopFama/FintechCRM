"""Custo do WhatsApp na moeda de cobrança de cada WABA.

A Meta devolve o custo do Pricing Analytics na moeda da WABA (campo currency):
WABA em USD é convertida pela cotação, WABA em BRL entra como veio, WABA sem
o campo é tratada como USD e moeda que não sabemos converter vira aviso da
WABA, sem entrar no total. Sem nenhuma WABA em dólar a cotação nem é buscada.
Executado com asserts simples sem pytest, encerrando com 'OK'.
"""

import os
import re
import tempfile
from datetime import date, datetime, time
from decimal import Decimal

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_custo_moeda")
os.environ["JWT_SECRET"] = "segredo-de-teste-custo-moeda-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-custo-moeda-987"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import httpx

from app import cambio, crypto, models
from app.database import SessionLocal
from app.main import _run_migrations
from app.meta_client import MetaClient
from app.services import custo_whatsapp
from app.timezone import BUSINESS_TZ

DIA = date(2026, 10, 20)
INICIO_DIA = int(datetime.combine(DIA, time.min, BUSINESS_TZ).timestamp())
# WABA → (currency devolvido pela Meta, número, custo do dia na moeda dela)
WABAS = {
    "waba-usd": ("USD", "+55 11 4000-0001", 2.0),
    "waba-brl": ("BRL", "+55 11 4000-0002", 31.47),
    "waba-sem-moeda": (None, "+55 11 4000-0003", 1.0),
    "waba-eur": ("EUR", "+55 11 4000-0004", 5.0),
}
PEDIDOS: list[str] = []


def meta_falsa(request: httpx.Request) -> httpx.Response:
    waba_id = request.url.path.rsplit("/", 1)[-1]
    campos = request.url.params.get("fields", "")
    PEDIDOS.append(campos)
    assert campos.startswith("currency,pricing_analytics"), campos
    assert re.search(r"start\(\d+\)\.end\(\d+\)", campos), campos
    moeda, numero, custo = WABAS[waba_id]
    ponto = {"start": INICIO_DIA, "end": INICIO_DIA + 86400, "phone_number": numero, "volume": 10,
             "cost": custo, "pricing_type": "REGULAR", "pricing_category": "UTILITY"}
    corpo = {"id": waba_id, "pricing_analytics": {"data": [{"data_points": [ponto]}]}}
    if moeda:
        corpo["currency"] = moeda
    return httpx.Response(200, json=corpo)


COTACOES: list[int] = []


async def cotacao_falsa() -> float:
    COTACOES.append(1)
    return 5.0


MetaClient.default_transport = httpx.MockTransport(meta_falsa)
cambio.cotacao_usd_brl = cotacao_falsa
_run_migrations()


def cadastrar(wabas: list[str]) -> None:
    db = SessionLocal()
    db.query(models.WhatsappNumber).delete()
    db.query(models.MetaToken).delete()
    for waba_id in wabas:
        token = models.MetaToken(nome=waba_id, token_cifrado=crypto.cifrar(f"TOKEN_{waba_id}"), ultimos4="TEST",
                                 waba_id=waba_id)
        db.add(token)
        db.flush()
        db.add(models.WhatsappNumber(waba_id=waba_id, phone_number_id=f"pn-{waba_id}",
                                     display_phone_number=WABAS[waba_id][1], meta_token_id=token.id))
    db.commit()
    db.close()


def calcular() -> custo_whatsapp.CustoWhatsapp:
    db = SessionLocal()
    try:
        return custo_whatsapp.custo_detalhado(db, DIA, DIA)
    finally:
        db.close()


# Quatro WABAs: USD e sem moeda convertem (×5), BRL entra como veio, EUR fica de fora com aviso
cadastrar(list(WABAS))
r = calcular()
assert r.motivo is None, r.motivo
assert r.por_numero["+55 11 4000-0001"] == Decimal("10.0"), r.por_numero
assert r.por_numero["+55 11 4000-0002"] == Decimal("31.47"), r.por_numero
assert r.por_numero["+55 11 4000-0003"] == Decimal("5.0"), r.por_numero
assert r.por_numero["+55 11 4000-0004"] == Decimal("0"), r.por_numero
assert r.por_dia == {DIA: Decimal("46.47")}, r.por_dia
assert r.por_categoria[(DIA, "+55 11 4000-0002", "utilitario")] == [Decimal("31.47"), 10], r.por_categoria
assert [(a.waba_id, a.motivo) for a in r.avisos] == [("waba-eur", "moeda de cobrança EUR não suportada")], r.avisos
assert len(PEDIDOS) == 4 and COTACOES, (PEDIDOS, COTACOES)

# Só WABA em reais: o custo entra como veio e a cotação do dólar não é buscada
COTACOES.clear()
cadastrar(["waba-brl"])
r = calcular()
assert r.por_dia == {DIA: Decimal("31.47")}, r.por_dia
assert not r.avisos and not COTACOES, (r.avisos, COTACOES)

# Só WABA em moeda não suportada: sem custo, com o motivo
cadastrar(["waba-eur"])
r = calcular()
assert r.por_dia is None and "EUR" in r.motivo, (r.por_dia, r.motivo)

print("OK")
