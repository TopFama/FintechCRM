# Variáveis do ambiente de TESTE (nada aqui é de produção). Use: source env.teste.sh
export DATABASE_URL="postgresql+psycopg://crm:crm@localhost:5432/crm_app"
export SETA_DB_HOST=localhost SETA_DB_PORT=5432 SETA_DB_NAME=seta_fake SETA_DB_USER=crm SETA_DB_PASSWORD=crm
export JWT_SECRET="segredo-apenas-para-teste-e2e"
export ENCRYPTION_KEY="kVcXb0jcRLJ3mNcvj3xYQn3q2mHk5a1Q2dM0Qm9pZ1c="
export ADMIN_EMAIL="admin@topfama.com.br" ADMIN_PASSWORD="senha-teste-123"
export COOKIE_SECURE=false CORS_ALLOWED_ORIGINS="http://localhost:4174"
export REDIS_URL="redis://localhost:6379/15"
export MEDIA_DIR="${TMPDIR:-/tmp}/fintechcrm-e2e-media"
export DISPATCH_WORKER_INTERVAL_SECONDS=2
