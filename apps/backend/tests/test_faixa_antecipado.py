"""Faixa só de campanhas ("Antecipado", clientes antes do vencimento):
1. Fica fora da matriz do WhatsApp e do "todas as faixas" (rotina diária,
   Cobrança, régua pós-campanha); só a campanha que a pede consulta esses dias.
2. A campanha com Antecipado traz quem está em dia; o lembrete continua fora.
3. Antecipado fica sozinho na campanha, sem filtro nem variável de valor em atraso.
4. Campo de template "Valor da próxima parcela".

Sem banco: regras, SETA e cache são substituídos.
"""

import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-faixa-antecipado-123456")
os.environ.setdefault("ADMIN_PASSWORD", "senha-admin-teste-antecipado")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_antecipado")

from app import campanhas, cobranca_base
from app.cobranca_regras import REGRAS_PADRAO, FaixaAtraso, Regras
from app.timezone import hoje_br
from app.variaveis_template import contexto_cliente

REGRAS = Regras(
    clusters=REGRAS_PADRAO.clusters,
    faixas=(FaixaAtraso("Antecipado", -365, -2, so_campanhas=True),) + REGRAS_PADRAO.faixas,
    # mesmo marcada na matriz, a faixa só de campanhas não entra no WhatsApp
    whatsapp=REGRAS_PADRAO.whatsapp | {("ESPECIAL", "Antecipado")},
    juros=REGRAS_PADRAO.juros,
)

print("1. Regras")
assert REGRAS.nomes_faixa[0] == "Antecipado"
assert "Antecipado" not in REGRAS.nomes_faixa_regua
assert REGRAS.nomes_faixa_so_campanhas == ["Antecipado"]
assert REGRAS.faixa_por_dias(-30) == "Antecipado" and REGRAS.faixa_por_dias(-1) == "-1"
assert not REGRAS.entra_no_whatsapp("ESPECIAL", "Antecipado")
assert "Antecipado" not in REGRAS.faixas_whatsapp("ESPECIAL")
print("  OK")


def _linha(codigo: str, dias: int) -> dict:
    return {
        "codigo": codigo, "nome": "CLIENTE " + codigo, "telefone2": "63999990000", "telefone1": None,
        "telefone3": None, "telefone4": None, "cpfcnpj": "12345678901", "status": "A", "loja_cadastro": "01",
        "salario": None, "limite_rotativo": None, "nascimento": None, "cadastro": None, "spc_restricao": "nao",
        "dias_atraso": dias, "qtd_titulos": 1, "valor_em_aberto": Decimal("100"), "qtd_parcelas_cobranca": 1,
        "valor_cobrar": Decimal("100"), "valor_atraso_original": Decimal("0"), "valor_atraso_juros": Decimal("0"),
        "vencimento_mais_antigo": hoje_br() - timedelta(days=dias), "lojas": "01", "portadores": "", "valor_pago": 0,
    }


LINHAS = [_linha("00000001", -30), _linha("00000002", -1), _linha("00000003", 5)]
pedidos: list[dict] = []


def _seta(**kwargs):
    pedidos.append(kwargs)
    return LINHAS


def _buscar(**kwargs):
    pedidos.clear()
    with (
        patch("app.cobranca_base.carregar_regras", return_value=REGRAS),
        patch("app.cobranca_base.codigos_bloqueados", return_value=([], [])),
        patch("app.cobranca_base.compras_seta.obter", return_value={}),
        patch("app.cobranca_base.cache.buscar_ou_iniciar", side_effect=lambda chave, fn: {"status": "ready", "data": fn()}),
        patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta),
    ):
        return cobranca_base.buscar_base(MagicMock(), **kwargs)


print("2. Base de cobrança")
_buscar(apenas_primeiro_dia=False, somente_regra_whatsapp=False)
assert (-365, -2) not in pedidos[0]["faixas"], "sem pedir faixa, o Antecipado não vai ao SETA"
_buscar()
assert (-365, -2) not in pedidos[0]["faixas"], "rotina diária (matriz) não pede o Antecipado"
try:
    _buscar(apenas_primeiro_dia=False, somente_regra_whatsapp=False, faixas=["Antecipado"])
    raise AssertionError("Cobrança não pode pedir a faixa só de campanhas")
except cobranca_base.FiltroInvalido:
    pass
job = _buscar(apenas_primeiro_dia=False, somente_regra_whatsapp=False, faixas=["Antecipado"], incluir_so_campanhas=True)
assert pedidos[0]["faixas"] == [(-365, -2)]
assert {c["codigo"]: c["faixa"] for c in job["data"]}["00000001"] == "Antecipado"
print("  OK")

print("3. Seleção da campanha")
base = {"status": "ready", "data": [{"codigo": l["codigo"], "dias_atraso": l["dias_atraso"], "faixa": REGRAS.faixa_por_dias(l["dias_atraso"])} for l in LINHAS]}
campanha = SimpleNamespace(filtros={"faixa": ["Antecipado"]}, clientes=[])
with (
    patch("app.campanhas.carregar_regras", return_value=REGRAS),
    patch("app.campanhas.filtros_para_busca", return_value={}),
    patch("app.campanhas.cobranca_base.buscar_base", return_value=base),
    patch("app.campanhas.ja_receberam", return_value=set()),
):
    selecao = campanhas.selecionar(MagicMock(), campanha)
# em dia (Antecipado) e em atraso entram; o lembrete (-1) não
assert [c["codigo"] for c in selecao["clientes"]] == ["00000001", "00000003"], selecao
print("  OK")

print("4. Antecipado sozinho e sem valor em atraso")


def _erro(faixas, valor_atraso=False, mapeamentos=()):
    with patch("app.campanhas.carregar_regras", return_value=REGRAS):
        return campanhas.erro_faixa_so_campanhas(MagicMock(), faixas, valor_atraso=valor_atraso, mapeamentos=mapeamentos)


campo = lambda tipo, coluna=None, expressao=None: SimpleNamespace(fonte_tipo=tipo, column_name=coluna, expressao=expressao)
assert _erro(["3 A 10"], valor_atraso=True, mapeamentos=[campo("campo_cliente", "valor_atraso")]) is None
assert _erro(["Antecipado"], mapeamentos=[campo("campo_cliente", "valor_proxima_parcela")]) is None
assert "combinada" in _erro(["Antecipado", "3 A 10"])
assert "valor em atraso" in _erro(["Antecipado"], valor_atraso=True)
assert "Valor em atraso" in _erro(["Antecipado"], mapeamentos=[campo("campo_cliente", "valor_atraso")])
assert "Valor em atraso" in _erro(["Antecipado"], mapeamentos=[campo("expressao", expressao="R$ {valor_atraso}")])
print("  OK")

print("5. Valor da próxima parcela")
hoje = hoje_br()
parcelas = [
    {"vencimento": hoje - timedelta(days=1), "valor": Decimal("5")},
    {"vencimento": hoje + timedelta(days=9), "valor": Decimal("100.50")},
    {"vencimento": hoje + timedelta(days=9), "valor": Decimal("10")},
    {"vencimento": hoje + timedelta(days=40), "valor": Decimal("7")},
]
assert contexto_cliente({"parcelas": parcelas})["valor_proxima_parcela"] == "110,50"
assert contexto_cliente({"parcelas": parcelas[:1]})["valor_proxima_parcela"] == ""
print("  OK")

print("OK")
