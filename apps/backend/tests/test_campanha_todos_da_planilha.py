"""Campanha com "Todos os clientes da planilha" e "Incluir quem já recebeu mensagem hoje":
1. Faixa de cada cliente: em atraso fica na faixa de atraso, 1 dia (sem faixa) vai
   para a faixa "1", e quem não está em atraso vai para a faixa só de campanhas.
2. A base pede ao SETA todos os dias (vencidos ou não) só com a planilha.
3. Seleção: entra todo cliente da planilha com parcela em aberto, inclusive o lembrete.
4. Validação: sem filtro de faixa nem de valor em atraso, sem variável "Valor em atraso".
5. Fora da regra do dia: entra sem olhar quem já foi cobrado hoje e sai mesmo assim.

Sem banco: regras, SETA e cache são substituídos.
"""

import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-campanha-todos-123456")
os.environ.setdefault("ADMIN_PASSWORD", "senha-admin-teste-campanha-todos")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_campanha_todos")

from app import campanhas, cobranca_base, elegibilidade
from app.cobranca_regras import REGRAS_PADRAO, FaixaAtraso, Regras
from app.timezone import hoje_br

# Faixas como as de produção: nenhuma cobre 0 nem 1 dia de atraso
FAIXAS = (
    FaixaAtraso("-1", -1, -1),
    FaixaAtraso("2", 2, 2),
    FaixaAtraso("3 A 10", 3, 10),
    FaixaAtraso("41 A 60", 41, 60),
    FaixaAtraso("151+", 151, None),
)
REGRAS = Regras(
    clusters=REGRAS_PADRAO.clusters,
    faixas=(FaixaAtraso("Antecipado", -365, -2, so_campanhas=True),) + FAIXAS,
    whatsapp=frozenset(),
    juros=REGRAS_PADRAO.juros,
)
SEM_SO_CAMPANHAS = Regras(clusters=REGRAS_PADRAO.clusters, faixas=FAIXAS, whatsapp=frozenset(), juros=REGRAS_PADRAO.juros)

print("1. Faixa na campanha")
assert campanhas.faixa_na_campanha(REGRAS, 5) == "3 A 10"
assert campanhas.faixa_na_campanha(REGRAS, 200) == "151+"
assert campanhas.faixa_na_campanha(REGRAS, 20) == "20", "dia sem faixa cadastrada vira faixa só com ele"
assert campanhas.faixa_na_campanha(REGRAS, 1) == "1"
assert campanhas.faixa_na_campanha(REGRAS, 0) == "Antecipado"
assert campanhas.faixa_na_campanha(REGRAS, -1) == "Antecipado", "o lembrete (-1) não fica na faixa da régua"
assert campanhas.faixa_na_campanha(REGRAS, -30) == "Antecipado"
assert campanhas.faixa_na_campanha(REGRAS, -800) == "Antecipado", "vencimento depois do fim do Antecipado"
assert campanhas.faixa_na_campanha(SEM_SO_CAMPANHAS, -30) is None
COM_FAIXA_1 = Regras(
    clusters=REGRAS_PADRAO.clusters,
    faixas=REGRAS.faixas + (FaixaAtraso("1", 1, 1),),
    whatsapp=frozenset(),
    juros=REGRAS_PADRAO.juros,
)
assert campanhas.faixa_na_campanha(COM_FAIXA_1, 1) == "1", "com a faixa 1 cadastrada (migration e6b2d8f4a1c7)"
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


LINHAS = [_linha("00000001", -30), _linha("00000002", -1), _linha("00000003", 0), _linha("00000004", 1), _linha("00000005", 45)]
pedidos: list[dict] = []


def _buscar(**kwargs):
    pedidos.clear()

    def seta(**k):
        pedidos.append(k)
        return LINHAS

    with (
        patch("app.cobranca_base.carregar_regras", return_value=REGRAS),
        patch("app.cobranca_base.codigos_bloqueados", return_value=([], [])),
        patch("app.cobranca_base.compras_seta.obter", return_value={}),
        patch("app.cobranca_base.cache.buscar_ou_iniciar", side_effect=lambda chave, fn: {"status": "ready", "data": fn()}),
        patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=seta),
    ):
        return cobranca_base.buscar_base(MagicMock(), **kwargs)


print("2. Base com todos os dias")
_buscar(apenas_primeiro_dia=True, somente_regra_whatsapp=False, todos_os_dias=True, codigos=["00000001"])
assert pedidos[0]["faixas"] == [cobranca_base.TODOS_OS_DIAS] and pedidos[0]["dias_exatos"] is None
with patch("app.campanhas.lojas_base.combinar_lojas", return_value=None):
    args = campanhas.filtros_para_busca(MagicMock(), {}, ["00000001"], todos_da_planilha=True)
    assert args["todos_os_dias"] is True
    args = campanhas.filtros_para_busca(MagicMock(), {}, [], todos_da_planilha=True)
    assert args["todos_os_dias"] is False, "sem planilha, a opção não vale"
print("  OK")

print("3. Seleção da campanha")
job = _buscar(apenas_primeiro_dia=False, somente_regra_whatsapp=False, todos_os_dias=True, codigos=[l["codigo"] for l in LINHAS])


def _selecionar(campanha):
    with (
        patch("app.campanhas.carregar_regras", return_value=REGRAS),
        patch("app.campanhas.filtros_para_busca", return_value={}),
        patch("app.campanhas.cobranca_base.buscar_base", return_value=job),
        patch("app.campanhas.ja_receberam", return_value={"00000005"}),
    ):
        return campanhas.selecionar(MagicMock(), campanha)


planilha = [l["codigo"] for l in LINHAS]
todos = _selecionar(SimpleNamespace(filtros={}, clientes=planilha, todos_da_planilha=True, incluir_cobrados_hoje=False, faixa=SimpleNamespace(variable_mappings=[]), planilha_linhas={c: {} for c in planilha}))
assert {c["codigo"]: c["faixa"] for c in todos["clientes"]} == {
    "00000001": "Antecipado",
    "00000002": "Antecipado",
    "00000003": "Antecipado",
    "00000004": "1",
}, todos
assert todos["total_base"] == 5, "quem já recebeu da campanha conta na base, mas não entra"
so_atraso = _selecionar(SimpleNamespace(filtros={}, clientes=planilha, todos_da_planilha=False, incluir_cobrados_hoje=False, faixa=SimpleNamespace(variable_mappings=[]), planilha_linhas={c: {} for c in planilha}))
assert {c["codigo"] for c in so_atraso["clientes"]} == {"00000001", "00000004"}, "sem a opção, nada muda"
print("  OK")

print("4. Validação")
campo = lambda tipo, coluna=None, expressao=None: SimpleNamespace(fonte_tipo=tipo, column_name=coluna, expressao=expressao)


def _erro(faixas=(), valor_atraso=False, mapeamentos=(), regras=REGRAS):
    with patch("app.campanhas.carregar_regras", return_value=regras):
        return campanhas.erro_todos_da_planilha(MagicMock(), list(faixas), valor_atraso=valor_atraso, mapeamentos=mapeamentos)


assert _erro(mapeamentos=[campo("campo_cliente", "primeiro_nome")]) is None
assert "faixa" in _erro(faixas=["3 A 10"])
assert "valor em atraso" in _erro(valor_atraso=True)
assert "Valor em atraso" in _erro(mapeamentos=[campo("expressao", expressao="R$ {valor_atraso}")])
assert "Antecipado" in _erro(regras=SEM_SO_CAMPANHAS)
print("  OK")

print("5. Fora da regra de uma mensagem por dia")
with (
    patch("app.campanhas.travar_entrada_na_fila") as travar,
    patch("app.campanhas.clientes_bloqueados_hoje", return_value={"00000009"}),
):
    assert campanhas._bloqueados(MagicMock(), SimpleNamespace(incluir_cobrados_hoje=True)) == set()
    assert travar.called, "continua travando a entrada na fila"
    assert campanhas._bloqueados(MagicMock(), SimpleNamespace(incluir_cobrados_hoje=False)) == {"00000009"}

item = SimpleNamespace(codigo_cliente="00000001", cpf="123", faixa_id="f1", id="i1")
blacklist = SimpleNamespace(contem=lambda codigo, cpf: False)
retencao = SimpleNamespace(retido=lambda item: False)
with (
    patch("app.elegibilidade.Retencao.carregar", return_value=retencao),
    patch("app.elegibilidade.ja_cobrado_hoje", return_value=True),
):
    with patch("app.elegibilidade.fora_da_regra_do_dia", return_value=True):
        assert elegibilidade.conferir_saida(MagicMock(), item, blacklist) is None
    with patch("app.elegibilidade.fora_da_regra_do_dia", return_value=False):
        assert "já cobrado hoje" in elegibilidade.conferir_saida(MagicMock(), item, blacklist)
print("  OK")

print("OK")
