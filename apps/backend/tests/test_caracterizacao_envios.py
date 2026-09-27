"""Testes de caracterização do fluxo de envio (review de responsabilidade, Fase 5).

"Fotografam" o comportamento de hoje do caminho cliente entra na fila → worker
dispara → envio sai → status atualiza, para as refatorações do backlog
(docs/architecture/backlog-refatoracao.md) não mudarem nada sem perceber.
Não dizem que o comportamento está certo: um teste que falhar depois de uma
refatoração é desvio a investigar, não assert a ajustar.

Cobre, com Postgres de verdade e a Meta simulada:
- entrada na fila: `clientes_bloqueados_hoje`, `enfileirar_clientes`
  (variáveis, telefone, bloqueio, formato achatado e por template),
  `enfileirar_leads`, upload de planilha na faixa;
- saída: `worker.run_dispatch_cycle` com pausa (cliente, faixa, loja),
  parada, blacklist, "já cobrado hoje", erro da Meta e falha incerta;
- regra de uma comunicação por cliente por dia em todos esses caminhos;
- `expirar_nao_enviados`.

Rodar (Postgres UTF-8 em localhost:15432, senha "t", banco agy_carac recriado antes):
    PYTHONPATH=. .venv/bin/python tests/test_caracterizacao_envios.py
Imprime 'OK' ao final se tudo passar.
"""

import asyncio
import io
import json
from decimal import Decimal
import os
import tempfile
from datetime import date, datetime, timedelta

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_carac"
os.environ["JWT_SECRET"] = "segredo-de-teste-longo-e-seguro-caracterizacao"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["COOKIE_SECURE"] = "false"

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

import httpx  # noqa: E402
import openpyxl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import dispatch_service, elegibilidade, fila_automatica, models, worker  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.meta_client import MetaClient  # noqa: E402
from app.timezone import hoje_br  # noqa: E402

# --- Meta simulada: guarda o que teria saído -----------------------------------

enviados: list[dict] = []
modo_meta = {"resposta": "ok"}  # "ok" | "erro" (400 da Meta) | "servidor" (503) | "queda" (falha de rede)


def _meta(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/messages"):
        corpo = json.loads(request.content)
        if modo_meta["resposta"] == "queda":
            raise httpx.ConnectError("conexão caiu", request=request)
        if modo_meta["resposta"] == "erro":
            return httpx.Response(400, json={"error": {"message": "número não tem WhatsApp"}})
        if modo_meta["resposta"] == "servidor":
            return httpx.Response(503, json={"error": {"message": "Service temporarily unavailable"}})
        enviados.append(corpo)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(enviados)}"}]})
    return httpx.Response(404, json={"error": {"message": request.url.path}})


MetaClient.default_transport = httpx.MockTransport(_meta)
dispatch_service.token_do_numero = lambda db, number: "token-de-teste"


def para(numero: str) -> list[str]:
    return [e["to"] for e in enviados if e["to"] == numero]


def parametros(e: dict) -> list[str]:
    corpo = next(c for c in e["template"]["components"] if c["type"] == "body")
    return [p["text"] for p in corpo["parameters"]]


# --- Ambiente: o lifespan roda as migrations e cria o admin ---------------------

client = TestClient(app)
client.__enter__()
resp = client.post("/auth/login", json={"email": settings.admin_email, "password": "senha-admin-teste"})
assert resp.status_code == 200, resp.text

db = SessionLocal()

cfg = db.get(models.GlobalDispatchConfig, "global") or models.GlobalDispatchConfig(id="global")
cfg.schedule_days = "1,2,3,4,5,6,7"
cfg.schedule_start = "00:00"
cfg.schedule_end = "23:59"
cfg.batch_size = 50
cfg.interval_seconds = 0
db.add(cfg)

numero = models.WhatsappNumber(waba_id="waba1", phone_number_id="pn1", display_phone_number="5511900000000")
numero2 = models.WhatsappNumber(waba_id="waba1", phone_number_id="pn2", display_phone_number="5511900000001")
tpl = models.Template(
    name="cobranca", meta_template_name="cobranca", status=models.TemplateStatus.approved, body_text="Olá {{1}}, {{2}}"
)
tpl.variables = [
    models.TemplateVariable(position=1, internal_name="nome"),
    models.TemplateVariable(position=2, internal_name="valor"),
]
tpl2 = models.Template(
    name="lembrete", meta_template_name="lembrete", status=models.TemplateStatus.approved, body_text="Oi {{1}}"
)
tpl2.variables = [models.TemplateVariable(position=1, internal_name="nome")]
db.add_all([numero, numero2, tpl, tpl2])
db.flush()


def criar_faixa(nome: str, templates: list[tuple[models.WhatsappNumber, models.Template]]) -> models.Faixa:
    faixa = models.Faixa(name=nome, tipo=models.TIPO_REGUA)
    db.add(faixa)
    db.flush()
    for num, t in templates:
        envio = models.FaixaEnvio(faixa_id=faixa.id, whatsapp_number_id=num.id, template_id=t.id)
        envio.dispatch_config = models.DispatchConfig(active=True, interval_seconds=0, batch_size=50)
        db.add(envio)
        for v in t.variables:
            campo = {"nome": "primeiro_nome", "valor": "valor_em_aberto"}[v.internal_name]
            db.add(
                models.FaixaVariableMapping(
                    faixa_id=faixa.id, template_id=t.id, template_variable_id=v.id,
                    fonte_tipo="campo_cliente", column_name=campo,
                )
            )
    db.commit()
    db.refresh(faixa)
    return faixa


faixa_a = criar_faixa("11 A 20", [(numero, tpl)])
faixa_b = criar_faixa("21 A 30", [(numero2, tpl)])
faixa_dupla = criar_faixa("31 A 60", [(numero, tpl), (numero2, tpl2)])


def limpar() -> None:
    db.rollback()
    db.query(models.ErrorLog).delete()
    db.query(models.InvalidPhoneRecord).delete()
    db.query(models.QueueItem).delete()
    db.query(models.PausaEnvio).delete()
    db.query(models.ClienteBloqueado).delete()
    db.query(models.LeadParcela).delete()
    db.query(models.Lead).delete()
    db.commit()
    enviados.clear()
    modo_meta["resposta"] = "ok"


def item(faixa: models.Faixa, codigo: str, celular: str, **extra) -> models.QueueItem:
    dados = dict(
        faixa_id=faixa.id, codigo_cliente=codigo, nome="Ana", cpf="123.456.789-09", valor="100,00",
        celular=celular, celular_original=celular, variables_json={"nome": "Ana", "valor": "100,00"},
        status=models.QueueStatus.pending,
    )
    dados.update(extra)
    it = models.QueueItem(**dados)
    db.add(it)
    db.commit()
    return it


def ciclo() -> None:
    db.commit()
    asyncio.run(worker.run_dispatch_cycle())
    db.expire_all()


def status(it: models.QueueItem) -> models.QueueStatus:
    db.refresh(it)
    return it.status


def cliente(codigo: str, celular: str = "5511988887777", **extra) -> dict:
    c = {
        "codigo": codigo, "nome": "MARIA DA SILVA", "cpfcnpj": "12345678909", "valor_cobrar": "250.00",
        "valor_em_aberto": "250.00", "celular": celular, "faixa": "11 A 20", "lojas": ["1", "07"],
        "dias_atraso": 11, "vencimento_mais_antigo": date(2026, 9, 1),
    }
    c.update(extra)
    return c


# =============================================================================
print("=== 1. Fluxo básico: pendente → enviado ===")
limpar()
it = item(faixa_a, "00000001", "5511911110001")
ciclo()
assert status(it) == models.QueueStatus.sent, it.status
assert it.sent_at is not None and it.whatsapp_message_id == "wamid.1"
assert it.whatsapp_number_id == numero.id and it.reserved_by is not None
assert len(enviados) == 1 and enviados[0]["to"] == "5511911110001"
assert enviados[0]["template"]["name"] == "cobranca"
assert parametros(enviados[0]) == ["Ana", "100,00"]
ciclo()  # nada pendente: nada sai de novo
assert len(enviados) == 1

# =============================================================================
print("=== 2. Mesmo cliente em duas faixas: sai uma vez, a outra vira erro ===")
limpar()
i1 = item(faixa_a, "00000002", "5511911110002")
i2 = item(faixa_b, "00000002", "5511911110002")
ciclo()
estados = sorted([status(i1).value, status(i2).value])
assert estados == ["error", "sent"], estados
erro = i1 if i1.status == models.QueueStatus.error else i2
assert erro.error_message == "Cliente já cobrado hoje em outra faixa ou envio; não reenviado"
assert erro.sent_at is None
assert len(para("5511911110002")) == 1

# =============================================================================
print("=== 3. Blacklist entrou depois de o cliente estar na fila ===")
limpar()
it = item(faixa_a, "00000003", "5511911110003")
it_cpf = item(faixa_a, "00000033", "5511911110033", cpf="987.654.321-00")
db.add(models.ClienteBloqueado(tipo="seta", valor="00000003", motivo="teste"))
db.add(models.ClienteBloqueado(tipo="cpf", valor="98765432100", motivo="teste"))
db.commit()
ciclo()
assert status(it) == models.QueueStatus.error and it.error_message == "Cliente na blacklist; não enviado"
assert status(it_cpf) == models.QueueStatus.error
assert enviados == []

# =============================================================================
print("=== 4. Pausas: cliente, faixa e loja seguram o item pendente ===")
limpar()
p_cli = item(faixa_a, "00000004", "5511911110004")
p_fx = item(faixa_b, "00000005", "5511911110005")
p_loja = item(faixa_a, "00000006", "5511911110006", lojas=",01,07,")
livre = item(faixa_a, "00000007", "5511911110007", lojas=",02,")
db.add_all([
    models.PausaEnvio(escopo="cliente", valor="00000004", motivo="t"),
    models.PausaEnvio(escopo="faixa", valor=faixa_b.id, motivo="t"),
    models.PausaEnvio(escopo="loja", valor="07", motivo="t"),
    # vencida e encerrada não valem
    models.PausaEnvio(escopo="cliente", valor="00000007", motivo="t", ate=hoje_br() - timedelta(days=1)),
    models.PausaEnvio(escopo="loja", valor="02", motivo="t", encerrada_em=datetime.utcnow()),
])
db.commit()
ciclo()
assert [status(x) for x in (p_cli, p_fx, p_loja)] == [models.QueueStatus.pending] * 3
assert status(livre) == models.QueueStatus.sent
assert [e["to"] for e in enviados] == ["5511911110007"]
# Retomar: sai no ciclo seguinte
db.query(models.PausaEnvio).update({models.PausaEnvio.encerrada_em: datetime.utcnow()})
db.commit()
ciclo()
assert [status(x) for x in (p_cli, p_fx, p_loja)] == [models.QueueStatus.sent] * 3

# =============================================================================
print("=== 5. Parar: cancelado não sai e libera o cliente ===")
limpar()
it = item(faixa_a, "00000008", "5511911110008")
r = client.post("/pausas/parar", json={"escopo": "cliente", "valor": "8"})
assert r.status_code == 200 and r.json()["qtd"] == 1, r.text
ciclo()
assert status(it) == models.QueueStatus.cancelled and it.error_message.startswith("Envio parado por ")
assert enviados == []
assert "00000008" not in elegibilidade.clientes_bloqueados_hoje(db)

# =============================================================================
print("=== 6. Erro da Meta libera o cliente; falha incerta ocupa ===")
limpar()
modo_meta["resposta"] = "erro"
it = item(faixa_a, "00000009", "5511911110009")
ciclo()
assert status(it) == models.QueueStatus.error and it.sent_at is None
assert "número não tem WhatsApp" in it.error_message
assert db.query(models.ErrorLog).filter_by(queue_item_id=it.id).count() == 1
assert "00000009" not in elegibilidade.clientes_bloqueados_hoje(db)

modo_meta["resposta"] = "queda"
it2 = item(faixa_a, "00000010", "5511911110010")
ciclo()
assert status(it2) == models.QueueStatus.error and it2.sent_at is not None
assert it2.error_message.startswith("Falha inesperada ao enviar")
assert "00000010" in elegibilidade.clientes_bloqueados_hoje(db)
# 5xx da Meta: a mensagem pode ter saído, ocupa o cliente como a queda
modo_meta["resposta"] = "servidor"
it5 = item(faixa_a, "00000015", "5511911110015")
ciclo()
assert status(it5) == models.QueueStatus.error and it5.sent_at is not None
assert "00000015" in elegibilidade.clientes_bloqueados_hoje(db)
# e segura um segundo item do mesmo cliente no mesmo dia
modo_meta["resposta"] = "ok"
it3 = item(faixa_b, "00000010", "5511911110010")
ciclo()
assert status(it3) == models.QueueStatus.error
assert it3.error_message == "Cliente já cobrado hoje em outra faixa ou envio; não reenviado"
assert enviados == []

# =============================================================================
print("=== 7. clientes_bloqueados_hoje: quem ocupa o cliente ===")
limpar()
ontem = datetime.utcnow() - timedelta(days=2)
casos = {
    "00000011": dict(status=models.QueueStatus.pending),
    "00000012": dict(status=models.QueueStatus.reserved),
    "00000013": dict(status=models.QueueStatus.sent, sent_at=datetime.utcnow()),
    "00000014": dict(status=models.QueueStatus.error, sent_at=datetime.utcnow()),  # incerto
    "00000015": dict(status=models.QueueStatus.error),
    "00000016": dict(status=models.QueueStatus.cancelled),
    "00000017": dict(status=models.QueueStatus.sent, sent_at=ontem),
    "00000018": dict(status=models.QueueStatus.invalid_phone),
}
for codigo, extra in casos.items():
    item(faixa_a, codigo, "5511911119999", **extra)
assert elegibilidade.clientes_bloqueados_hoje(db) == {"00000011", "00000012", "00000013", "00000014"}
assert elegibilidade.cobrados_hoje(db) == {"00000013", "00000014"}

# =============================================================================
print("=== 8. enfileirar_clientes: bloqueio, telefone, variáveis e formato ===")
limpar()
item(faixa_b, "00000020", "5511911110020")  # já pendente em outra faixa
bloqueados = elegibilidade.clientes_bloqueados_hoje(db)
enfileirados: list[dict] = []
clientes = [
    cliente("00000020"),  # bloqueado
    cliente("00000021"),
    cliente("00000022", celular="1133334444"),  # fixo: pula sem item
    cliente("00000023", celular=None),  # sem telefone: pula
    cliente("00000024", valor_em_aberto=None),  # variável sem valor: item de erro
    cliente("00000021"),  # repetido na mesma lista: só o primeiro
]
total = fila_automatica.enfileirar_clientes(
    db, faixa_a, clientes, bloqueados=bloqueados, juros=None, parcelas={}, origem="no teste",
    enfileirados=enfileirados,
)
db.commit()
assert total == 1 and [c["codigo"] for c in enfileirados] == ["00000021"]
novos = {i.codigo_cliente: i for i in db.query(models.QueueItem).filter_by(faixa_id=faixa_a.id)}
assert set(novos) == {"00000021", "00000024"}, set(novos)
ok = novos["00000021"]
assert ok.status == models.QueueStatus.pending
assert ok.variables_json == {"nome": "Maria", "valor": "250,00"}, ok.variables_json
assert ok.nome == "Maria" and ok.cpf == "123.456.789-09" and ok.celular == "5511988887777"
assert ok.lojas == ",01,07," and ok.faixa_atraso == "11 A 20" and ok.valor == "250.00"
falta = novos["00000024"]
assert falta.status == models.QueueStatus.error
assert falta.error_message == "Variável sem valor no teste: valor"
assert {"00000021", "00000024"} <= bloqueados  # acrescenta quem entrou (inclusive com erro)

# faixa com dois templates ativos: variables_json por template
total = fila_automatica.enfileirar_clientes(
    db, faixa_dupla, [cliente("00000025", celular="5511966665555")], bloqueados=set(), juros=None, parcelas={}, origem="no teste"
)
db.commit()
dupla = db.query(models.QueueItem).filter_by(faixa_id=faixa_dupla.id).one()
assert total == 1
assert dupla.variables_json == {tpl.id: {"nome": "Maria", "valor": "250,00"}, tpl2.id: {"nome": "Maria"}}
# e o envio escolhe o dict do template do envio que reservou o item
ciclo()
assert status(dupla) == models.QueueStatus.sent
e = next(x for x in enviados if x["to"] == "5511966665555")
assert parametros(e) == (["Maria", "250,00"] if e["template"]["name"] == "cobranca" else ["Maria"])

# =============================================================================
print("=== 9. enfileirar_leads (extração automática) ===")
limpar()


def lead(codigo: str, faixa: str = "11 A 20", **extra) -> models.Lead:
    dados = dict(
        codigo_cliente=codigo, nome="JOAO PEREIRA", cpf="12345678909", celular="5511977776666",
        celular_original="11977776666", cluster="ESPECIAL", faixa=faixa, dias_atraso=11, qtd_parcelas=1,
        valor_cobrar="300.00", valor_em_aberto="300.00", vencimento_mais_antigo=date(2026, 9, 1),
        lojas=",03,", status="novo", created_by=None,
    )
    dados.update(extra)
    le = models.Lead(**dados)
    db.add(le)
    db.commit()
    return le


lead("00000030")
lead("00000031")
lead("00000032", celular="123")  # telefone inválido: fica só em Leads
lead("00000033", faixa="SEM FAIXA")  # faixa que não existe: ignorado
item(faixa_b, "00000031", "5511911110031", status=models.QueueStatus.sent, sent_at=datetime.utcnow())
base = [
    {"codigo": c, "faixa": f, "vencimento_mais_antigo": date(2026, 9, 1)}
    for c, f in (("00000030", "11 A 20"), ("00000031", "11 A 20"), ("00000032", "11 A 20"), ("00000033", "SEM FAIXA"))
]
assert fila_automatica.enfileirar_leads(db, base) == 1
it = db.query(models.QueueItem).filter_by(codigo_cliente="00000030").one()
assert it.faixa_id == faixa_a.id and it.status == models.QueueStatus.pending
assert it.variables_json == {"nome": "Joao", "valor": "300,00"}, it.variables_json
assert it.lojas == ",03," and it.faixa_atraso is None
assert db.query(models.QueueItem).filter_by(codigo_cliente="00000031").count() == 1  # só o enviado
assert fila_automatica.enfileirar_leads(db, base) == 0  # de novo: todos bloqueados

# Lead de outro dia com a mesma faixa e vencimento: a mensagem usa os dados da
# base de hoje e as parcelas atuais, não o retrato do dia em que o lead nasceu
limpar()
antigo = lead("00000034", created_at=datetime.utcnow() - timedelta(days=5), status="cobrado")
parcelas_seta = {"00000034": [{"titulo_codigo": "T9", "empresa": "01", "vencimento": date(2026, 9, 1),
                               "valor": Decimal("120.00"), "valor_cobrar": Decimal("120.00")}]}
original_parcelas = fila_automatica.seta_client.buscar_parcelas_cobranca
fila_automatica.seta_client.buscar_parcelas_cobranca = lambda codigos, juros=None: parcelas_seta
try:
    hoje_base = [{
        "codigo": "00000034", "nome": "JOAO PEREIRA", "cpfcnpj": "12345678909", "celular": "5511977776666",
        "cluster": "ESPECIAL", "faixa": "11 A 20", "dias_atraso": 15, "qtd_parcelas_cobranca": 1,
        "valor_em_aberto": Decimal("120.00"), "valor_cobrar": Decimal("120.00"),
        "vencimento_mais_antigo": date(2026, 9, 1), "lojas": ["03"],
    }]
    assert fila_automatica.enfileirar_leads(db, hoje_base) == 1
finally:
    fila_automatica.seta_client.buscar_parcelas_cobranca = original_parcelas
it = db.query(models.QueueItem).filter_by(codigo_cliente="00000034").one()
assert it.variables_json == {"nome": "Joao", "valor": "120,00"}, it.variables_json
assert it.valor == "120.00"
db.refresh(antigo)
assert antigo.valor_cobrar == Decimal("300.00") and antigo.parcelas == []  # o lead não muda

# =============================================================================
print("=== 10. Upload de planilha na faixa ===")
limpar()


def planilha(linhas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Codigo", "Nome", "CPF", "Celular", "Valor"])
    for linha in linhas:
        ws.append(linha)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


item(faixa_b, "00000040", "5511911110040")  # pendente em outra faixa
db.add(models.ClienteBloqueado(tipo="seta", valor="00000041", motivo="t"))
db.commit()
lead("00000043", lojas=",05,")  # tem Lead na faixa, com loja
conteudo = planilha([
    ["40", "Bia Souza", "11122233344", "11911110040", "10,00"],  # já na fila hoje
    ["41", "Caio Lima", "11122233345", "11911110041", "20,00"],  # blacklist
    ["42", "Dani Reis", "11122233346", "1133334444", "30,00"],  # fixo → telefone inválido
    ["43", "Edu Melo", "11122233347", "11911110043", "40,00"],
    ["44", "Fabi Luz", "11122233348", "11911110044", ""],  # variável sem valor
    ["43", "Edu Melo", "11122233347", "11911110043", "40,00"],  # repetida
])
vars_ = {v.internal_name: v.id for v in tpl.variables}
mapeamento = {
    "celular": "Celular", "codigo_cliente": "Codigo", "nome": "Nome", "cpf": "CPF", "valor": "Valor",
    "variables": {vars_["nome"]: "Nome", vars_["valor"]: "Valor"},
}
r = client.post(
    f"/faixas/{faixa_a.id}/uploads",
    files={"file": ("clientes.xlsx", conteudo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    data={"mapping": json.dumps(mapeamento)},
)
assert r.status_code == 200, r.text
res = r.json()
assert res["row_count"] == 6 and res["invalid_phone_count"] == 1, res
assert res["accepted_count"] == 1 and res["rejected_count"] == 5, res
motivos = " | ".join(res["rejected_reasons"])
assert "Linha 2: cliente já está na fila ou já foi cobrado hoje" in motivos
assert "Linha 3: cliente na blacklist" in motivos
assert "Linha 7: cliente já está na fila ou já foi cobrado hoje" in motivos  # repetida
itens = {i.codigo_cliente: i for i in db.query(models.QueueItem).filter_by(faixa_id=faixa_a.id)}
assert set(itens) == {"00000043", "00000044"}, set(itens)
assert itens["00000043"].status == models.QueueStatus.pending
# Coluna de valor ligada a uma variável usa o valor em atraso com juros do
# Lead da faixa; Lead sem parcelas (valor zerado) cai no valor da planilha.
assert itens["00000043"].variables_json == {"nome": "Edu", "valor": "40,00"}, itens["00000043"].variables_json
# Lojas vêm do Lead do cliente; sem Lead ficam "," (pausa por loja não pega)
assert itens["00000043"].lojas == ",05,"
assert itens["00000044"].lojas == ","
assert itens["00000044"].status == models.QueueStatus.error
assert itens["00000044"].error_message.startswith("Faltando coluna(s)")
assert db.query(models.InvalidPhoneRecord).filter_by(codigo_cliente="00000042").count() == 1

# Valor zerado não entra: volta para o usuário escolher um valor do sistema
# ou descartar. Texto com número vira número ("1 500,00", "10,00 reais").
limpar()
le = lead("00000060")  # cadastro com valor em aberto e parcela vencida
db.add(models.LeadParcela(lead_id=le.id, titulo_codigo="T1", empresa="01", vencimento=date(2026, 9, 1),
                          valor=Decimal("150.00"), valor_cobrar=Decimal("150.00")))
db.commit()
conteudo = planilha([
    ["60", "Gil Dias", "11122233360", "11911110060", "0,00"],  # zerado com cadastro
    ["61", "Hana Sá", "11122233361", "11911110061", "R$ 0,00"],  # zerado sem cadastro
    ["62", "Ivo Paz", "11122233362", "11911110062", "1 500,00"],
    ["63", "Jó Reis", "11122233363", "11911110063", "10,00 reais"],
    ["64", "Kai Luz", "11122233364", "11911110064", "US$ 50"],
    ["61", "Hana Sá", "11122233361", "11911110061", "0"],  # repetida
])
r = client.post(
    f"/faixas/{faixa_a.id}/uploads",
    files={"file": ("zerados.xlsx", conteudo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    data={"mapping": json.dumps(mapeamento)},
)
assert r.status_code == 200, r.text
res = r.json()
assert res["accepted_count"] == 3 and res["rejected_count"] == 0, res
zerados = {z["codigo_cliente"]: z for z in res["valores_zerados"]}
assert set(zerados) == {"00000060", "00000061"}, zerados
assert zerados["00000060"]["linha"] == 2 and zerados["00000060"]["dados"]["Valor"] == "0,00"
opcoes = {o["campo"]: o["valor"] for o in zerados["00000060"]["opcoes"]}
assert opcoes["valor_em_aberto"] == "300,00" and opcoes["valor_atraso"] not in ("", "0,00"), opcoes
assert zerados["00000061"]["opcoes"] == []
itens = {i.codigo_cliente: i for i in db.query(models.QueueItem).filter_by(faixa_id=faixa_a.id)}
assert set(itens) == {"00000062", "00000063", "00000064"}, set(itens)
assert [itens[c].variables_json["valor"] for c in ("00000062", "00000063", "00000064")] == ["1.500,00", "10,00", "50,00"]
assert itens["00000062"].valor == "1.500,00"

# Valor escolhido para o 60; o 61 foi descartado (não vem)
url = f"/faixas/{faixa_a.id}/uploads/valores-zerados"
escolha = {"linha": 2, "dados": zerados["00000060"]["dados"], "valor": opcoes["valor_atraso"]}
r = client.post(url, json={"filename": "zerados.xlsx", "mapping": mapeamento, "linhas": [{**escolha, "valor": "0"}]})
assert r.status_code == 400, r.text
r = client.post(url, json={"filename": "zerados.xlsx", "mapping": mapeamento, "linhas": [escolha]})
assert r.status_code == 200, r.text
assert r.json()["accepted_count"] == 1 and r.json()["valores_zerados"] == [], r.json()
it = db.query(models.QueueItem).filter_by(codigo_cliente="00000060").one()
assert it.status == models.QueueStatus.pending and it.variables_json["valor"] == opcoes["valor_atraso"]
assert db.query(models.QueueItem).filter_by(codigo_cliente="00000061").count() == 0
# De novo: já está na fila hoje
r = client.post(url, json={"filename": "zerados.xlsx", "mapping": mapeamento, "linhas": [escolha]})
assert r.json()["accepted_count"] == 0 and "Linha 2: cliente já está na fila" in r.json()["rejected_reasons"][0]

# Expressão com texto em volta do valor: o valor escolhido entra nela também,
# e "-50" conta como zerado
limpar()
com_expressao = {**mapeamento, "variables": {vars_["nome"]: "Nome"}, "expressoes": {vars_["valor"]: "{Valor} à vista"}}
conteudo = planilha([
    ["65", "Lia Mota", "11122233365", "11911110065", "0,00"],
    ["66", "Max Reis", "11122233366", "11911110066", "-50"],
])
r = client.post(
    f"/faixas/{faixa_a.id}/uploads",
    files={"file": ("expr.xlsx", conteudo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    data={"mapping": json.dumps(com_expressao)},
)
assert r.status_code == 200, r.text
zerados = {z["codigo_cliente"]: z for z in r.json()["valores_zerados"]}
assert set(zerados) == {"00000065", "00000066"}, r.json()
r = client.post(url, json={"filename": "expr.xlsx", "mapping": com_expressao,
                           "linhas": [{"linha": 2, "dados": zerados["00000065"]["dados"], "valor": "300"}]})
assert r.status_code == 200 and r.json()["accepted_count"] == 1, r.text
it = db.query(models.QueueItem).filter_by(codigo_cliente="00000065").one()
assert it.variables_json == {"nome": "Lia", "valor": "300,00 à vista"}, it.variables_json

# Leitura de valor escrito de vários jeitos
from app.upload_service import ler_valor

for texto, esperado in [
    ("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("R$ 10", "10"), ("1 500,00", "1500.00"),
    ("10,00 reais", "10.00"), ("US$ 50", "50"), ("1.500", "1500"), ("1500.0", "1500.0"),
    ("1,234.56", "1234.56"), ("0,00", "0.00"), (",50", "0.50"), ("0.500", "0.500"), ("-50", "-50"), ("R$\u00a01\u00a0500,50", "1500.50"),
]:
    assert ler_valor(texto) == Decimal(esperado), (texto, ler_valor(texto))
assert ler_valor("") is None and ler_valor("sem valor") is None

# =============================================================================
print("=== 11. expirar_nao_enviados ===")
limpar()
antes = datetime.utcnow() - timedelta(days=2)
velho = item(faixa_a, "00000050", "5511911110050", created_at=antes)
reservado = item(faixa_a, "00000051", "5511911110051", created_at=antes, status=models.QueueStatus.reserved)
novo = item(faixa_a, "00000052", "5511911110052")
enviado = item(faixa_a, "00000053", "5511911110053", created_at=antes, status=models.QueueStatus.sent, sent_at=antes)
lead("00000054", created_at=antes)  # lead da extração automática não cobrado
lead("00000055", created_at=antes, created_by=db.query(models.User).first().id)  # lead manual fica
ids = id_velho, id_reservado, id_novo, id_enviado = (velho.id, reservado.id, novo.id, enviado.id)
assert fila_automatica.expirar_nao_enviados(db, cfg, datetime.utcnow()) == (1, 1)
db.expire_all()
restantes = {i.id: i for i in db.query(models.QueueItem).filter(models.QueueItem.id.in_(ids))}
assert id_velho not in restantes
assert restantes[id_reservado].status == models.QueueStatus.error
assert restantes[id_reservado].error_message.startswith("Envio interrompido")
assert restantes[id_novo].status == models.QueueStatus.pending
assert restantes[id_enviado].status == models.QueueStatus.sent
assert {l.codigo_cliente for l in db.query(models.Lead)} == {"00000055"}

# =============================================================================
print("=== 12. Número desativado não envia; variável vazia não chama a Meta ===")
limpar()
numero2.active = False
db.commit()
parado = item(faixa_b, "00000070", "5511911110070")
ciclo()
assert status(parado) == models.QueueStatus.pending and enviados == []
numero2.active = True
db.commit()
sem_valor = item(faixa_a, "00000071", "5511911110071", variables_json={"nome": "Ana"})
ciclo()
assert status(sem_valor) == models.QueueStatus.error, sem_valor.error_message
assert sem_valor.error_message == "Variável sem valor para o template cobranca: valor"
assert para("5511911110071") == [] and sem_valor.sent_at is None
assert status(parado) == models.QueueStatus.sent  # número de volta: sai

db.close()
client.__exit__(None, None, None)
print("OK")
