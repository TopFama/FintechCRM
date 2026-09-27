"""Gera docs/architecture/deps.svg: imports internos do backend (apps/backend/app),
agrupados pelo domínio de cada módulo (ver dominios-e-camadas.md).

Rodar da raiz do repositório (precisa do Graphviz, comando `dot`):
    python3 docs/architecture/scripts/grafo_dependencias.py

Arestas em vermelho violam a regra de camadas: módulo de serviço/domínio
importando um router, ou router importando outro router.
"""

import ast
import os
import subprocess
import sys

RAIZ = os.path.join("apps", "backend")
PACOTE = "app"

# módulo -> domínio. Módulo novo sem entrada aparece em "(sem domínio)".
DOMINIO = {
    # Autenticação
    "routers.auth": "Autenticação", "routers.users": "Autenticação", "security": "Autenticação",
    "deps": "Autenticação", "rate_limit": "Autenticação",
    # Conexões e integrações externas
    "meta_client": "Integrações", "chatwoot_client": "Integrações", "google_client": "Integrações",
    "seta_client": "Integrações", "cambio": "Integrações", "crypto": "Integrações", "segredos": "Integrações",
    "routers.meta_tokens": "Integrações", "routers.chatwoot": "Integrações", "routers.google": "Integrações",
    "routers.seta": "Integrações", "routers.numbers": "Integrações",
    # Templates
    "routers.templates": "Templates", "variaveis_template": "Templates", "utils.imagem": "Templates",
    # Lojas
    "lojas": "Lojas", "lojas_iniciais": "Lojas", "routers.lojas": "Lojas",
    # Base de cobrança (SETA) e leads
    "cobranca_base": "Cobrança", "cobranca_regras": "Cobrança", "regras_db": "Cobrança",
    "cobranca_relatorio": "Cobrança", "routers.cobranca": "Cobrança", "routers.config_cobranca": "Cobrança",
    "leads_service": "Cobrança", "routers.leads": "Cobrança", "utils.leads_xlsx": "Cobrança", "utils.spc": "Cobrança",
    "services.compras_seta": "Cobrança",
    # Réguas (faixas)
    "routers.faixas": "Réguas",
    # Envios (fila, disparo, pausas, blacklist)
    "fila_automatica": "Envios", "worker": "Envios", "dispatch_service": "Envios", "pausas": "Envios",
    "routers.pausas": "Envios", "routers.uploads": "Envios", "routers.blacklist": "Envios",
    "elegibilidade": "Envios", "blacklist": "Envios", "itens_fila": "Envios", "upload_service": "Envios",
    # Campanhas e remarketing
    "campanhas": "Campanhas", "campanhas_fixas": "Campanhas", "routers.campanhas": "Campanhas",
    "remarketing": "Campanhas", "routers.remarketing": "Campanhas",
    # Pagamentos
    "services.pagamentos_seta": "Pagamentos", "services.pagamentos_service": "Pagamentos",
    "services.pagos_janela_service": "Pagamentos",
    # Dashboard e relatórios
    "routers.dashboard": "Dashboard/Relatórios", "routers.reports": "Dashboard/Relatórios",
    "services.efetividade_service": "Dashboard/Relatórios", "relatorio_efetividade": "Dashboard/Relatórios",
    "services.custo_whatsapp": "Dashboard/Relatórios", "consultas_fila": "Dashboard/Relatórios",
    # Plataforma (compartilhado)
    "main": "Plataforma", "config": "Plataforma", "database": "Plataforma", "models": "Plataforma",
    "schemas": "Plataforma", "cache": "Plataforma", "timezone": "Plataforma", "utils.phone": "Plataforma",
    "utils.document": "Plataforma", "utils.spreadsheet": "Plataforma", "utils.xlsx": "Plataforma",
    "routers.comum": "Plataforma",
}

CORES = {
    "Autenticação": "#e8eaf6", "Integrações": "#e0f2f1", "Templates": "#f3e5f5", "Lojas": "#fff8e1",
    "Cobrança": "#e3f2fd", "Réguas": "#fce4ec", "Envios": "#ffebee", "Campanhas": "#f1f8e9",
    "Pagamentos": "#ede7f6", "Dashboard/Relatórios": "#fff3e0", "Plataforma": "#eeeeee", "(sem domínio)": "#ffffff",
}


def modulos() -> dict[str, str]:
    achados = {}
    base = os.path.join(RAIZ, PACOTE)
    for pasta, _, arquivos in os.walk(base):
        for nome in arquivos:
            if nome.endswith(".py") and nome != "__init__.py":
                caminho = os.path.join(pasta, nome)
                achados[os.path.relpath(caminho, base)[:-3].replace(os.sep, ".")] = caminho
    return achados


def imports(mods: dict[str, str]) -> dict[str, set[str]]:
    grafo = {}
    for mod, caminho in mods.items():
        pacote = mod.rsplit(".", 1)[0] if "." in mod else ""
        deps = set()
        for no in ast.walk(ast.parse(open(caminho, encoding="utf-8").read())):
            if isinstance(no, ast.ImportFrom):
                if no.level:
                    partes = pacote.split(".") if pacote else []
                    partes = partes[: len(partes) - (no.level - 1)] if no.level > 1 else partes
                    origem = ".".join(partes + ([no.module] if no.module else []))
                elif (no.module or "").startswith(PACOTE + "."):
                    origem = no.module[len(PACOTE) + 1 :]
                else:
                    continue
                for alias in no.names:
                    alvo = f"{origem}.{alias.name}".strip(".")
                    deps.add(alvo if alvo in mods else origem)
        grafo[mod] = {d for d in deps if d in mods and d != mod}
    return grafo


def viola(origem: str, destino: str) -> bool:
    # routers.comum não é router (peças HTTP compartilhadas): o .importlinter permite importá-lo
    return destino.startswith("routers.") and destino != "routers.comum" and origem != "main"


def main() -> None:
    mods = modulos()
    grafo = imports(mods)
    linhas = ["digraph deps {", '  graph [rankdir=LR, fontname="Helvetica", fontsize=11, nodesep=0.15, ranksep=1.2];',
              '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
              '  edge [color="#9e9e9e", arrowsize=0.5];']
    por_dominio: dict[str, list[str]] = {}
    for mod in mods:
        por_dominio.setdefault(DOMINIO.get(mod, "(sem domínio)"), []).append(mod)
    for i, (dominio, lista) in enumerate(sorted(por_dominio.items())):
        linhas.append(f'  subgraph cluster_{i} {{ label="{dominio}"; style="filled"; color="#bdbdbd"; fillcolor="{CORES.get(dominio, "#fff")}";')
        for mod in sorted(lista):
            linhas.append(f'    "{mod}" [fillcolor="white"];')
        linhas.append("  }")
    for origem in sorted(grafo):
        if origem == "main":
            continue  # main importa todos os routers; só polui o desenho
        for destino in sorted(grafo[origem]):
            if destino in ("models", "database", "deps", "schemas", "config", "timezone"):
                continue  # dependências de plataforma que todo mundo usa
            attr = ' [color="#d32f2f", penwidth=1.6]' if viola(origem, destino) else ""
            linhas.append(f'  "{origem}" -> "{destino}"{attr};')
    linhas.append("}")
    dot = "\n".join(linhas)
    saida = os.path.join("docs", "architecture", "deps.svg")
    subprocess.run(["dot", "-Tsvg", "-o", saida], input=dot.encode(), check=True)
    sem = sorted(m for m in mods if m not in DOMINIO)
    if sem:
        print("Módulos sem domínio definido:", ", ".join(sem), file=sys.stderr)
    print(f"{saida} gerado ({len(mods)} módulos)")


if __name__ == "__main__":
    main()
