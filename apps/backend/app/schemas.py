from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from .models import QueueStatus, TemplateHeaderType, TemplateStatus


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Números ---


class WhatsappNumberCreate(BaseModel):
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    label: str = ""


class WhatsappNumberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    label: str
    active: bool
    created_at: datetime


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
    waba_id: str
    variables: list[TemplateVariableIn] = []
    submit_to_meta: bool = False


class TemplateVariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    internal_name: str


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


# --- Faixas ---


class FaixaVariableMappingIn(BaseModel):
    template_variable_id: str
    column_name: str


class FaixaCreate(BaseModel):
    name: str
    template_id: str
    whatsapp_number_ids: list[str]
    variable_mappings: list[FaixaVariableMappingIn]


class FaixaVariableMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_variable_id: str
    column_name: str


class DispatchConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    interval_seconds: int
    batch_size: int
    schedule_days: str
    schedule_start: str
    schedule_end: str
    active: bool
    last_run_at: datetime | None = None


class DispatchConfigUpdate(BaseModel):
    interval_seconds: int = 5
    batch_size: int = 3
    schedule_days: str = "1,2,3,4,5"
    schedule_start: str = "08:00"
    schedule_end: str = "18:30"
    active: bool = True


class FaixaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    template_id: str
    active: bool
    created_at: datetime
    template: TemplateOut
    variable_mappings: list[FaixaVariableMappingOut] = []
    dispatch_config: DispatchConfigOut | None = None
    upload_field_mapping: dict = {}


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    faixa_id: str
    codigo_cliente: str
    codigo_tipo: str
    nome: str
    valor: str | None
    celular: str
    status: QueueStatus
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None


# --- Upload da planilha da faixa ---


class UploadColumnsOut(BaseModel):
    columns: list[str]


class UploadFieldMapping(BaseModel):
    """Qual coluna real da planilha (pelo cabeçalho) alimenta cada campo.
    Escolhido pelo usuário via lista suspensa a cada upload, já que o
    cabeçalho pode variar de planilha para planilha."""

    celular: str
    codigo_cliente: str
    nome: str | None = None
    valor: str | None = None
    variables: dict[str, str] = {}  # template_variable_id -> nome da coluna


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


class DispatchReportItemOut(BaseModel):
    codigo_cliente: str
    faixa: str
    nome: str
    valor: str | None
    telefone: str
    enviado_em: datetime


class DashboardSummary(BaseModel):
    total_pendentes: int
    total_enviados: int
    total_erros: int
    total_telefones_invalidos: int
    por_faixa: list[dict]
    erros_recentes: list[dict]


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
    valor_cobrar: Decimal  # o que vai no template: parcelas da cobrança com multa e juros (atraso >= 3 dias)
    vencimento_mais_antigo: date
    lojas: list[str]
    portadores: list[str]
    spc_restricao: str  # sim / nao / indeterminado
    spc_data_consulta: date | None = None  # só preenchida na listagem, para os clientes da página


class ClientesCobrancaPage(BaseModel):
    total: int
    itens: list[ClienteCobrancaOut]


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


class RelatorioCobrancaOut(BaseModel):
    clusters: list[str]
    faixas: list[str]
    quantidade: MatrizQuantidadeOut
    quantidade_com_restricao_spc: MatrizQuantidadeOut


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


class LeadsMarcarCobrados(BaseModel):
    ids: list[str]


# --- Google e lojas ---


class GoogleStatusOut(BaseModel):
    configurado: bool
    conectado: bool
    email: str | None
    redirect_uri: str  # a mesma que precisa estar cadastrada no cliente OAuth do Google


class GoogleAutorizacaoOut(BaseModel):
    url: str


class LojaOut(BaseModel):
    filial: str  # código de 2 caracteres (ft.empresa)
    nome_com_cod: str | None
    regional: str | None
    estado: str | None
    cluster_inad: str | None
    cluster_populacao: str | None


class LojaFiltrosOut(BaseModel):
    regionais: list[str]
    estados: list[str]
    clusters_inad: list[str]
    clusters_populacao: list[str]
