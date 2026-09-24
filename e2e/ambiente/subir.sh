#!/usr/bin/env bash
# Sobe o ambiente de TESTE do zero: bancos locais descartáveis (app + SETA falso),
# backend com integrações simuladas (porta 8010) e frontend em vite preview (4174).
# Nada aqui toca produção nem o .env do projeto.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
source "$AQUI/env.teste.sh"
PG_SUPER="${PG_SUPER:-postgres}"   # usuário do Postgres local com permissão de criar bancos
LOGS="${E2E_LOGS:-$AQUI/../.ambiente-logs}"
mkdir -p "$LOGS" "$MEDIA_DIR"

# derruba uma rodada anterior (pids guardados por este mesmo script)
for pid in "$LOGS/backend.pid" "$LOGS/frontend.pid"; do
  [ -f "$pid" ] && kill "$(cat "$pid")" 2>/dev/null || true
done
sleep 1
for porta in 8010 4174; do
  if curl -s -o /dev/null "localhost:$porta"; then
    echo "porta $porta ainda ocupada (servidor de uma rodada anterior?): encerre-o e rode de novo" >&2; exit 1
  fi
done

# o SQL vai pela entrada padrão para não passar por mais uma camada de aspas do shell
psql_super() { if [ "$(id -un)" = root ]; then echo "$1" | su "$PG_SUPER" -c "psql -v ON_ERROR_STOP=1 -q"; else echo "$1" | psql -U "$PG_SUPER" -v ON_ERROR_STOP=1 -q; fi; }
psql_super 'DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '"'crm'"') THEN CREATE ROLE crm LOGIN PASSWORD '"'crm'"'; END IF; END$$;'
for db in crm_app seta_fake; do
  psql_super "DROP DATABASE IF EXISTS $db WITH (FORCE);"
  psql_super "CREATE DATABASE $db OWNER crm;"
done
redis-cli -n 15 flushdb >/dev/null 2>&1 || echo "aviso: redis local indisponível (relatórios em cache podem falhar)"

PY="$RAIZ/apps/backend/.venv/bin/python"
[ -x "$PY" ] || { python3 -m venv "$RAIZ/apps/backend/.venv"; "$RAIZ/apps/backend/.venv/bin/pip" install -q -r "$RAIZ/apps/backend/requirements.txt"; }
"$PY" "$AQUI/seta_falso.py" "postgresql://crm:crm@localhost:5432/seta_fake"

nohup "$PY" "$AQUI/servidor_teste.py" 8010 > "$LOGS/backend.log" 2>&1 &
echo $! > "$LOGS/backend.pid"
for _ in $(seq 60); do curl -sf localhost:8010/health >/dev/null && break; sleep 1; done
curl -sf localhost:8010/health >/dev/null || { tail -40 "$LOGS/backend.log"; exit 1; }

cd "$RAIZ/apps/frontend"
[ -d node_modules ] || npm install --silent
VITE_API_URL=http://localhost:8010 npm run build --silent >/dev/null
nohup ./node_modules/.bin/vite preview --port 4174 --strictPort > "$LOGS/frontend.log" 2>&1 &
echo $! > "$LOGS/frontend.pid"
for _ in $(seq 30); do curl -sf localhost:4174 >/dev/null && break; sleep 1; done
echo "Ambiente de teste no ar: frontend http://localhost:4174 · backend http://localhost:8010"
