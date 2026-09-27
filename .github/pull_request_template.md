## Antes / Depois

Antes:

Depois:

## Como

## Checklist

- [ ] Cada arquivo tocado continua com uma responsabilidade só (ver `docs/architecture/fichas/`)
- [ ] Código novo está no domínio e na camada certos (`docs/architecture/dominios-e-camadas.md`)
- [ ] Nenhum router novo importado fora de `app/main.py`; `lint-imports` passa
- [ ] Regra de uma comunicação por cliente por dia preservada em todo caminho de envio
- [ ] SETA só leitura, em lote; horários de negócio em GMT-3; `.env` sem mudança
- [ ] Refatoração não muda comportamento (caracterização e e2e passando); mudança de
      comportamento vai em PR separado
- [ ] Mudou `models.py`? Migration gerada e revisada
- [ ] Documentação atualizada no mesmo PR (README, AGENTS.md, `.env.example`, `docs/architecture/`
      — ver AGENTS.md → "Documentação")
