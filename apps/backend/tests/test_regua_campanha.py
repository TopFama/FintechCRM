"""Teste da régua pós-campanha e do envio automático da régua e campanhas:
1. `enfileirar_na_regua` só deve rodar quando a extração automática de leads
   está ligada (`leads_auto_extract=True`).
2. `enfileirar_na_regua` roda no máximo uma vez por dia (quando conclui com status ready).
3. Fora da janela de agendamento (ex: fins de semana), não roda.
4. Campanhas com envio automático rodam de forma independente da régua diária.

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


print("OK")
