"""multiplos numeros e templates por faixa

Uma faixa passa a poder ter vários pares (número de WhatsApp, template) —
FaixaEnvio — cada um com seu próprio agendamento de disparo, pensado pra
WABAs diferentes cobrando em paralelo com distribuição pelos números e sem
cobrar o mesmo cliente duas vezes (a fila continua compartilhada por
faixa; cada item só é reservado por um envio).

Antes: Faixa tinha um único template_id e uma lista de números
(FaixaNumber) que só alternavam entre si (last_number_index) usando SEMPRE
o mesmo template e o mesmo DispatchConfig (1 por faixa). Depois: cada
FaixaEnvio (faixa + número + template) tem seu próprio DispatchConfig;
FaixaVariableMapping passa a ser por (faixa, template) em vez de só por
faixa, já que cada template tem suas próprias variáveis.

Migração de dados: cada FaixaNumber existente vira um FaixaEnvio com o
template que a faixa já tinha, carregando consigo uma cópia do
DispatchConfig antigo (compartilhado por faixa); FaixaVariableMapping
existente ganha o template_id da faixa (só havia um).

Revision ID: 02887e88dfea
Revises: 657a127e9ad1
Create Date: 2026-09-22 19:10:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '02887e88dfea'
down_revision: Union[str, None] = '657a127e9ad1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'faixa_envios',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('faixa_id', sa.String(), nullable=False),
        sa.Column('whatsapp_number_id', sa.String(), nullable=False),
        sa.Column('template_id', sa.String(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['faixa_id'], ['faixas.id']),
        sa.ForeignKeyConstraint(['whatsapp_number_id'], ['whatsapp_numbers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('faixa_id', 'whatsapp_number_id', name='faixa_envios_faixa_id_whatsapp_number_id_key'),
    )

    op.add_column(
        'dispatch_configs',
        sa.Column('faixa_envio_id', sa.String(), nullable=True),
    )
    # Torna faixa_id opcional só durante a migração — os novos registros
    # (1 dispatch_config por envio) são inseridos sem faixa_id, que é
    # removida no fim desta função.
    op.alter_column('dispatch_configs', 'faixa_id', existing_type=sa.String(), nullable=True)
    op.add_column(
        'faixa_variable_mappings',
        sa.Column('template_id', sa.String(), nullable=True),
    )

    conn = op.get_bind()

    faixas = conn.execute(
        sa.text("SELECT id, template_id FROM faixas WHERE template_id IS NOT NULL")
    ).fetchall()

    for faixa_id, template_id in faixas:
        # O mapeamento de variáveis é do par (faixa, template), independente
        # de a faixa já ter número atribuído — backfill sempre que houver
        # template, mesmo pra faixa ainda sem nenhum FaixaNumber.
        conn.execute(
            sa.text(
                "UPDATE faixa_variable_mappings SET template_id = :template_id WHERE faixa_id = :faixa_id"
            ),
            {"template_id": template_id, "faixa_id": faixa_id},
        )

        numeros = conn.execute(
            sa.text("SELECT whatsapp_number_id FROM faixa_numbers WHERE faixa_id = :fid"),
            {"fid": faixa_id},
        ).fetchall()
        if not numeros:
            continue

        config_antigo = conn.execute(
            sa.text(
                "SELECT interval_seconds, batch_size, schedule_days, schedule_start, "
                "schedule_end, active, last_run_at, force_run "
                "FROM dispatch_configs WHERE faixa_id = :fid"
            ),
            {"fid": faixa_id},
        ).mappings().first()

        for (numero_id,) in numeros:
            envio_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO faixa_envios "
                    "(id, faixa_id, whatsapp_number_id, template_id, active, created_at) "
                    "VALUES (:id, :faixa_id, :numero_id, :template_id, true, now())"
                ),
                {"id": envio_id, "faixa_id": faixa_id, "numero_id": numero_id, "template_id": template_id},
            )
            params = {"id": str(uuid.uuid4()), "envio_id": envio_id}
            if config_antigo is not None:
                params.update(dict(config_antigo))
                conn.execute(
                    sa.text(
                        "INSERT INTO dispatch_configs "
                        "(id, faixa_envio_id, interval_seconds, batch_size, schedule_days, "
                        "schedule_start, schedule_end, active, last_run_at, force_run) "
                        "VALUES (:id, :envio_id, :interval_seconds, :batch_size, :schedule_days, "
                        ":schedule_start, :schedule_end, :active, :last_run_at, :force_run)"
                    ),
                    params,
                )
            else:
                conn.execute(
                    sa.text("INSERT INTO dispatch_configs (id, faixa_envio_id) VALUES (:id, :envio_id)"),
                    params,
                )

    # dispatch_configs antigos que não migraram (faixa sem template ou sem
    # número) ficam sem faixa_envio_id: são órfãos do modelo antigo, remove.
    conn.execute(sa.text("DELETE FROM dispatch_configs WHERE faixa_envio_id IS NULL"))
    # Mapeamentos de variável de faixas sem template (não deveria existir na
    # prática, já que o mapeamento sempre exigiu um template) ficam sem
    # template_id: também são órfãos, remove.
    conn.execute(sa.text("DELETE FROM faixa_variable_mappings WHERE template_id IS NULL"))

    op.drop_constraint('dispatch_configs_faixa_id_key', 'dispatch_configs', type_='unique')
    op.drop_constraint('dispatch_configs_faixa_id_fkey', 'dispatch_configs', type_='foreignkey')
    op.drop_column('dispatch_configs', 'faixa_id')
    op.alter_column('dispatch_configs', 'faixa_envio_id', existing_type=sa.String(), nullable=False)
    op.create_unique_constraint(
        'dispatch_configs_faixa_envio_id_key', 'dispatch_configs', ['faixa_envio_id']
    )
    op.create_foreign_key(
        'dispatch_configs_faixa_envio_id_fkey',
        'dispatch_configs', 'faixa_envios', ['faixa_envio_id'], ['id'], ondelete='CASCADE',
    )

    op.drop_constraint(
        'faixa_variable_mappings_faixa_id_template_variable_id_key',
        'faixa_variable_mappings', type_='unique',
    )
    op.alter_column('faixa_variable_mappings', 'template_id', existing_type=sa.String(), nullable=False)
    op.create_foreign_key(
        'faixa_variable_mappings_template_id_fkey',
        'faixa_variable_mappings', 'templates', ['template_id'], ['id'],
    )
    op.create_unique_constraint(
        'faixa_variable_mappings_faixa_id_template_id_template_var_key',
        'faixa_variable_mappings', ['faixa_id', 'template_id', 'template_variable_id'],
    )

    op.drop_table('faixa_numbers')
    op.drop_constraint('faixas_template_id_fkey', 'faixas', type_='foreignkey')
    op.drop_column('faixas', 'template_id')
    op.drop_column('faixas', 'last_number_index')


def downgrade() -> None:
    conn = op.get_bind()

    op.add_column('faixas', sa.Column('template_id', sa.String(), nullable=True))
    op.add_column(
        'faixas',
        sa.Column('last_number_index', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_foreign_key('faixas_template_id_fkey', 'faixas', 'templates', ['template_id'], ['id'])

    op.create_table(
        'faixa_numbers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('faixa_id', sa.String(), nullable=False),
        sa.Column('whatsapp_number_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['faixa_id'], ['faixas.id']),
        sa.ForeignKeyConstraint(['whatsapp_number_id'], ['whatsapp_numbers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('faixa_id', 'whatsapp_number_id', name='faixa_numbers_faixa_id_whatsapp_number_id_key'),
    )

    op.add_column('dispatch_configs', sa.Column('faixa_id', sa.String(), nullable=True))

    # Um FaixaEnvio (o mais antigo) por faixa vira o template_id/dispatch_config
    # únicos do modelo anterior; os demais envios (números/templates extras,
    # que o modelo antigo não suporta) só entram em faixa_numbers — a
    # informação de qual template cada um usava se perde no downgrade.
    faixas_com_envio = conn.execute(
        sa.text("SELECT DISTINCT faixa_id FROM faixa_envios")
    ).fetchall()

    for (faixa_id,) in faixas_com_envio:
        envios = conn.execute(
            sa.text(
                "SELECT id, whatsapp_number_id, template_id FROM faixa_envios "
                "WHERE faixa_id = :fid ORDER BY created_at ASC"
            ),
            {"fid": faixa_id},
        ).fetchall()

        canonical_id, _, canonical_template_id = envios[0]
        conn.execute(
            sa.text("UPDATE faixas SET template_id = :tid WHERE id = :fid"),
            {"tid": canonical_template_id, "fid": faixa_id},
        )

        for envio_id, numero_id, _ in envios:
            conn.execute(
                sa.text(
                    "INSERT INTO faixa_numbers (id, faixa_id, whatsapp_number_id) "
                    "VALUES (:id, :faixa_id, :numero_id) ON CONFLICT DO NOTHING"
                ),
                {"id": str(uuid.uuid4()), "faixa_id": faixa_id, "numero_id": numero_id},
            )

        conn.execute(
            sa.text("UPDATE dispatch_configs SET faixa_id = :fid WHERE faixa_envio_id = :envio_id"),
            {"fid": faixa_id, "envio_id": canonical_id},
        )

    # Configs dos envios não-canônicos (faixa_id ainda nulo) não cabem mais
    # no modelo antigo (1 config por faixa) — descarta.
    conn.execute(sa.text("DELETE FROM dispatch_configs WHERE faixa_id IS NULL"))

    op.drop_constraint('dispatch_configs_faixa_envio_id_fkey', 'dispatch_configs', type_='foreignkey')
    op.drop_constraint('dispatch_configs_faixa_envio_id_key', 'dispatch_configs', type_='unique')
    op.drop_column('dispatch_configs', 'faixa_envio_id')
    op.alter_column('dispatch_configs', 'faixa_id', existing_type=sa.String(), nullable=False)
    op.create_unique_constraint('dispatch_configs_faixa_id_key', 'dispatch_configs', ['faixa_id'])
    op.create_foreign_key(
        'dispatch_configs_faixa_id_fkey', 'dispatch_configs', 'faixas', ['faixa_id'], ['id']
    )

    op.drop_constraint(
        'faixa_variable_mappings_faixa_id_template_id_template_var_key',
        'faixa_variable_mappings', type_='unique',
    )
    op.drop_constraint(
        'faixa_variable_mappings_template_id_fkey', 'faixa_variable_mappings', type_='foreignkey'
    )
    op.drop_column('faixa_variable_mappings', 'template_id')
    op.create_unique_constraint(
        'faixa_variable_mappings_faixa_id_template_variable_id_key',
        'faixa_variable_mappings', ['faixa_id', 'template_variable_id'],
    )

    op.drop_table('faixa_envios')
