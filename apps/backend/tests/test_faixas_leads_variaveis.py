"""Testes para o catálogo de dados de lead do sistema, resolução de variáveis e importação de leads para a fila da faixa."""

import os
import tempfile
from datetime import date, datetime
from decimal import Decimal

os.environ["MEDIA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient

import app.variaveis_template as vt
from app import models, schemas

# 1. Validação de catálogo de campos e contexto_cliente
def test_catalogo_campos_cliente_completo():
    campos_essenciais = [
        "primeiro_nome",
        "nome",
        "valor_cobrar",
        "vencimento",
        "dias_atraso",
        "valor_em_aberto",
        "qtd_parcelas",
        "codigo",
        "cpf",
        "celular",
        "cluster",
        "faixa",
        "salario",
        "limite_rotativo",
        "loja_cadastro",
        "lojas",
        "qtd_compras",
        "faixa_compra",
        "spc_restricao",
        "spc_data_consulta",
        "status_cliente",
        "valor_pago",
        "qtd_titulos",
    ]
    for c in campos_essenciais:
        assert c in vt.CAMPOS_CLIENTE, f"Campo {c} deveria estar em CAMPOS_CLIENTE"

    assert vt.CAMPOS_CLIENTE["valor_cobrar"] == "Valor total com cálculo de juros"
    assert vt.CAMPOS_CLIENTE["dias_atraso"] == "Dias em atraso (maior atraso)"
    assert vt.CAMPOS_CLIENTE["vencimento"] == "Vencimento da parcela mais antiga"
    assert vt.CAMPOS_CLIENTE["primeiro_nome"] == "Primeiro nome"


def test_contexto_cliente_formatacao():
    dados = {
        "codigo": "123456",
        "nome": "Maria da Silva Santos",
        "cpfcnpj": "12345678901",
        "celular": "5511999998888",
        "cluster": "ESPECIAL",
        "faixa": "11 A 20",
        "dias_atraso": 15,
        "qtd_parcelas_cobranca": 2,
        "valor_cobrar": Decimal("1234.56"),
        "valor_em_aberto": Decimal("1200.00"),
        "vencimento_mais_antigo": date(2026, 9, 21),
        "salario": Decimal("2500.00"),
        "limite_rotativo": Decimal("1000.00"),
        "valor_pago": Decimal("4800.00"),
        "loja_cadastro": "49",
        "lojas": ["49", "12"],
        "qtd_compras": 12,
        "faixa_compra": "10+",
        "spc_restricao": "nao",
        "spc_data_consulta": date(2026, 8, 15),
        "status_cliente": "Ativo",
        "qtd_titulos": 3,
    }

    ctx = vt.contexto_cliente(dados)
    assert ctx["primeiro_nome"] == "Maria"
    assert ctx["nome"] == "Maria da Silva Santos"
    assert ctx["valor_cobrar"] == "R$ 1.234,56"
    assert ctx["valor_em_aberto"] == "R$ 1.200,00"
    assert ctx["vencimento"] == "21/09/2026"
    assert ctx["dias_atraso"] == "15"
    assert ctx["codigo"] == "00123456"
    assert ctx["cpf"] == "123.456.789-01"
    assert ctx["salario"] == "R$ 2.500,00"
    assert ctx["limite_rotativo"] == "R$ 1.000,00"
    assert ctx["lojas"] == "49, 12"
    assert ctx["qtd_compras"] == "12"
    assert ctx["spc_restricao"] == "nao"
    assert ctx["spc_data_consulta"] == "15/08/2026"
    assert ctx["status_cliente"] == "Ativo"


def test_resolver_variaveis_com_dados_lead():
    dados = {
        "codigo": "123456",
        "nome": "Carlos Drummond de Andrade",
        "cpf": "12345678901",
        "celular": "5511999998888",
        "valor_cobrar": Decimal("450.75"),
        "vencimento": date(2026, 9, 10),
        "dias_atraso": 12,
    }
    ctx = vt.contexto_cliente(dados)

    fontes = [
        vt.FonteVariavel(nome_interno="nome", tipo="campo_cliente", valor="primeiro_nome"),
        vt.FonteVariavel(nome_interno="total", tipo="campo_cliente", valor="valor_cobrar"),
        vt.FonteVariavel(nome_interno="venc", tipo="campo_cliente", valor="vencimento"),
        vt.FonteVariavel(nome_interno="atraso", tipo="campo_cliente", valor="dias_atraso"),
    ]

    res = vt.resolver_variaveis(fontes, ctx)
    assert res["nome"] == "Carlos"
    assert res["total"] == "R$ 450,75"
    assert res["venc"] == "10/09/2026"
    assert res["atraso"] == "12"


if __name__ == "__main__":
    test_catalogo_campos_cliente_completo()
    test_contexto_cliente_formatacao()
    test_resolver_variaveis_com_dados_lead()
    print("TODOS OS TESTES UNITARIOS PASSARAM COM SUCESSO!")
