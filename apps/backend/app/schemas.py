from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import QueueStatus, TemplateHeaderType, TemplateStatus
from .variaveis_template import CAMPOS_CLIENTE, validar_sintaxe


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_admin: bool = False


# --- Usuários ---


class UserCreate(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v) < 5:
            raise ValueError("Email inválido")
        return v

    @field_validator("password")
    @classmethod
    def validar_senha(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Senha precisa ter pelo menos 8 caracteres")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    is_admin: bool
    created_at: datetime


# --- Meta Tokens ---


class MetaTokenCreate(BaseModel):
    nome: str
    token: str
    waba_id: str


class MetaTokenUpdate(BaseModel):
    nome: str | None = None
    ativo: bool | None = None
    waba_id: str | None = None
    token: str | None = None


class MetaTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    ultimos4: str
    waba_id: str | None
    ativo: bool
    created_at: datetime
    numeros_vinculados: int = 0


class MetaTokenTestResult(BaseModel):
    ok: bool
    detalhe: str


class NumeroMetaOut(BaseModel):
    """Número que a Meta devolve para a WABA do token."""

    phone_number_id: str
    display_phone_number: str
    verified_name: str | None = None
    quality_rating: str | None = None
    status: str | None = None
    cadastrado: bool  # já existe entre os números do portal (mesmo phone_number_id)
    vinculado_a_este_token: bool


class ImportarNumerosIn(BaseModel):
    phone_number_ids: list[str]


class ImportarNumerosOut(BaseModel):
    importados: int  # números novos criados
    vinculados: int  # já cadastrados sem token, agora ligados a este
    ignorados: int  # já cadastrados com outro token (ficam como estão)


# --- Números ---


class WhatsappNumberCreate(BaseModel):
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    label: str = ""
    meta_token_id: str | None = None
    chatwoot_inbox_id: int | None = None


class WhatsappNumberUpdate(BaseModel):
    label: str | None = None
    active: bool | None = None
    meta_token_id: str | None = None
    chatwoot_inbox_id: int | None = None


class WhatsappNumberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    label: str
    active: bool
    created_at: datetime
    meta_token_id: str | None = None
    meta_token_nome: str | None = None
    chatwoot_inbox_id: int | None = None


# --- Templates ---


class TemplateVariableIn(BaseModel):
    position: int
    internal_name: str


class TemplateCreate(BaseModel):
    name: str
    meta_template_name: str
    language: str = "pt_BR"
    category: str = "UTILITY"
    header_type: TemplateHeaderType = TemplateHeaderType.none
    body_text: str
    waba_id: str | None = None
    variables: list[TemplateVariableIn] = []
    submit_to_meta: bool = False


class TemplateVariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    internal_name: str
    campo_sugerido: str | None = None


class TemplateVariableUpdate(BaseModel):
    campo_sugerido: str | None = None

    @field_validator("campo_sugerido")
    @classmethod
    def validar_campo(cls, valor: str | None) -> str | None:
        if valor is not None and valor not in CAMPOS_CLIENTE:
            validos = ", ".join(sorted(CAMPOS_CLIENTE.keys()))
            raise ValueError(f"Campo inválido ({validos})")
        return valor


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    meta_template_name: str
    language: str
    category: str
    header_type: TemplateHeaderType
    image_url: str | None
    body_text: str
    status: TemplateStatus
    meta_status_raw: str | None
    meta_template_id: str | None
    waba_id: str | None
    created_at: datetime
    updated_at: datetime
    variables: list[TemplateVariableOut] = []


class CampoClienteOut(BaseModel):
    campo: str
    rotulo: str
    exemplo: str


# --- Faixas ---


class FaixaVariableMappingIn(BaseModel):
    template_variable_id: str
    column_name: str | None = None
    fonte_tipo: Literal["coluna", "campo_cliente", "expressao"] = "coluna"
    expressao: str | None = None

    @model_validator(mode="after")
    def validar_fonte(self) -> "FaixaVariableMappingIn":
        if self.fonte_tipo == "coluna":
            if not self.column_name or not self.column_name.strip():
                raise ValueError("Tipo 'coluna' exige o preenchimento de 'column_name'")
        elif self.fonte_tipo == "campo_cliente":
            if not self.column_name or self.column_name not in CAMPOS_CLIENTE:
                validos = ", ".join(sorted(CAMPOS_CLIENTE.keys()))
                raise ValueError(
                    f"Tipo 'campo_cliente' exige 'column_name' válido ({validos})"
                )
        elif self.fonte_tipo == "expressao":
            if not self.expressao or not self.expressao.strip():
                raise ValueError("Tipo 'expressao' exige o preenchimento de 'expressao'")
            erro = validar_sintaxe(self.expressao)
            if erro:
                raise ValueError(f"Expressão inválida: {erro}")
        return self


class FaixaCreate(BaseModel):
    """Cria a faixa e, quando um template_id é informado, já atribui o
    primeiro envio (par número+template) — o wizard de criação sempre
    envia isso; sincronizar-faixas-atraso cria só o nome. Mais
    números/templates depois entram por POST /faixas/{id}/envios."""

    name: str
    template_id: str | None = None
    whatsapp_number_ids: list[str] = []
    variable_mappings: list[FaixaVariableMappingIn] = []

    @model_validator(mode="after")
    def validar_envio_inicial(self) -> "FaixaCreate":
        if self.template_id and not self.whatsapp_number_ids:
            raise ValueError("Selecione ao menos um número de envio para o template")
        return self


class DispatchConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interval_seconds: int
    batch_size: int
    active: bool
    last_run_at: datetime | None = None


class DispatchConfigUpdate(BaseModel):
    interval_seconds: int = 5
    batch_size: int = 3
    active: bool = True


class GlobalDispatchConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schedule_days: str
    schedule_start: str
    schedule_end: str
    leads_auto_extract: bool
    leads_auto_extract_minutos_antes: int
    leads_auto_extract_last_run: date | None = None
    interval_seconds: int
    batch_size: int


class GlobalDispatchConfigUpdate(BaseModel):
    schedule_days: str = "1,2,3,4,5"
    schedule_start: str = "08:00"
    schedule_end: str = "18:30"
    leads_auto_extract: bool = False
    leads_auto_extract_minutos_antes: int = 15
    interval_seconds: int = 5
    batch_size: int = 3


class FaixaEnvioCreate(BaseModel):
    """Um novo par (número, template) para uma faixa já existente.
    variable_mappings só é obrigatório na primeira vez que esse template é
    usado nesta faixa — se já existir mapeamento salvo (outro envio já usa
    o mesmo template aqui), pode vir vazio para reaproveitar; se vier
    preenchido, substitui o mapeamento salvo desse (faixa, template)."""

    whatsapp_number_id: str
    template_id: str
    variable_mappings: list[FaixaVariableMappingIn] = []


class FaixaEnvioUpdate(BaseModel):
    whatsapp_number_id: str
    template_id: str
    active: bool = True
    variable_mappings: list[FaixaVariableMappingIn] = []


class FaixaVariableMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str
    template_variable_id: str
    fonte_tipo: str = "coluna"
    column_name: str | None = None
    expressao: str | None = None


class FaixaEnvioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    whatsapp_number_id: str
    whatsapp_number: WhatsappNumberOut
    template_id: str
    template: TemplateOut
    active: bool
    created_at: datetime
    dispatch_config: DispatchConfigOut | None = None


class FaixaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    active: bool
    created_at: datetime
    envios: list[FaixaEnvioOut] = []
    variable_mappings: list[FaixaVariableMappingOut] = []
    upload_field_mapping: dict = {}
    tipo: str = "regua"  # "regua" | "campanha" | "remarketing"
    remarketing_segmento: str | None = None
    campanha_id: str | None = None
    descricao: str | None = None


class SincronizarFaixasAtrasoOut(BaseModel):
    criadas: list[str]
    ja_existentes: list[str]


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    faixa_id: str
    codigo_cliente: str
    nome: str
    cpf: str
    valor: str | None
    celular: str
    status: QueueStatus
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None


class QueueItemPage(BaseModel):
    total: int
    itens: list[QueueItemOut]


# --- Upload da planilha da faixa ---


class UploadColumnsOut(BaseModel):
    columns: list[str]
    sample_row: dict[str, str] | None = None


class UploadFieldMapping(BaseModel):
    """Qual coluna real da planilha (pelo cabeçalho) alimenta cada campo.
    Escolhido pelo usuário via lista suspensa a cada upload, já que o
    cabeçalho pode variar de planilha para planilha."""

    celular: str
    codigo_cliente: str
    nome: str
    cpf: str
    valor: str | None = None
    variables: dict[str, str] = {}  # template_variable_id -> nome da coluna
    expressoes: dict[str, str] = {}  # template_variable_id -> expressao usando cabecalhos da planilha


class UploadResult(BaseModel):
    filename: str
    row_count: int
    accepted_count: int
    rejected_count: int
    invalid_phone_count: int = 0
    rejected_reasons: list[str] = []


# --- Relatórios ---


class InvalidPhoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    faixa_id: str
    codigo_cliente: str
    celular_original: str
    celular_normalizado: str | None
    motivo: str
    created_at: datetime


class InvalidPhonePage(BaseModel):
    total: int
    itens: list[InvalidPhoneOut]


class DispatchReportItemOut(BaseModel):
    codigo_cliente: str
    faixa: str
    nome: str
    valor: str | None
    telefone: str
    enviado_em: datetime


class DispatchReportPage(BaseModel):
    total: int
    itens: list[DispatchReportItemOut]


class FilaReportItemOut(BaseModel):
    """Linha dos relatórios de pendentes e de erros (itens da fila)."""

    lojas: list[str] = []
    # pendente retido por uma pausa ativa (cliente, faixa ou loja)
    pausado: bool = False

    id: str
    codigo_cliente: str
    nome: str
    faixa_id: str
    # Faixa de atraso (régua). Em item de campanha/remarketing, a do cliente
    # (nula em item antigo); o nome da campanha vai em `campanha`.
    faixa: str | None
    campanha: str | None = None
    valor: str | None
    telefone: str
    entrou_em: datetime
    mensagem: str | None = None
    quando: datetime | None = None


class FilaReportPage(BaseModel):
    total: int
    itens: list[FilaReportItemOut]
    # só na aba Pendentes: quantos do total estão retidos por pausa
    total_pausados: int = 0
    # itens sem loja (planilha sem Lead do cliente): pausa por loja não os pega
    total_sem_loja: int = 0


# --- Pausas de envio ---

EscopoPausa = Literal["cliente", "faixa", "loja"]


class PausaEnvioCreate(BaseModel):
    escopo: EscopoPausa
    valor: str
    motivo: str
    ate: date | None = None


class PausaEnvioOut(BaseModel):
    id: str
    escopo: EscopoPausa
    valor: str
    valor_legivel: str
    motivo: str
    ate: date | None
    created_by: str | None
    created_at: datetime
    qtd_retidos: int


class PausaLoteIn(BaseModel):
    escopo: Literal["faixa", "loja"]
    valores: list[str]
    motivo: str
    ate: date | None = None


class OpcaoFilaOut(BaseModel):
    valor: str
    rotulo: str
    qtd_pendentes: int
    pausado: bool


class OpcoesFilaOut(BaseModel):
    faixas: list[OpcaoFilaOut]
    lojas: list[OpcaoFilaOut]


class ReaplicarVariaveisOut(BaseModel):
    atualizados: int
    sem_cadastro: int


class PararEnvioIn(BaseModel):
    escopo: EscopoPausa
    valor: str


class PararEnvioOut(BaseModel):
    qtd: int


class PagosJanelaOut(BaseModel):
    qtd_cobrados: int
    qtd_pagaram: int
    percentual: Decimal
    valor_pago: Decimal
    qtd_em_maturacao: int
    dias_janela: int


class DashboardSummary(BaseModel):
    total_pendentes: int
    total_pausados: int = 0
    total_enviados: int
    total_erros: int
    total_telefones_invalidos: int
    por_faixa: list[dict]
    erros_recentes: list[dict]


class LinhaEfetividadeBase(BaseModel):
    qtd_envios: int
    clientes_cobrados: int
    valor_cobrado: Decimal
    clientes_pagaram: int
    valor_pago: Decimal
    parcelas_cobradas: int
    parcelas_pagas: int
    parcelas_renegociadas: int
    conversao_clientes: Decimal
    recuperacao_valor: Decimal


class LinhaEfetividadeFaixa(LinhaEfetividadeBase):
    faixa: str


class LinhaEfetividadeLoja(LinhaEfetividadeBase):
    loja: str
    loja_nome: str | None = None
    regional: str | None = None
    cluster_inad: str | None = None


class LinhaEfetividadeCampanha(LinhaEfetividadeBase):
    campanha: str  # nome da campanha, ou "Régua de atraso"
    campanha_id: str = ""


class LinhaEfetividadeTotal(LinhaEfetividadeBase):
    pass


class OrcamentoMesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ano: int
    mes: int
    valor_orcado: Decimal


class OrcamentoMesIn(BaseModel):
    mes: int = Field(ge=1, le=12)
    valor_orcado: Decimal = Field(ge=0)


class OrcamentoProgressaoDiaOut(BaseModel):
    data: date
    gasto_acumulado_brl: Decimal


class OrcamentoProgressaoOut(BaseModel):
    de: date
    ate: date
    valor_orcado: Decimal
    valor_gasto_brl: Decimal | None
    motivo_sem_gasto: str | None = None
    dias: list[OrcamentoProgressaoDiaOut]
    avisos: list["AvisoCustoWabaOut"] = []
    gasto_por_numero: list["GastoNumeroOut"] = []


class AvisoCustoWabaOut(BaseModel):
    waba_id: str
    numeros: list[str]
    motivo: str


class GastoNumeroOut(BaseModel):
    numero: str
    gasto_brl: Decimal
    qtd_mensagens: int = 0


class LinhaEfetividadeClienteOut(BaseModel):
    codigo_cliente: str
    nome: str
    faixa: str
    empresa: str
    titulo_codigo: str
    data_cobranca: date | None
    valor_cobrar: Decimal
    pago: bool
    valor_pago: Decimal
    renegociada: bool


class RelatorioEfetividadeOut(BaseModel):
    por_faixa: list[LinhaEfetividadeFaixa]
    por_loja: list[LinhaEfetividadeLoja]
    por_campanha: list[LinhaEfetividadeCampanha] = []
    total: LinhaEfetividadeTotal
    leads_sem_parcelas: int
    dias_janela: int | None = None
    valor_a_pagar_brl: Decimal | None = None


# --- SETA (ERP) ---


class SetaStatusOut(BaseModel):
    configurado: bool
    conectado: bool
    banco: str | None = None
    usuario: str | None = None
    versao: str | None = None
    somente_leitura: bool | None = None
    latencia_ms: int | None = None
    erro: str | None = None


# --- Blacklist ---


class BlacklistCreate(BaseModel):
    documento: str  # código SETA (8 dígitos) ou CPF, com ou sem pontuação
    motivo: str = ""


class BlacklistLoteCreate(BaseModel):
    documentos: list[str]
    motivo: str = ""


class BlacklistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo: str
    valor: str
    motivo: str
    created_at: datetime


class BlacklistLoteResult(BaseModel):
    adicionados: int
    ja_existiam: int
    invalidos: list[str]


# --- Base de cobrança ---


class ClienteCobrancaOut(BaseModel):
    codigo: str
    nome: str
    celular: str | None
    celular_origem: str | None  # de qual campo do SETA veio: telefone2 / telefone1 / telefone3
    celular_original: str | None
    cpfcnpj: str | None
    status: str
    status_descricao: str
    loja_cadastro: str | None
    salario: Decimal | None  # pessoas.faturamento: é o que gera o limite do cliente
    limite_rotativo: Decimal | None
    nascimento: date | None
    cadastro: date | None
    cluster: str
    valor_pago: Decimal
    qtd_compras: int
    faixa_compra: str | None  # 1 a 9 ou 10+; None = sem compra de crediário validada
    ultima_compra: date | None
    faixa: str | None
    dias_atraso: int
    entra_whatsapp: bool
    qtd_titulos: int
    valor_em_aberto: Decimal  # soma de ft.valor de todas as parcelas abertas, sem juros
    qtd_parcelas_cobranca: int  # parcelas vencidas (ou a de amanhã, no lembrete) que entram no valor a cobrar
    valor_cobrar: Decimal  # o que vai no template: parcelas da cobrança com multa e juros (atraso acima da carência)
    valor_atraso_original: Decimal = Decimal(0)  # parcelas já vencidas, sem multa e juros
    valor_atraso_juros: Decimal = Decimal(0)  # parcelas já vencidas, com multa e juros
    vencimento_mais_antigo: date
    lojas: list[str]
    portadores: list[str]
    spc_restricao: str  # sim / nao / indeterminado
    spc_data_consulta: date | None = None  # só preenchida na listagem, para os clientes da página


class ClientesCobrancaPage(BaseModel):
    total: int
    itens: list[ClienteCobrancaOut]


class ClientesCobrancaAsyncOut(BaseModel):
    """A consulta ao SETA por trás da base de cobrança pode levar minutos na
    primeira vez (tabela de títulos com dezenas de milhões de linhas) — ver
    `app/cache.py`. "processing" significa que o cálculo está em segundo
    plano; quem pediu tenta de novo em seguida."""

    status: Literal["ready", "processing"]
    data: ClientesCobrancaPage | None = None


class CobrancaRegrasOut(BaseModel):
    clusters: list[str]
    faixas: list[str]
    faixas_whatsapp: dict[str, list[str]]  # cluster -> faixas que recebem WhatsApp
    primeiro_dia: dict[str, int]  # faixa -> primeiro dia
    faixas_compra: list[str]


class MatrizQuantidadeOut(BaseModel):
    celulas: dict[str, dict[str, int]]  # cluster -> faixa -> clientes
    total_por_cluster: dict[str, int]
    total_por_faixa: dict[str, int]
    total: int


class MatrizValorOut(BaseModel):
    celulas: dict[str, dict[str, Decimal]]  # cluster -> faixa -> valor em aberto
    total_por_cluster: dict[str, Decimal]
    total_por_faixa: dict[str, Decimal]
    total: Decimal


class RelatorioCobrancaOut(BaseModel):
    clusters: list[str]
    faixas: list[str]
    quantidade: MatrizQuantidadeOut
    quantidade_com_restricao_spc: MatrizQuantidadeOut
    valor_em_aberto: MatrizValorOut


class RelatorioCobrancaAsyncOut(BaseModel):
    status: Literal["ready", "processing"]
    data: RelatorioCobrancaOut | None = None



# --- Leads ---


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    codigo_cliente: str
    nome: str
    cpf: str | None
    celular: str | None
    celular_origem: str | None
    cluster: str
    faixa: str
    faixa_compra: str | None
    qtd_compras: int
    dias_atraso: int
    qtd_parcelas: int
    valor_em_aberto: Decimal
    valor_cobrar: Decimal
    vencimento_mais_antigo: date
    lojas: list[str]
    portadores: list[str]
    status_cliente: str
    spc_restricao: str
    spc_data_consulta: date | None
    status: str
    cobrado_em: datetime | None
    created_at: datetime

    @field_validator("lojas", "portadores", mode="before")
    @classmethod
    def _dividir(cls, valor):
        # no banco fica como ",49,12," (ver models.Lead)
        return [v for v in valor.split(",") if v] if isinstance(valor, str) else valor


class LeadsPage(BaseModel):
    total: int
    itens: list[LeadOut]


class LeadsGerarResult(BaseModel):
    criados: int
    ja_existiam: int
    sem_celular: int  # entre os criados: sem telefone válido em nenhum dos campos
    na_fila: int = 0  # entraram na fila de disparo da faixa


class LeadsGerarAsyncOut(BaseModel):
    status: Literal["ready", "processing"]
    data: LeadsGerarResult | None = None


class LeadsMarcarCobrados(BaseModel):
    ids: list[str]


class LeadsExcluir(BaseModel):
    ids: list[str] = []


# --- Google e lojas ---


class GoogleStatusOut(BaseModel):
    configurado: bool
    conectado: bool
    email: str | None
    redirect_uri: str  # a mesma que precisa estar cadastrada no cliente OAuth do Google


class GoogleAutorizacaoOut(BaseModel):
    url: str


# --- Chatwoot ---


class ChatwootStatusOut(BaseModel):
    configurado: bool
    base_url: str | None = None
    account_id: str | None = None


class ChatwootConfigIn(BaseModel):
    base_url: str
    account_id: str
    # Vazio ao editar uma configuração já existente = mantém o token atual
    # (a tela nunca mostra o token salvo de volta, então não tem o que reenviar).
    api_access_token: str | None = None

    @field_validator("base_url", "account_id")
    @classmethod
    def campo_obrigatorio(cls, valor: str) -> str:
        if not valor or not valor.strip():
            raise ValueError("Campo obrigatório")
        return valor.strip()

    @field_validator("api_access_token")
    @classmethod
    def token_sem_espacos(cls, valor: str | None) -> str | None:
        return valor.strip() if valor and valor.strip() else None


class ChatwootTestResult(BaseModel):
    ok: bool
    detalhe: str


class TestarEnvioChatwootIn(BaseModel):
    whatsapp_number_id: str
    celular: str
    variables: dict[str, str] = {}


class LojaOut(BaseModel):
    filial: str  # código de 2 caracteres (ft.empresa)
    nome_com_cod: str | None
    regional: str | None
    estado: str | None
    cluster_cobradora: str | None
    cluster_inad: str | None
    cluster_populacao: str | None


class LojaIn(BaseModel):
    nome_com_cod: str | None = None
    regional: str | None = None
    estado: str | None = None
    cluster_cobradora: str | None = None
    cluster_inad: str | None = None
    cluster_populacao: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _vazio_vira_none(cls, v):
        if isinstance(v, str):
            v = " ".join(v.split())
            return v or None
        return v

    @field_validator("estado")
    @classmethod
    def _estado_maiusculo(cls, v):
        return v.upper() if v else v


class LojaNovaIn(LojaIn):
    filial: str


class SincronizacaoLojasOut(BaseModel):
    novas: int
    atualizadas: int
    sem_mudanca: int


class LojaFiltrosOut(BaseModel):
    regionais: list[str]
    estados: list[str]
    clusters_inad: list[str]
    clusters_populacao: list[str]
    cobradoras: list[str]  # clusters de cobradora + "Sem cobradora", se houver loja sem


# --- Configuração da cobrança ---


class ClusterConfigIn(BaseModel):
    id: str | None = None
    nome: str
    valor_min: Decimal


class FaixaAtrasoConfigIn(BaseModel):
    id: str | None = None
    nome: str
    dia_min: int
    dia_max: int | None = None


class CelulaMatrizIn(BaseModel):
    cluster_id: str
    faixa_id: str


class ParametrosCobrancaIn(BaseModel):
    juros_mes_percentual: Decimal
    multa_percentual: Decimal
    dias_min_juros: int


class ClusterConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    valor_min: Decimal


class FaixaAtrasoConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    dia_min: int
    dia_max: int | None


class CelulaMatrizOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cluster_id: str
    faixa_id: str


class ParametrosCobrancaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    juros_mes_percentual: Decimal
    multa_percentual: Decimal
    dias_min_juros: int


class ConfigCobrancaOut(BaseModel):
    clusters: list[ClusterConfigOut]
    faixas: list[FaixaAtrasoConfigOut]
    matriz: list[CelulaMatrizOut]
    parametros: ParametrosCobrancaOut


class PagamentoClienteOut(BaseModel):
    codigo_cliente: str
    nome: str
    cpf: str | None
    loja: str
    faixa: str
    data_cobranca: date
    valor_cobrado: Decimal
    valor_pago: Decimal
    qtd_titulos_pagos: int
    primeiro_pagamento: date | None
    ultimo_pagamento: date | None


class PagamentosClientesPage(BaseModel):
    total: int
    # a mesma pessoa cobrada em dois dias vira duas linhas; o card do Dashboard conta pessoas
    total_clientes: int
    valor_cobrado: Decimal
    valor_pago: Decimal
    itens: list[PagamentoClienteOut]
