// Alvo e credenciais da suíte. Os padrões apontam para o ambiente local de revisão
// (frontend em vite preview na 4174 e backend na 8010); em outro ambiente, defina as variáveis.
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8010";
export const EMAIL = process.env.E2E_EMAIL ?? "admin@topfama.com.br";
export const SENHA = process.env.E2E_SENHA ?? "senha-teste-123";
