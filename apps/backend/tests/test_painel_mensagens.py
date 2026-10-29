"""Painel de mensagens do Dashboard (GET /dashboard/painel-mensagens): quadros do
analytics da Meta (todas, entregues por categoria, gratuitas, pagas, cobrança em
BRL) e métricas por template (entregues, lidas, cliques, conversão, custo).

Sem filtro de template/campanha os quadros vêm da Meta; com um deles a Meta não
filtra, então os quadros passam a contar a fila e o custo é o
gasto real da Meta por WABA e categoria rateado pela fatia dos envios do CRM. Filtro de
telefone vai para o analytics da WABA e restringe a fila. Categoria sem gasto no
período deixa o custo "—" com aviso.

Executa com assert simples, sem pytest. Encerra imprimindo 'OK'.
"""

import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_painel_mensagens"
os.environ["JWT_SECRET"] = "segredo-de-teste-painel-mensagens-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-painel-mensagens"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from fastapi.testclient import TestClient

from app import crypto, models, schemas
from app.database import SessionLocal
from app.main import app
from app.services import painel_mensagens
from app.services import custo_whatsapp
from app.services.custo_whatsapp import CustoWhatsapp

with TestClient(app):  # sobe o schema
    pass

DIA = date(2026, 10, 20)
NUM1, NUM2 = "+55 11 4000-0001", "+55 11 4000-0002"
CHAMADAS: list[tuple] = []

db = SessionLocal()
token = models.MetaToken(nome="t", token_cifrado=crypto.cifrar("TOKEN"), ultimos4="TOKE", waba_id="waba1")
db.add(token)
db.flush()
n1 = models.WhatsappNumber(waba_id="waba1", phone_number_id="pn1", display_phone_number=NUM1, meta_token_id=token.id)
n2 = models.WhatsappNumber(waba_id="waba1", phone_number_id="pn2", display_phone_number=NUM2, meta_token_id=token.id)
util = models.Template(
    name="Aviso", meta_template_name="aviso", category="UTILITY", status=models.TemplateStatus.approved,
    waba_id="waba1", meta_template_id="111",
)
mkt = models.Template(
    name="Oferta", meta_template_name="oferta", category="MARKETING", status=models.TemplateStatus.approved,
    waba_id="waba1", meta_template_id="222",
)
faixa = models.Faixa(name="1 a 3 dias")
campanha = models.Faixa(name="Campanha: Black", tipo=models.TIPO_CAMPANHA)
db.add_all([n1, n2, util, mkt, faixa, campanha])
db.flush()


def item(codigo, numero, template, f=None, atraso=None, entregue=False, lida=False, status=models.QueueStatus.sent):
    db.add(
        models.QueueItem(
            faixa_id=(f or faixa).id, codigo_cliente=codigo, celular="5511999990000", celular_original="11999990000",
            status=status, sent_at=datetime(2026, 10, 20, 15, 0), created_at=datetime(2026, 10, 20, 14, 0),
            whatsapp_number_id=numero.id, template_id=template.id if template else None, faixa_atraso=atraso,
            entregue_em=datetime(2026, 10, 20, 15, 1) if entregue or lida else None,
            lida_em=datetime(2026, 10, 20, 16, 0) if lida else None,
        )
    )


# Template de utilidade: 4 envios pelo número 1 (3 clientes, c1 duas vezes) + 1 pelo número 2
for codigo in ("c1", "c1", "c2", "c3"):
    item(codigo, n1, util)
item("c4", n2, util)
# Marketing: 2 envios sem tarifa no período
item("c5", n1, mkt)
item("c5", n1, mkt)
db.commit()
util_id, mkt_id, n1_id = util.id, mkt.id, n1.id

# Pricing Analytics já em BRL: utilidade R$ 0,0068 por mensagem cobrada; 40 gratuitas; serviço cobrado
CUSTO = CustoWhatsapp(
    {DIA: Decimal("12.20")},
    por_tipo_categoria={
        ("waba1", NUM1, "UTILITY", "REGULAR"): [Decimal("10.20"), 1500],
        ("waba1", NUM1, "SERVICE", "REGULAR"): [Decimal("2.00"), 100],
        ("waba1", NUM1, "UTILITY", "FREE_CUSTOMER_SERVICE"): [Decimal("0"), 40],
    },
)


class MetaFalsa:
    def __init__(self, token):
        pass

    async def message_analytics(self, waba, *, start_unix, end_unix, product_types, telefones=None):
        CHAMADAS.append(("mensagens", waba, tuple(product_types), tuple(telefones or ())))
        return [{"sent": 50}] if product_types == [100] else [{"sent": 1000, "delivered": 900}]

    async def template_analytics(self, waba, template_ids, *, start_unix, end_unix):
        CHAMADAS.append(("templates", waba, tuple(template_ids)))
        return [{"template_id": "111", "delivered": 80, "read": 40, "clicked": [{"type": "url_button", "count": 8}]}]


painel_mensagens.custo_whatsapp.custo_detalhado = lambda db_, de, ate: CUSTO
custo_whatsapp.meta_client.MetaClient = MetaFalsa
JANELAS: list = []


def pagamentos_falsos(**filtros):
    JANELAS.append(filtros["dias_janela"])
    return SimpleNamespace(data=[{"codigo_cliente": "c1", "valor_pago": Decimal("100.00")}])


painel_mensagens.pagamentos_service.snapshot_pagamentos = pagamentos_falsos
painel_mensagens.hoje_br = lambda: date(2026, 10, 28)


def painel(**filtros):
    dados = painel_mensagens.montar(
        db, DIA, DIA, **{"telefones": [], "wabas": [], "templates": [], "campanha": "", **filtros}
    )
    return schemas.PainelMensagensOut(**dados)


# Sem filtro: quadros da Meta, em BRL
p = painel()
assert p.origem == "meta"
assert (p.todas.enviadas, p.todas.entregues, p.todas.recebidas) == (1000, 900, 50), p.todas
assert p.entregues.total == 1640 and p.entregues.por_categoria == {"UTILITY": 1540, "SERVICE": 100}, p.entregues
assert p.pagas.total == 1600 and p.pagas.por_categoria == {"UTILITY": 1500, "SERVICE": 100}, p.pagas
assert p.gratuitas.total == 40 and p.gratuitas.por_tipo == {"FREE_CUSTOMER_SERVICE": 40}, p.gratuitas
assert p.cobranca.total_brl == Decimal("12.20") and p.cobranca.por_categoria["UTILITY"] == Decimal("10.20"), p.cobranca
assert ("mensagens", "waba1", (0, 2), ()) in CHAMADAS and ("mensagens", "waba1", (100,), ()) in CHAMADAS

# Por template: entregues/lidas/cliques da Meta, conversão pelos pagamentos, custo = gasto real rateado pelos envios
linhas = {t.nome: t for t in p.linhas}  # a linha do template é por nome
u = linhas["Aviso"]
assert (u.enviados, u.cobrados, u.pagaram) == (5, 4, 1), u
assert (u.entregues, u.lidas, u.cliques) == (80, 40, 8), u
assert u.taxa_visualizacao == Decimal("0.5") and u.taxa_cliques == Decimal("0.1"), u
assert u.conversao == Decimal("0.25"), u
assert u.roas == Decimal("9.80"), u.roas  # 100,00 pagos ÷ 10,20
assert u.custo_brl == Decimal("10.20"), u.custo_brl  # os 5 envios do Aviso são todos os do CRM em utilidade: levam o gasto inteiro
# Marketing sem gasto no período: custo "—" e aviso; sem insights do template (Meta não devolveu)
m = linhas["Oferta"]
assert m.enviados == 2 and m.custo_brl is None and m.entregues is None and m.taxa_visualizacao is None and m.roas is None, m
assert any("Sem gasto" in a and "MARKETING" in a for a in p.avisos), p.avisos

# Telefone: vai para o analytics da WABA (só dígitos) e restringe a fila
CHAMADAS.clear()
p = painel(telefones=[n1_id])
assert ("mensagens", "waba1", (0, 2), ("551140000001",)) in CHAMADAS, CHAMADAS
assert {t.nome: t.enviados for t in p.linhas} == {"Aviso": 4, "Oferta": 2}, p.linhas
assert p.entregues.total == 1640  # só o número 1 tem custo no Pricing Analytics do teste
assert any("não filtra por telefone" in a for a in p.avisos), p.avisos

# Número que não existe no filtro: nada entra
p = painel(wabas=["outra"])
assert p.entregues.total == 0 and p.linhas == [], p

# Template marcado: quadros da fila, custo = gasto real rateado pelos envios
p = painel(templates=[util_id])
assert p.origem == "fila" and p.entregues is None and p.gratuitas is None
assert (p.todas.enviadas, p.todas.entregues, p.todas.recebidas) == (5, None, None), p.todas
assert p.pagas.total == 5 and p.pagas.por_categoria == {"UTILITY": 5}, p.pagas
assert p.cobranca.total_brl == Decimal("10.20") and p.cobranca.por_categoria == {"UTILITY": Decimal("10.20")}, p.cobranca
assert [t.nome for t in p.linhas] == ["Aviso"]

# Template sem gasto: total da cobrança "—"
p = painel(templates=[mkt_id])
assert p.cobranca.total_brl is None and p.pagas.por_categoria == {"MARKETING": 2}, p

# Meta sem leitura (nenhuma WABA com custo): quadros vazios, tabela por template segue da fila
CUSTO_FORA = CustoWhatsapp(None, "Falha ao consultar a Meta: fora")
painel_mensagens.custo_whatsapp.custo_detalhado = lambda db_, de, ate: CUSTO_FORA
p = painel()
assert p.todas is None and p.entregues is None and p.cobranca is None, p
assert any("fora" in a for a in p.avisos) and len(p.linhas) == 2, p.avisos

# Agrupar por campanha/faixa de atraso: cada linha leva a parte dos templates dela, igual à fatia dos envios de cada template
painel_mensagens.custo_whatsapp.custo_detalhado = lambda db_, de, ate: CUSTO
item("c6", n1, util, f=campanha, atraso="4 a 7 dias", lida=True)
item("c7", n1, util, f=campanha, atraso="1 a 3 dias", entregue=True)
db.commit()
campanha_id = campanha.id
CHAMADAS.clear()
p = painel(agrupar="campanha")
por = {l.chave: l for l in p.linhas}
assert set(por) == {"regua", campanha_id}, por.keys()
assert por["regua"].nome == "Régua de cobrança" and por["regua"].enviados == 7 and por["regua"].custo_brl is None, por["regua"]
c = por[campanha_id]
assert c.nome == "Campanha: Black" and (c.enviados, c.cobrados, c.pagaram) == (2, 2, 0), c
# Campanha tem recibos do Chatwoot (2 entregues, 1 lida): dado real; os cliques são a parte da Meta (2 dos 7 envios do Aviso)
assert (c.entregues, c.lidas, c.cliques) == (2, 1, 2), c
assert c.taxa_visualizacao == Decimal("0.5") and c.taxa_cliques == Decimal(2) / 23 and c.categoria == "", c
# Régua sem recibos: a parte da Meta (80 entregues, 40 lidas e 8 cliques repartidos em 5 e 2 dos 7 envios)
assert (por["regua"].entregues, por["regua"].lidas, por["regua"].cliques) == (57, 29, 6), por["regua"]
assert c.roas == Decimal("0.00") and por["regua"].roas is None, (c.roas, por["regua"].roas)
assert c.custo_brl == Decimal("2.91"), c.custo_brl  # 10,20 × 2 ÷ 7 envios do CRM em utilidade

p = painel(agrupar="faixa")
por = {l.nome: l for l in p.linhas}
assert set(por) == {"1 a 3 dias", "4 a 7 dias"}, por.keys()  # faixa de atraso do cliente: a da campanha, senão a da régua
assert por["1 a 3 dias"].enviados == 8 and por["4 a 7 dias"].enviados == 1, por
assert (por["4 a 7 dias"].entregues, por["4 a 7 dias"].lidas) == (1, 1), por  # recibos do Chatwoot
assert (por["1 a 3 dias"].entregues, por["1 a 3 dias"].lidas) == (1, 0), por
# Ordem do "Por faixa" (progressão de atraso das regras), não por quantidade: a faixa de mais atraso, mesmo com mais envios, vem depois
for i in range(10):
    item(f"x{i}", n1, util, atraso="4 a 7 dias")
db.commit()
p = painel(agrupar="faixa")
assert [l.nome for l in p.linhas] == ["1 a 3 dias", "4 a 7 dias"] and p.linhas[1].enviados > p.linhas[0].enviados, p.linhas

# Por faixa substitui o antigo "Por faixa" do Dashboard: Pendente e Erro da fila, envio sem template registrado
# conta (sem custo nem ROAS), pagamento em qualquer data depois do 1º envio (sem janela) e linha de total
faixa8 = models.Faixa(name="8 a 15 dias")
db.add(faixa8)
db.flush()
item("p1", n1, util, status=models.QueueStatus.pending)
item("p2", n1, util, status=models.QueueStatus.reserved)
item("e1", n1, util, status=models.QueueStatus.error)
item("p3", n1, util, f=faixa8, status=models.QueueStatus.pending)  # faixa só com fila aberta também ganha linha
item("c1", n1, None, atraso="4 a 7 dias")  # c1 também em outra faixa, num envio sem template registrado
db.commit()
JANELAS.clear()
p = painel(agrupar="faixa")
assert JANELAS == [None], JANELAS  # por faixa não usa a janela de pagamento
por = {l.nome: l for l in p.linhas}
a, b, d = por["1 a 3 dias"], por["8 a 15 dias"], por["4 a 7 dias"]
assert (a.pendente, a.erro) == (2, 1) and (b.pendente, b.erro, b.enviados, b.cobrados) == (1, 0, 0, 0), (a, b)
assert a.faixa_id == faixa.id and b.faixa_id == faixa8.id, (a.faixa_id, b.faixa_id)
assert a.valor_pago == Decimal("100.00"), a  # custo None: a faixa tem envio de Marketing, sem tarifa no período
assert d.valor_pago == Decimal("100.00") and d.custo_brl is not None and d.roas is not None, d  # envio sem template: custo do dia
t = p.total
assert t.nome == "Total" and (t.pendente, t.erro) == (3, 1), t
assert t.enviados == sum(l.enviados for l in p.linhas), t
assert (t.pagaram, t.valor_pago) == (1, Decimal("100.00")), t  # c1 está em duas linhas e conta uma vez
assert t.conversao == Decimal(1) / t.cobrados and t.custo_brl is None and t.roas is None, t
assert t.cobrados < sum(l.cobrados for l in p.linhas), (t.cobrados, [l.cobrados for l in p.linhas])  # cliente em duas faixas conta uma vez

# Custo misto: o envio sem template (c1) leva o custo médio da mensagem no dia; o gasto dele sai do que os
# templates rateiam, então as linhas continuam somando o gasto do dia (menos o de SERVICE, que nenhum template tem)
taxa = painel_mensagens.custo_whatsapp.custo_por_envio(db, DIA, DIA)[0][DIA]
for modo in ("template", "faixa", "campanha"):
    pm = painel(agrupar=modo)
    antigo = [l for l in pm.linhas if l.chave == "sem_template"]
    assert bool(antigo) == (modo == "template"), (modo, [l.chave for l in pm.linhas])
    if antigo:
        assert antigo[0].nome == "Sem template registrado" and antigo[0].enviados == 1 and antigo[0].custo_brl == taxa, antigo[0]
        assert antigo[0].entregues is None and antigo[0].roas is not None, antigo[0]
util_linha = next(l for l in painel(agrupar="template").linhas if l.chave == "Aviso")
assert util_linha.custo_brl == Decimal("10.20") * (Decimal("12.20") - taxa) / Decimal("12.20"), util_linha.custo_brl

# Templates de mesmo nome (um registro por WABA) somam numa linha só
util2 = models.Template(
    name="Aviso", meta_template_name="aviso", category="UTILITY", status=models.TemplateStatus.approved,
    waba_id="waba2", meta_template_id="333",
)
db.add(util2)
db.commit()
util2_id = util2.id
antes = painel(templates=[util_id]).linhas[0]
item("y1", n2, util2)
item("y2", n2, util2)
db.commit()
p = painel(templates=[util_id, util2_id])
assert [(l.nome, l.enviados, l.cobrados, l.categoria) for l in p.linhas] == [("Aviso", antes.enviados + 2, antes.cobrados + 2, "UTILITY")], p.linhas

# Filtro de template vale em qualquer agrupamento
p = painel(agrupar="campanha", templates=[mkt_id])
assert [l.chave for l in p.linhas] == ["regua"] and p.linhas[0].enviados == 2, p.linhas

# Tipo de mensagem = categoria do Orçamento (marketing, utilitario, servico, outras): vale na tabela (categoria do
# template; envio sem template e fila aberta ficam fora) e nos quadros da Meta, que não vêm por categoria em "todas"
p = painel(tipos=["utilitario"])
assert [l.nome for l in p.linhas] == ["Aviso"] and p.todas is None, [l.nome for l in p.linhas]
assert set(p.entregues.por_categoria) == {"UTILITY"}, p.entregues.por_categoria
p = painel(tipos=["marketing"])
assert [l.nome for l in p.linhas] == ["Oferta"], [l.nome for l in p.linhas]
assert p.entregues.por_categoria == {}, p.entregues.por_categoria
p = painel(tipos=["servico", "outras"])
assert p.linhas == [] and p.total is None and set(p.entregues.por_categoria) == {"SERVICE"}, p
p = painel(agrupar="faixa", tipos=["utilitario"])
assert p.linhas and all(l.pendente == 0 and l.erro == 0 for l in p.linhas), p.linhas  # fila aberta ainda não tem template
assert all(l.chave != "sem_template" for l in painel(tipos=["utilitario"]).linhas)

# Endpoint exige o período e rejeita de > ate
with TestClient(app) as client:
    login = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": os.environ["ADMIN_PASSWORD"]})
    assert login.status_code == 200, login.text
    cabecalho = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/dashboard/painel-mensagens", headers=cabecalho).status_code == 422
    assert client.get("/dashboard/painel-mensagens?de=2026-10-20&ate=2026-10-20&agrupar=x", headers=cabecalho).status_code == 422
    resposta = client.get("/dashboard/painel-mensagens?de=2026-10-21&ate=2026-10-20", headers=cabecalho)
    assert resposta.status_code == 400, resposta.text

db.close()
print("OK")
