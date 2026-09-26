#!/usr/bin/env bash
# Roda todos os scripts de teste do backend, cada um no próprio banco recriado
# antes (o nome está no DATABASE_URL de cada arquivo). Precisa de Postgres
# UTF-8 em localhost:15432 com usuário postgres e senha "t", e do venv em .venv.
# Uso (de apps/backend): ./tests/rodar_todos.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
export PGPASSWORD=t
falhas=0
for teste in tests/test_*.py; do
  banco=$(grep -o "localhost:15432/[a-z_]*" "$teste" | head -1 | cut -d/ -f2)
  if [ -n "$banco" ]; then
    psql -h localhost -p 15432 -U postgres -v ON_ERROR_STOP=1 -q \
      -c "DROP DATABASE IF EXISTS $banco WITH (FORCE)" -c "CREATE DATABASE $banco" >/dev/null || exit 1
  fi
  saida=$(PYTHONPATH=. "$PY" "$teste" 2>&1)
  if [ "$(printf '%s\n' "$saida" | tail -1)" = "OK" ]; then
    echo "ok     $teste"
  else
    echo "FALHOU $teste"
    printf '%s\n' "$saida" | tail -30
    falhas=$((falhas + 1))
  fi
done
[ "$falhas" -eq 0 ] || { echo "$falhas script(s) falharam"; exit 1; }
echo "todos os scripts passaram"
