"""regras de cobranca em banco

Revision ID: 364478fd9506
Revises: d3dec284035d
Create Date: 2026-09-21 21:40:58.148434

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '364478fd9506'
down_revision: Union[str, None] = 'd3dec284035d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('config_clusters',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('nome', sa.String(), nullable=False),
    sa.Column('valor_min', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('config_faixas_atraso',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('nome', sa.String(), nullable=False),
    sa.Column('dia_min', sa.Integer(), nullable=False),
    sa.Column('dia_max', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('config_parametros',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('juros_mes_percentual', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('multa_percentual', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('dias_min_juros', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('config_regras_whatsapp',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('cluster_id', sa.String(), nullable=False),
    sa.Column('faixa_id', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['cluster_id'], ['config_clusters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['faixa_id'], ['config_faixas_atraso.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cluster_id', 'faixa_id')
    )

    # --- Seed: valores iniciais reproduzindo o comportamento anterior ---

    t_clusters = sa.table('config_clusters',
        sa.column('id', sa.String),
        sa.column('nome', sa.String),
        sa.column('valor_min', sa.Numeric),
    )
    t_faixas = sa.table('config_faixas_atraso',
        sa.column('id', sa.String),
        sa.column('nome', sa.String),
        sa.column('dia_min', sa.Integer),
        sa.column('dia_max', sa.Integer),
    )
    t_parametros = sa.table('config_parametros',
        sa.column('id', sa.String),
        sa.column('juros_mes_percentual', sa.Numeric),
        sa.column('multa_percentual', sa.Numeric),
        sa.column('dias_min_juros', sa.Integer),
    )
    t_regras = sa.table('config_regras_whatsapp',
        sa.column('id', sa.String),
        sa.column('cluster_id', sa.String),
        sa.column('faixa_id', sa.String),
    )

    # Clusters (nome -> valor_min)
    cluster_ids = {
        "ESPECIAL": str(uuid.uuid4()),
        "POTENCIAL": str(uuid.uuid4()),
        "EM POTENCIAL": str(uuid.uuid4()),
        "ALTO POTENCIAL": str(uuid.uuid4()),
        "BEST SELLER": str(uuid.uuid4()),
        "HEAVY USER": str(uuid.uuid4()),
    }
    op.bulk_insert(t_clusters, [
        {"id": cluster_ids["ESPECIAL"],       "nome": "ESPECIAL",       "valor_min": "0"},
        {"id": cluster_ids["POTENCIAL"],      "nome": "POTENCIAL",      "valor_min": "400"},
        {"id": cluster_ids["EM POTENCIAL"],   "nome": "EM POTENCIAL",   "valor_min": "1000"},
        {"id": cluster_ids["ALTO POTENCIAL"], "nome": "ALTO POTENCIAL", "valor_min": "1500"},
        {"id": cluster_ids["BEST SELLER"],    "nome": "BEST SELLER",    "valor_min": "3000"},
        {"id": cluster_ids["HEAVY USER"],     "nome": "HEAVY USER",     "valor_min": "7000"},
    ])

    # Faixas de atraso (nome -> dia_min, dia_max)
    faixa_ids = {
        "-1":       str(uuid.uuid4()),
        "2":        str(uuid.uuid4()),
        "3 A 10":   str(uuid.uuid4()),
        "11 A 20":  str(uuid.uuid4()),
        "21 A 30":  str(uuid.uuid4()),
        "31 A 40":  str(uuid.uuid4()),
        "41 A 60":  str(uuid.uuid4()),
        "61 A 80":  str(uuid.uuid4()),
        "81 A 100": str(uuid.uuid4()),
        "101 A 120":str(uuid.uuid4()),
        "121 A 140":str(uuid.uuid4()),
        "141 A 150":str(uuid.uuid4()),
        "151+":     str(uuid.uuid4()),
    }
    op.bulk_insert(t_faixas, [
        {"id": faixa_ids["-1"],        "nome": "-1",        "dia_min": -1,  "dia_max": 1},
        {"id": faixa_ids["2"],         "nome": "2",         "dia_min": 2,   "dia_max": 2},
        {"id": faixa_ids["3 A 10"],    "nome": "3 A 10",    "dia_min": 3,   "dia_max": 10},
        {"id": faixa_ids["11 A 20"],   "nome": "11 A 20",   "dia_min": 11,  "dia_max": 20},
        {"id": faixa_ids["21 A 30"],   "nome": "21 A 30",   "dia_min": 21,  "dia_max": 30},
        {"id": faixa_ids["31 A 40"],   "nome": "31 A 40",   "dia_min": 31,  "dia_max": 40},
        {"id": faixa_ids["41 A 60"],   "nome": "41 A 60",   "dia_min": 41,  "dia_max": 60},
        {"id": faixa_ids["61 A 80"],   "nome": "61 A 80",   "dia_min": 61,  "dia_max": 80},
        {"id": faixa_ids["81 A 100"],  "nome": "81 A 100",  "dia_min": 81,  "dia_max": 100},
        {"id": faixa_ids["101 A 120"], "nome": "101 A 120", "dia_min": 101, "dia_max": 120},
        {"id": faixa_ids["121 A 140"], "nome": "121 A 140", "dia_min": 121, "dia_max": 140},
        {"id": faixa_ids["141 A 150"], "nome": "141 A 150", "dia_min": 141, "dia_max": 150},
        {"id": faixa_ids["151+"],      "nome": "151+",      "dia_min": 151, "dia_max": None},
    ])

    # Parâmetros de juros. Carência 2 = juros a partir de 3 dias de atraso
    # ("maior que", desde f9ffe94); só vale para banco novo, o de produção
    # mantém o que foi configurado em Indicadores.
    op.bulk_insert(t_parametros, [
        {"id": str(uuid.uuid4()), "juros_mes_percentual": "15.99", "multa_percentual": "2", "dias_min_juros": 2},
    ])

    # Matriz WhatsApp: cluster -> faixas que recebem
    base_alto = ["-1", "11 A 20", "31 A 40", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]
    base_potencial = ["-1", "2", "11 A 20", "31 A 40", "61 A 80", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]
    matriz = {
        "ESPECIAL":       ["-1", "2", "11 A 20", "21 A 30", "61 A 80", "101 A 120", "121 A 140", "141 A 150", "151+"],
        "POTENCIAL":      base_potencial,
        "EM POTENCIAL":   base_potencial,
        "ALTO POTENCIAL": base_alto,
        "BEST SELLER":    base_alto,
        "HEAVY USER":     base_alto,
    }
    celulas = []
    for cluster_nome, faixas in matriz.items():
        for faixa_nome in faixas:
            celulas.append({
                "id": str(uuid.uuid4()),
                "cluster_id": cluster_ids[cluster_nome],
                "faixa_id": faixa_ids[faixa_nome],
            })
    op.bulk_insert(t_regras, celulas)


def downgrade() -> None:
    op.drop_table('config_regras_whatsapp')
    op.drop_table('config_parametros')
    op.drop_table('config_faixas_atraso')
    op.drop_table('config_clusters')
