"""Montagem do item da fila (QueueItem): de onde vêm as variáveis de cada
template ativo da faixa e em que formato elas ficam gravadas. Usado por
todo caminho que põe cliente na fila (régua automática, campanha,
remarketing, planilha) e pelo "reaplicar variáveis"."""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from . import models
from .utils.leads_xlsx import formatar_codigo, formatar_cpf, primeiro_nome
from .variaveis_template import FonteVariavel, contexto_cliente, resolver_variaveis


def templates_ativos(faixa: models.Faixa) -> dict[str, models.Template]:
    """Templates distintos entre os envios ativos da faixa: qualquer um deles
    pode acabar processando um item da fila (ver worker.run_dispatch_cycle)."""

    return {e.template_id: e.template for e in faixa.envios if e.active and e.template_id}


def avisos_categoria(templates: Iterable[models.Template]) -> list[str]:
    """Aviso de template recategorizado pela Meta e ainda sem Ciente, para quem
    sobe a fila e para o Dashboard (a regra mora em Template.aviso_categoria)."""

    return [
        f'Template "{t.meta_template_name}": {t.aviso_categoria}. Para não ver mais este aviso, '
        "vá em Configurações → Templates e clique em Ciente."
        for t in templates
        if t.aviso_categoria
    ]


def avisos_categoria_das_faixas(faixas: Iterable[models.Faixa]) -> list[str]:
    """Avisos dos templates que podem enviar os itens dessas faixas."""

    templates = {tid: t for f in faixas for tid, t in templates_ativos(f).items()}
    return avisos_categoria(templates.values())


def fontes(faixa: models.Faixa, template: models.Template) -> list[tuple[models.TemplateVariable, FonteVariavel | None]]:
    """De onde vem cada variável do template, pela configuração salva da faixa."""

    mapas = {m.template_variable_id: m for m in faixa.variable_mappings}
    resultado = []
    for v in template.variables:
        m = mapas.get(v.id)
        if m is None:
            resultado.append((v, None))
        elif m.fonte_tipo == "expressao":
            resultado.append((v, FonteVariavel(v.internal_name, "expressao", m.expressao or "")))
        else:
            resultado.append((v, FonteVariavel(v.internal_name, m.fonte_tipo, m.column_name or "")))
    return resultado


def fontes_por_template(faixa: models.Faixa, templates: dict[str, models.Template]) -> dict[str, list]:
    return {tid: fontes(faixa, tpl) for tid, tpl in templates.items()}


def contexto_do_lead(lead: models.Lead, juros=None) -> dict[str, str]:
    """Campos do cadastro do cliente (Lead) para resolver variáveis."""

    return contexto_cliente(
        {
            "codigo": lead.codigo_cliente,
            "nome": lead.nome,
            "cpf": lead.cpf,
            "celular": lead.celular,
            "cluster": lead.cluster,
            "faixa": lead.faixa,
            "dias_atraso": lead.dias_atraso,
            "qtd_parcelas": lead.qtd_parcelas,
            "valor_cobrar": lead.valor_cobrar,
            "valor_em_aberto": lead.valor_em_aberto,
            "vencimento_mais_antigo": lead.vencimento_mais_antigo,
            "parcelas": lead.parcelas,
            "juros": juros,
        }
    )


def contexto_lead_exportado(lead: models.Lead, juros=None) -> dict[str, str]:
    """Contexto do Lead mais as colunas da planilha de leads exportada."""

    # Colunas da planilha de leads exportada vêm primeiro: um mapeamento
    # "coluna Nome" resolve pro primeiro nome, igual ao upload manual dessa planilha.
    contexto = {
        "Codigo": formatar_codigo(lead.codigo_cliente),
        "Nome": primeiro_nome(lead.nome),
        "CPF": formatar_cpf(lead.cpf),
        "Celular": lead.celular or "",
    }
    contexto.update(contexto_do_lead(lead, juros))
    return contexto


def formato_variaveis(por_template: dict[str, dict[str, str]]) -> dict:
    """Faixa com um template ativo: dict "achatado" (formato de sempre). Mais
    de um: um dict por template_id, já que qualquer envio da faixa pode
    processar o item (ver dispatch_service.montar_parametros_envio)."""

    return next(iter(por_template.values())) if len(por_template) == 1 else por_template


def resolver_por_template(fontes_por_tpl: dict[str, list], contexto: dict[str, str]) -> tuple[dict, list[str]]:
    """Resolve as variáveis de cada template. Devolve (variables_json, nomes sem valor)."""

    faltando: list[str] = []
    por_template: dict[str, dict[str, str]] = {}
    for tid, fontes_tpl in fontes_por_tpl.items():
        valores: dict[str, str] = {}
        for v, fonte in fontes_tpl:
            val = resolver_variaveis([fonte], contexto)[v.internal_name] if fonte else ""
            if not val:
                faltando.append(v.internal_name)
            valores[v.internal_name] = val
        por_template[tid] = valores
    return formato_variaveis(por_template), faltando


def novo_item(db: Session, *, erro: str | None = None, **campos) -> models.QueueItem:
    """Cria o item pendente (ou já com erro, para aparecer em Erros com o motivo)."""

    item = models.QueueItem(**campos, status=models.QueueStatus.error if erro else models.QueueStatus.pending)
    if erro:
        item.error_message = erro
    db.add(item)
    return item
