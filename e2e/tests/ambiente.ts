// Alvo e credenciais da suíte — os padrões batem com e2e/ambiente/env.teste.sh.
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8010";
export const EMAIL = process.env.E2E_EMAIL ?? "admin@topfama.com.br";
export const SENHA = process.env.E2E_SENHA ?? "senha-teste-123";
