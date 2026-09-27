"""Cria um SETA falso (mesmas tabelas/colunas que app/seta_client.py lê) num
Postgres local e popula com clientes fictícios. Nunca aponte para o SETA real.

Uso: python seta_falso.py postgresql://crm:crm@localhost:5432/seta_fake
"""

import random
import sys
from datetime import date, timedelta

import psycopg

DDL = """
DROP TABLE IF EXISTS financeiro_titulos, pessoas, vendas, condicoes, caixa_lotes;
CREATE TABLE pessoas (
    codigo char(8) PRIMARY KEY, nome char(60), telefone1 char(20), telefone2 char(20),
    telefone3 char(20), cpfcnpj char(18), status char(1), empresa char(2),
    faturamento numeric(14,2), credito numeric(14,2), nascimento date, cadastro date,
    scpcresultado text, cliente boolean DEFAULT true
);
CREATE TABLE financeiro_titulos (
    codigo char(10) PRIMARY KEY, pessoa char(8), valor numeric(14,2), vencimento date,
    empresa char(2), portador char(3), rp char(1), status char(1), tipo char(1),
    auxiliar char(10), descricao char(40), pagamento date, valorpago numeric(14,2),
    documento char(10), lote char(10), emissao date
);
CREATE INDEX ON financeiro_titulos (pessoa);
-- lote do caixa: horário da baixa feita na loja (títulos daqui ficam sem lote)
CREATE TABLE caixa_lotes (codigo char(10) PRIMARY KEY, datahora timestamp);
CREATE TABLE condicoes (codigo char(3) PRIMARY KEY, tipo char(1));
CREATE TABLE vendas (codigo char(8) PRIMARY KEY, cliente char(8), data date, status char(1), condicoes char(3));
"""

NOMES = [
    "MARIA APARECIDA SILVA", "JOSE CARLOS SOUZA", "ANA PAULA OLIVEIRA", "JOAO PEDRO SANTOS",
    "FRANCISCA LIMA", "ANTONIO PEREIRA", "ADRIANA COSTA", "CARLOS EDUARDO ALVES",
    "JULIANA RODRIGUES", "PAULO HENRIQUE GOMES", "FERNANDA RIBEIRO", "LUCAS MARTINS",
    "PATRICIA CARVALHO", "MARCOS VINICIUS ROCHA", "ALINE FERREIRA", "RAFAEL ARAUJO",
    "CAMILA MELO", "BRUNO BARBOSA", "LETICIA CARDOSO", "DIEGO TEIXEIRA",
    "BEATRIZ CORREIA", "GUSTAVO DIAS", "LARISSA MOREIRA", "RODRIGO NUNES",
    "VANESSA MENDES", "FELIPE CASTRO", "SIMONE PINTO", "THIAGO RAMOS",
    "RENATA FREITAS", "LEANDRO MONTEIRO", "CLAUDIA VIEIRA", "EDUARDO LOPES",
    "SANDRA MACHADO", "VINICIUS BATISTA", "DEBORA CAMPOS", "MATEUS REIS",
]
# dias de atraso escolhidos para cobrir as faixas padrão (inclusive o 1º dia de cada uma)
DIAS = [-1, 0, 1, 2, 3, 5, 10, 11, 15, 21, 25, 31, 35, 41, 50, 61, 70, 81, 90, 101,
        110, 121, 130, 141, 145, 151, 200, 3, 11, 21, 31, 2, 41, 61, 81, 151]
LOJAS = ["01", "02", "06", "10"]
PORTADORES = ["001", "114", "216"]


def main(url: str) -> None:
    rnd = random.Random(42)
    hoje = date.today()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(DDL)
        conn.execute("INSERT INTO condicoes VALUES ('004','4'), ('130','4'), ('001','1')")
        tit = 0
        for i, nome in enumerate(NOMES):
            codigo = f"{i + 1:08d}"
            cpf = f"{rnd.randint(10**10, 10**11 - 1):011d}"
            # a cada 7 clientes um telefone inválido, para o relatório de telefones inválidos
            celular = "123" if i % 7 == 6 else f"(11) 9{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}"
            status = "ABE"[i % 3]
            loja = LOJAS[i % len(LOJAS)]
            spc = "RESTRICAO: SIM" if i % 5 == 0 else "RESTRICAO: NAO"
            conn.execute(
                "INSERT INTO pessoas VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)",
                (codigo, nome, "", celular, "", cpf, status, loja, 2500, 1000,
                 date(1985, 1 + i % 12, 1 + i % 28), date(2019, 1, 1), spc),
            )
            # parcelas abertas: a mais antiga define o atraso
            atraso = DIAS[i]
            for k in range(1 + i % 3):
                tit += 1
                conn.execute(
                    "INSERT INTO financeiro_titulos VALUES (%s,%s,%s,%s,%s,%s,'R','A','4',%s,'PARCELA',NULL,0)",
                    (f"T{tit:09d}", codigo, 100 + 37 * (i % 9) + 10 * k,
                     hoje - timedelta(days=atraso) + timedelta(days=30 * k), loja,
                     PORTADORES[i % 3], f"VE{i + 1:06d}"),
                )
            # histórico pago (define cluster por valor pago)
            pago_total = [0, 500, 1200, 2000, 4000, 8000][i % 6]
            if pago_total:
                tit += 1
                conn.execute(
                    "INSERT INTO financeiro_titulos VALUES (%s,%s,%s,%s,%s,%s,'R','B','4',%s,'PARCELA',%s,%s)",
                    (f"T{tit:09d}", codigo, pago_total, hoje - timedelta(days=400), loja,
                     PORTADORES[i % 3], f"VE{i + 1:06d}", hoje - timedelta(days=395), pago_total),
                )
            # alguns clientes pagam "hoje": aparecem como efetivos depois de cobrados
            if i % 4 == 0:
                tit += 1
                conn.execute(
                    "INSERT INTO financeiro_titulos VALUES (%s,%s,%s,%s,%s,%s,'R','B','4',%s,'PARCELA',%s,%s)",
                    (f"T{tit:09d}", codigo, 150, hoje - timedelta(days=5), loja, PORTADORES[i % 3],
                     f"VE{i + 1:06d}", hoje, 150),
                )
            conn.execute(
                "INSERT INTO vendas VALUES (%s,%s,%s,'S','004')",
                (f"{i + 1:06d}", codigo, hoje - timedelta(days=420)),
            )
        # acordos do Renegocie (remarketing): RE000900 teve a entrada paga
        # (status B, pagamento antigo para não mexer na efetividade);
        # RE000901 está ativo com a entrada vencida e em aberto.
        conn.execute(
            "INSERT INTO financeiro_titulos VALUES ('T800000001','00000005',90,%s,'06','001','R','B','4',"
            "'RE000900','ENTRADA',%s,90)",
            (hoje - timedelta(days=300), hoje - timedelta(days=300)),
        )
        conn.execute(
            "INSERT INTO financeiro_titulos VALUES ('T800000002','00000027',80,%s,'06','001','R','A','4',"
            "'RE000901','ENTRADA',NULL,0,'1')",
            (hoje - timedelta(days=10),),
        )
    print(f"SETA falso populado: {len(NOMES)} clientes, {tit} títulos")


if __name__ == "__main__":
    main(sys.argv[1])
