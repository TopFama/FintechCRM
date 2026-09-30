"""Teste da régua pós-campanha e do envio automático da régua e campanhas:
1. `enfileirar_na_regua` só deve rodar quando a extração automática de leads
   está ligada (`leads_auto_extract=True`).
2. `enfileirar_na_regua` roda no máximo uma vez por dia (quando conclui com status ready).
3. Fora da janela de agendamento (ex: fins de semana), não roda.
4. Campanhas com envio automático rodam de forma independente da régua diária.
5. `enfileirar_leads(..., apenas_disparo_ativo=True)` só enfileira clientes em
   faixas cujo envio automático da régua estiver realmente habilitado
   (`dispatch_config.active=True`).
6. `campanhas_para_hoje` só seleciona campanhas com envio ativo e agendamento
   ativo (`dispatch_config.active=True`).
7. `enfileirar_clientes(..., apenas_disparo_ativo=True)` só insere se o envio tiver
   disparo ativo.

Bug de produção (30/09/2026): com `leads_auto_extract=False`, a rotina
`enfileirar_na_regua` rodava mesmo assim a cada 5 s, inserindo milhares de clientes
de campanhas anteriores na fila da régua sem que nenhuma opção de envio automático
estivesse ativada.
"""

from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-regua-campanha-123456")
os.environ.setdefault("ADMIN_PASSWORD", "senha-admin-teste-regua-campanha")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_k"
)

from app import campanhas, models, worker
from app.models import GlobalDispatchConfig
from app.fila_automatica import enfileirar_clientes, enfileirar_leads


def _config(**overrides) -> GlobalDispatchConfig:
    defaults = dict(
        id="global",
        schedule_days="1,2,3,4,5",
        schedule_start="08:00",
        schedule_end="18:30",
        leads_auto_extract=False,
        leads_auto_extract_minutos_antes=15,
        leads_auto_extract_last_run=None,
        remarketing_last_run=None,
    )
    defaults.update(overrides)
    return GlobalDispatchConfig(**defaults)


# Terça-feira 22/09/2026, 14:00 UTC == 11:00 Brasília: dentro da janela diária.
NOW_DENTRO_JANELA = datetime(2026, 9, 22, 14, 0, 0)

# Sábado 26/09/2026, 14:00 UTC == 11:00 Brasília: fora dos dias configurados.
NOW_FORA_JANELA = datetime(2026, 9, 26, 14, 0, 0)


# -----------------------------------------------------------------------
# Teste 1: leads_auto_extract=False → enfileirar_na_regua NÃO é chamada
# -----------------------------------------------------------------------
print("Teste 1: leads_auto_extract=False, dentro da janela → régua NÃO roda")

worker._regua_campanha_last_run = None
mock_enfileirar = MagicMock(return_value={"status": "ready", "clientes": 0, "na_fila": 0})
mock_campanhas_para_hoje = MagicMock(return_value=[])
config_desligado = _config(leads_auto_extract=False)

with (
    patch("app.worker.SessionLocal") as mock_session_cls,
    patch("app.worker._global_config", return_value=config_desligado),
    patch("app.worker.telefones_invalidos"),
    patch("app.worker.expirar_nao_enviados"),
    patch("app.campanhas.enfileirar_na_regua", mock_enfileirar),
    patch("app.campanhas.campanhas_para_hoje", mock_campanhas_para_hoje),
):
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db
    worker._rotinas_do_dia(NOW_DENTRO_JANELA)

assert not mock_enfileirar.called, (
    "enfileirar_na_regua NÃO deveria ser chamada com leads_auto_extract=False"
)
print("  OK")


# -----------------------------------------------------------------------
# Teste 2: leads_auto_extract=True → roda UMA vez e não repete no mesmo dia
# -----------------------------------------------------------------------
print("Teste 2: leads_auto_extract=True → roda uma vez e não repete no mesmo dia")

worker._regua_campanha_last_run = None
mock_enfileirar = MagicMock(return_value={"status": "ready", "clientes": 5, "na_fila": 5})
mock_campanhas_para_hoje = MagicMock(return_value=[])
config_ligado = _config(leads_auto_extract=True)

with (
    patch("app.worker.SessionLocal") as mock_session_cls,
    patch("app.worker._global_config", return_value=config_ligado),
    patch("app.worker.telefones_invalidos"),
    patch("app.worker.expirar_nao_enviados"),
    patch("app.worker._deve_extrair_leads", return_value=False),
    patch("app.worker._deve_rodar_remarketing", return_value=False),
    patch("app.campanhas.enfileirar_na_regua", mock_enfileirar),
    patch("app.campanhas.campanhas_para_hoje", mock_campanhas_para_hoje),
):
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db
    # 1ª chamada: deve executar
    worker._rotinas_do_dia(NOW_DENTRO_JANELA)
    assert mock_enfileirar.call_count == 1, "Deveria ter chamado enfileirar_na_regua na 1ª passada"

    # 2ª chamada (ciclo de 5 s depois, mesmo dia): NÃO deve executar de novo
    worker._rotinas_do_dia(NOW_DENTRO_JANELA)
    assert mock_enfileirar.call_count == 1, (
        "NÃO deveria chamar enfileirar_na_regua novamente no mesmo dia após 'ready'"
    )
print("  OK")


# -----------------------------------------------------------------------
# Teste 3: leads_auto_extract=True, fora da janela → NÃO roda
# -----------------------------------------------------------------------
print("Teste 3: leads_auto_extract=True, fora da janela (sábado) → régua NÃO roda")

worker._regua_campanha_last_run = None
mock_enfileirar = MagicMock(return_value={"status": "ready", "clientes": 0, "na_fila": 0})
config_ligado = _config(leads_auto_extract=True)

with (
    patch("app.worker.SessionLocal") as mock_session_cls,
    patch("app.worker._global_config", return_value=config_ligado),
    patch("app.worker.telefones_invalidos"),
    patch("app.worker.expirar_nao_enviados"),
    patch("app.worker._deve_extrair_leads", return_value=False),
    patch("app.worker._deve_rodar_remarketing", return_value=False),
    patch("app.campanhas.enfileirar_na_regua", mock_enfileirar),
):
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db
    worker._rotinas_do_dia(NOW_FORA_JANELA)

assert not mock_enfileirar.called, (
    "enfileirar_na_regua NÃO deveria ser chamada fora da janela de disparo"
)
print("  OK")


# -----------------------------------------------------------------------
# Teste 4: campanhas com envio automático funcionam independente da régua
# -----------------------------------------------------------------------
print("Teste 4: campanhas automáticas rodam mesmo com leads_auto_extract=False")

worker._regua_campanha_last_run = None
mock_enfileirar = MagicMock(return_value={"status": "ready", "clientes": 0, "na_fila": 0})
mock_campanha = MagicMock()
mock_campanha.id = "test-camp-1"
mock_campanha.nome = "teste"
mock_executar = MagicMock(return_value={"status": "ready"})
mock_campanhas_para_hoje = MagicMock(return_value=[mock_campanha])
config_desligado = _config(leads_auto_extract=False)

with (
    patch("app.worker.SessionLocal") as mock_session_cls,
    patch("app.worker._global_config", return_value=config_desligado),
    patch("app.worker.telefones_invalidos"),
    patch("app.worker.expirar_nao_enviados"),
    patch("app.campanhas.enfileirar_na_regua", mock_enfileirar),
    patch("app.campanhas.campanhas_para_hoje", mock_campanhas_para_hoje),
    patch("app.campanhas.executar", mock_executar),
):
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db
    worker._rotinas_do_dia(NOW_DENTRO_JANELA)

assert not mock_enfileirar.called, (
    "enfileirar_na_regua NÃO deveria rodar com leads_auto_extract=False"
)
assert mock_executar.called, (
    "campanhas.executar DEVERIA rodar (campanhas são independentes da régua)"
)
print("  OK")


# -----------------------------------------------------------------------
# Teste 5: enfileirar_leads com apenas_disparo_ativo=True respeita dispatch_config.active
# -----------------------------------------------------------------------
print("Teste 5: enfileirar_leads(..., apenas_disparo_ativo=True) só insere se envio ativo")

mock_db = MagicMock()
mock_faixa_inativa_disparo = MagicMock()
mock_faixa_inativa_disparo.name = "21 A 30"
mock_envio = MagicMock()
mock_envio.active = True
mock_envio.template_id = "tpl-1"
mock_envio.template = MagicMock()
mock_envio.dispatch_config = MagicMock()
mock_envio.dispatch_config.active = False  # DISPARO DESATIVADO!
mock_faixa_inativa_disparo.envios = [mock_envio]

with (
    patch("app.fila_automatica.clientes_bloqueados_hoje", return_value=set()),
    patch("app.fila_automatica.carregar_regras"),
):
    mock_lead = MagicMock()
    mock_lead.codigo_cliente = "00000001"
    mock_lead.vencimento_mais_antigo = "2026-09-01"
    mock_lead.celular = "5511999998888"
    mock_lead.nome = "Teste"
    mock_lead.cpf = "12345678901"
    mock_lead.valor_cobrar = "100.00"
    mock_lead.lojas = "01"
    mock_lead.celular_original = "5511999998888"
    mock_lead.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    mock_lead.parcelas = []

    def query_mock(model):
        q = MagicMock()
        q.options.return_value = q
        if model == models.Faixa:
            q.filter.return_value = [mock_faixa_inativa_disparo]
        elif model == models.Lead:
            q.filter.return_value = [mock_lead]
        return q

    mock_db.query.side_effect = query_mock

    clientes = [{"codigo": "00000001", "faixa": "21 A 30", "vencimento_mais_antigo": "2026-09-01"}]

    # Chamada automática: com apenas_disparo_ativo=True, a faixa com dispatch_config.active=False deve ser ignorada
    inseridos = enfileirar_leads(mock_db, clientes, apenas_disparo_ativo=True)
    assert inseridos == 0, f"Deveria ter ignorado faixa com dispatch_config.active=False, mas inseriu {inseridos}"

    # Agora ativando o disparo:
    mock_envio.dispatch_config.active = True
    with patch("app.itens_fila.novo_item"):
        inseridos_ativo = enfileirar_leads(mock_db, clientes, apenas_disparo_ativo=True)
        assert inseridos_ativo == 1, f"Deveria ter inserido 1 cliente com disparo ativo, obteve {inseridos_ativo}"

print("  OK")


# -----------------------------------------------------------------------
# Teste 6: campanhas_para_hoje só seleciona campanhas com agendamento ativo
# -----------------------------------------------------------------------
print("Teste 6: campanhas_para_hoje filtra envios sem agendamento ativo")

mock_db_camp = MagicMock()
mock_camp_inativa_disp = MagicMock()
mock_camp_inativa_disp.ativa = True
mock_camp_inativa_disp.arquivada_em = None
mock_camp_inativa_disp.data_inicio = datetime(2026, 9, 1).date()
mock_camp_inativa_disp.data_fim = None
mock_camp_inativa_disp.ultima_execucao_dia = None
mock_camp_inativa_disp.faixa_id = "fx-camp-1"

mock_envio_camp = MagicMock()
mock_envio_camp.active = True
mock_envio_camp.template_id = "tpl-camp"
mock_envio_camp.dispatch_config = MagicMock()
mock_envio_camp.dispatch_config.active = False  # AGENDAMENTO PAUSADO!
mock_camp_inativa_disp.faixa.envios = [mock_envio_camp]

q_camp = MagicMock()
q_camp.options.return_value.filter.return_value = [mock_camp_inativa_disp]
mock_db_camp.query.return_value = q_camp

with patch("app.campanhas.pausas.ativas", return_value=[]):
    selecionadas = campanhas.campanhas_para_hoje(mock_db_camp)
    assert len(selecionadas) == 0, "Campanha com dispatch_config.active=False NÃO deve entrar em campanhas_para_hoje"

    # Agora ativando o disparo:
    mock_envio_camp.dispatch_config.active = True
    selecionadas_ativas = campanhas.campanhas_para_hoje(mock_db_camp)
    assert len(selecionadas_ativas) == 1, "Campanha com dispatch_config.active=True DEVE entrar"

print("  OK")


# -----------------------------------------------------------------------
# Teste 7: enfileirar_clientes com apenas_disparo_ativo=True respeita dispatch_config.active
# -----------------------------------------------------------------------
print("Teste 7: enfileirar_clientes(..., apenas_disparo_ativo=True) respeita disparo ativo")

mock_faixa_clientes = MagicMock()
mock_faixa_clientes.name = "Campanha 1"
mock_envio_c = MagicMock()
mock_envio_c.active = True
mock_envio_c.template_id = "tpl-1"
mock_envio_c.template = MagicMock()
mock_envio_c.dispatch_config = MagicMock()
mock_envio_c.dispatch_config.active = False  # DISPARO DESLIGADO!
mock_faixa_clientes.envios = [mock_envio_c]

mock_db_cli = MagicMock()
cli_lista = [{"codigo": "00000002", "celular": "5511988887777", "nome": "Cliente", "cpfcnpj": "12345678901", "valor_cobrar": "50.00"}]

# Com disparo inativo: deve retornar 0
qtd_inativo = enfileirar_clientes(
    mock_db_cli,
    mock_faixa_clientes,
    cli_lista,
    bloqueados=set(),
    juros=None,
    parcelas={},
    origem="teste",
    apenas_disparo_ativo=True,
)
assert qtd_inativo == 0, f"Deveria retornar 0 com disparo desativado, obteve {qtd_inativo}"

# Com disparo ativo:
mock_envio_c.dispatch_config.active = True
with (
    patch("app.itens_fila.fontes_por_template", return_value={}),
    patch("app.itens_fila.resolver_por_template", return_value=({}, [])),
    patch("app.itens_fila.novo_item"),
):
    qtd_ativo = enfileirar_clientes(
        mock_db_cli,
        mock_faixa_clientes,
        cli_lista,
        bloqueados=set(),
        juros=None,
        parcelas={},
        origem="teste",
        apenas_disparo_ativo=True,
    )
    assert qtd_ativo == 1, f"Deveria ter inserido 1 cliente com disparo ativo, obteve {qtd_ativo}"

print("  OK")


print("OK")
