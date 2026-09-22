"""Teste da janela de agendamento do worker de disparo (bug de produção:
cliente ficava na fila dentro do horário configurado e não era cobrado).

Puro (sem banco): `_within_schedule_window` só depende do DispatchConfig e do
horário UTC informados. Executa com asserts simples, sem pytest.
"""

import os
import tempfile
from datetime import datetime

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-worker-schedule-123456")
os.environ.setdefault("ADMIN_PASSWORD", "senha-admin-teste-worker-schedule")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_k"
)

from app.models import DispatchConfig
from app.worker import _within_schedule_window


def _config(**overrides) -> DispatchConfig:
    defaults = dict(
        schedule_days="1,2,3,4,5",
        schedule_start="08:00",
        schedule_end="18:30",
    )
    defaults.update(overrides)
    return DispatchConfig(**defaults)


# Terça-feira 22/09/2026. 21:00 UTC == 18:00 em America/Sao_Paulo (UTC-3):
# dentro da janela 08:00-18:30 configurada em horário local, mas fora dela se
# comparado (incorretamente) direto em UTC — exatamente o bug relatado em
# produção: cliente entrou na fila "dentro do horário" e não foi cobrado.
config = _config()

assert _within_schedule_window(config, datetime(2026, 9, 22, 21, 0, 0)), (
    "21:00 UTC (18:00 em Brasília) deveria estar dentro da janela 08:00-18:30 local"
)

# 11:00 UTC == 08:00 em Brasília: início exato da janela, deve estar dentro.
assert _within_schedule_window(config, datetime(2026, 9, 22, 11, 0, 0))

# 08:00 UTC == 05:00 em Brasília: antes da janela local, deve estar fora.
assert not _within_schedule_window(config, datetime(2026, 9, 22, 8, 0, 0))

# 22:00 UTC == 19:00 em Brasília: depois do fim da janela local (18:30), fora.
assert not _within_schedule_window(config, datetime(2026, 9, 22, 22, 0, 0))

# Dia da semana também precisa ser calculado no horário local: sábado
# 26/09/2026 01:00 UTC já é sexta 25/09 22:00 em Brasília — dentro dos dias
# configurados (1 a 5, seg-sex), mesmo a data UTC já sendo sábado. Comparar
# o dia da semana direto em UTC (o bug) recusaria esse horário.
config_seg_a_sex = _config(schedule_days="1,2,3,4,5", schedule_start="00:00", schedule_end="23:59")
assert _within_schedule_window(config_seg_a_sex, datetime(2026, 9, 26, 1, 0, 0)), (
    "sábado 01:00 UTC = sexta 22:00 em Brasília, deveria estar dentro (ainda sexta)"
)

# Sábado de verdade em Brasília (26/09 12:00 local = 15:00 UTC): fora dos
# dias configurados.
assert not _within_schedule_window(config_seg_a_sex, datetime(2026, 9, 26, 15, 0, 0))

print("OK")
