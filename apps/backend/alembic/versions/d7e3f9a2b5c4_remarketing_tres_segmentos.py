"""remarketing com três segmentos: identificados, propostas simuladas e acordo ativo não pago

"Cancelou a proposta" sai (o Renegocie passa a mandar esses clientes como
proposta simulada) e "Acordo cancelado sem pagar a entrada" vira "Acordo ativo
com entrada não paga" — mesma faixa, número e template, mas desligado, porque
o público mudou. A faixa do segmento que sai só é apagada se nada aponta pra ela.

Revision ID: d7e3f9a2b5c4
Revises: c5d2e8f1a9b3
Create Date: 2026-09-24
"""

from alembic import op

revision = "d7e3f9a2b5c4"
down_revision = "c5d2e8f1a9b3"
branch_labels = None
depends_on = None

_NOMES = {
    "SO_IDENTIFICOU": "Remarketing: Clientes identificados no portal",
    "VIU_PROPOSTA": "Remarketing: Propostas simuladas",
    "ACORDO_ATIVO": "Remarketing: Acordo ativo com entrada não paga",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _faixa_cancelou ON COMMIT DROP AS
        SELECT faixa_id FROM remarketing_segmentos WHERE segmento = 'CANCELOU_PROPOSTA'
        """
    )
    op.execute("DELETE FROM remarketing_segmentos WHERE segmento = 'CANCELOU_PROPOSTA'")
    op.execute(
        """
        DELETE FROM faixas f USING _faixa_cancelou c
         WHERE f.id = c.faixa_id
           AND NOT EXISTS (SELECT 1 FROM cobranca_fila x WHERE x.faixa_id = f.id)
           AND NOT EXISTS (SELECT 1 FROM faixa_variable_mappings x WHERE x.faixa_id = f.id)
           AND NOT EXISTS (SELECT 1 FROM telefones_invalidos x WHERE x.faixa_id = f.id)
           AND NOT EXISTS (SELECT 1 FROM upload_logs x WHERE x.faixa_id = f.id)
           AND NOT EXISTS (SELECT 1 FROM log_erros x WHERE x.faixa_id = f.id)
           AND NOT EXISTS (SELECT 1 FROM faixa_envios x WHERE x.faixa_id = f.id)
        """
    )
    op.execute(
        "UPDATE remarketing_segmentos SET segmento = 'ACORDO_ATIVO', ativo = false "
        "WHERE segmento = 'ACORDO_SEM_ENTRADA'"
    )
    for segmento, nome in _NOMES.items():
        op.execute(
            f"UPDATE faixas SET name = '{nome}' FROM remarketing_segmentos r "
            f"WHERE r.faixa_id = faixas.id AND r.segmento = '{segmento}'"
        )


def downgrade() -> None:
    # Só desfaz o que dá: nomes e o segmento renomeado. O "Cancelou a proposta"
    # é recriado sozinho (desligado) quando a versão anterior do código sobe.
    op.execute(
        "UPDATE remarketing_segmentos SET segmento = 'ACORDO_SEM_ENTRADA', ativo = false "
        "WHERE segmento = 'ACORDO_ATIVO'"
    )
    antigos = {
        "SO_IDENTIFICOU": "Remarketing: Só se identificou",
        "VIU_PROPOSTA": "Remarketing: Viu a proposta e não fechou",
        "ACORDO_SEM_ENTRADA": "Remarketing: Acordo cancelado sem pagar a entrada",
    }
    for segmento, nome in antigos.items():
        op.execute(
            f"UPDATE faixas SET name = '{nome}' FROM remarketing_segmentos r "
            f"WHERE r.faixa_id = faixas.id AND r.segmento = '{segmento}'"
        )
