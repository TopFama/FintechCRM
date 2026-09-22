import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    # Só o admin pode criar/listar/excluir outros usuários (ver routers/users.py);
    # fora isso, um usuário criado pelo admin acessa o sistema normalmente, igual ao admin.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MetaToken(Base):
    __tablename__ = "meta_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(String)
    token_cifrado: Mapped[str] = mapped_column(String)
    ultimos4: Mapped[str] = mapped_column(String)
    # WABA que o token acessa: de onde se puxam os números. Nulo só em tokens
    # antigos, cadastrados antes de a WABA ser pedida junto com o token.
    waba_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # passive_deletes: sem isso, o SQLAlchemy carrega os números e desvincula
    # (seta meta_token_id = NULL) em vez de deixar o ON DELETE CASCADE do
    # banco excluí-los de verdade (ver WhatsappNumber.meta_token_id).
    numeros: Mapped[list["WhatsappNumber"]] = relationship(back_populates="meta_token", passive_deletes=True)

    @property
    def numeros_vinculados(self) -> int:
        return len(self.numeros)


class WhatsappNumber(Base):
    __tablename__ = "whatsapp_numbers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    waba_id: Mapped[str] = mapped_column(String, index=True)
    phone_number_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_phone_number: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # CASCADE: excluir o token cadastrado (Configurações) leva junto os números
    # que dependiam dele.
    meta_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("meta_tokens.id", ondelete="CASCADE"), nullable=True
    )
    chatwoot_inbox_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    meta_token: Mapped[MetaToken | None] = relationship(back_populates="numeros")

    @property
    def meta_token_nome(self) -> str | None:
        return self.meta_token.nome if self.meta_token else None



class TemplateStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TemplateHeaderType(str, enum.Enum):
    none = "none"
    image = "image"


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, index=True)
    meta_template_name: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="pt_BR")
    category: Mapped[str] = mapped_column(String, default="UTILITY")
    header_type: Mapped[TemplateHeaderType] = mapped_column(
        Enum(TemplateHeaderType), default=TemplateHeaderType.none
    )
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TemplateStatus] = mapped_column(
        Enum(TemplateStatus), default=TemplateStatus.draft
    )
    meta_status_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    meta_template_id: Mapped[str | None] = mapped_column(String, nullable=True)
    waba_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    variables: Mapped[list["TemplateVariable"]] = relationship(
        back_populates="template", cascade="all, delete-orphan", order_by="TemplateVariable.position"
    )


class TemplateVariable(Base):
    __tablename__ = "template_variables"
    __table_args__ = (UniqueConstraint("template_id", "position"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    position: Mapped[int] = mapped_column(Integer)
    internal_name: Mapped[str] = mapped_column(String)
    # Campo do cliente (CAMPOS_CLIENTE) sugerido pra essa variável — só serve
    # de referência na pré-visualização da aba Templates; o mapeamento que
    # realmente vale no envio é o de FaixaVariableMapping, por faixa.
    campo_sugerido: Mapped[str | None] = mapped_column(String, nullable=True)

    template: Mapped[Template] = relationship(back_populates="variables")


class Faixa(Base):
    __tablename__ = "faixas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Último mapeamento coluna-da-planilha -> campo usado num upload, guardado só
    # para pré-preencher os selects na próxima vez (a planilha real pode ter
    # cabeçalhos diferentes a cada upload, então o mapeamento é reconferido
    # sempre, nunca fixo desde a criação da faixa).
    upload_field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Cada envio é um par (número, template) com disparo próprio — uma faixa
    # sincronizada a partir de uma faixa de atraso (ver POST
    # /faixas/sincronizar-faixas-atraso) nasce sem nenhum envio, e o disparo
    # fica pausado até alguém atribuir ao menos um em "Faixas".
    envios: Mapped[list["FaixaEnvio"]] = relationship(
        back_populates="faixa", cascade="all, delete-orphan"
    )
    variable_mappings: Mapped[list["FaixaVariableMapping"]] = relationship(
        back_populates="faixa", cascade="all, delete-orphan"
    )


class FaixaEnvio(Base):
    """Um par (número de WhatsApp, template) atribuído a uma faixa — o que
    antes era 'a faixa tem um template e uma lista de números' virou 'a
    faixa tem vários desses pares', cada um com seu próprio agendamento
    (DispatchConfig), pensado pra WABAs diferentes cobrando em paralelo.
    Todos os envios ativos de uma faixa disputam a mesma fila (QueueItem):
    cada item só é reservado por um envio (ver worker.run_dispatch_cycle),
    então nenhum cliente é cobrado duas vezes por números diferentes."""

    __tablename__ = "faixa_envios"
    __table_args__ = (UniqueConstraint("faixa_id", "whatsapp_number_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"))
    # CASCADE: excluir o número (Configurações) tira ele da faixa, sem
    # precisar excluir a faixa nem os demais envios.
    whatsapp_number_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_numbers.id", ondelete="CASCADE"))
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    faixa: Mapped[Faixa] = relationship(back_populates="envios")
    whatsapp_number: Mapped[WhatsappNumber] = relationship()
    template: Mapped[Template] = relationship()
    dispatch_config: Mapped["DispatchConfig | None"] = relationship(
        back_populates="envio", uselist=False, cascade="all, delete-orphan"
    )


class FaixaVariableMapping(Base):
    """Mapeamento variável -> fonte, por par (faixa, template): uma faixa com
    mais de um template ativo (um por FaixaEnvio) tem um conjunto de
    mapeamentos por template, todos compartilhados entre os envios que usam
    aquele template nessa faixa."""

    __tablename__ = "faixa_variable_mappings"
    __table_args__ = (UniqueConstraint("faixa_id", "template_id", "template_variable_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"))
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    template_variable_id: Mapped[str] = mapped_column(ForeignKey("template_variables.id"))
    fonte_tipo: Mapped[str] = mapped_column(String, default="coluna", server_default="coluna")
    column_name: Mapped[str | None] = mapped_column(String, nullable=True)
    expressao: Mapped[str | None] = mapped_column(String, nullable=True)

    faixa: Mapped[Faixa] = relationship(back_populates="variable_mappings")
    template: Mapped[Template] = relationship()
    template_variable: Mapped[TemplateVariable] = relationship()


class QueueStatus(str, enum.Enum):
    pending = "pending"
    reserved = "reserved"
    sent = "sent"
    error = "error"
    invalid_phone = "invalid_phone"


class QueueItem(Base):
    __tablename__ = "cobranca_fila"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"), index=True)
    codigo_cliente: Mapped[str] = mapped_column(String, index=True)
    nome: Mapped[str] = mapped_column(String, default="")
    cpf: Mapped[str] = mapped_column(String, default="")
    valor: Mapped[str | None] = mapped_column(String, nullable=True)
    celular: Mapped[str] = mapped_column(String, index=True)
    celular_original: Mapped[str] = mapped_column(String)
    variables_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[QueueStatus] = mapped_column(Enum(QueueStatus), default=QueueStatus.pending, index=True)
    # SET NULL: excluir o número não apaga o histórico de envio, só perde a
    # referência de qual número específico mandou.
    whatsapp_number_id: Mapped[str | None] = mapped_column(
        ForeignKey("whatsapp_numbers.id", ondelete="SET NULL"), nullable=True
    )
    whatsapp_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    faixa: Mapped[Faixa] = relationship()
    whatsapp_number: Mapped["WhatsappNumber | None"] = relationship()


class UploadLog(Base):
    __tablename__ = "upload_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"))
    filename: Mapped[str] = mapped_column(String)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_phone_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    faixa: Mapped[Faixa] = relationship()


class InvalidPhoneRecord(Base):
    """Relatório de clientes cuja planilha trouxe telefone fora do padrão
    55DD9XXXXXXXX (ou com menos dígitos que o mínimo esperado)."""

    __tablename__ = "telefones_invalidos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"), index=True)
    codigo_cliente: Mapped[str] = mapped_column(String, index=True)
    celular_original: Mapped[str] = mapped_column(String)
    celular_normalizado: Mapped[str | None] = mapped_column(String, nullable=True)
    motivo: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    faixa: Mapped[Faixa] = relationship()


class DispatchConfig(Base):
    __tablename__ = "dispatch_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_envio_id: Mapped[str] = mapped_column(ForeignKey("faixa_envios.id", ondelete="CASCADE"), unique=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5)
    batch_size: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    force_run: Mapped[bool] = mapped_column(Boolean, default=False)

    envio: Mapped[FaixaEnvio] = relationship(back_populates="dispatch_config")


class GlobalDispatchConfig(Base):
    """Configuração única (singleton, id fixo) de janela de disparo — antes era
    por FaixaEnvio, virou global porque não fazia sentido dois envios da mesma
    operação atirarem em horários diferentes. Também guarda a extração
    automática de leads pouco antes do disparo começar (opcional), pra reduzir
    a chance de cobrar quem já pagou mais cedo no mesmo dia."""

    __tablename__ = "global_dispatch_config"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: "global")
    schedule_days: Mapped[str] = mapped_column(String, default="1,2,3,4,5")
    schedule_start: Mapped[str] = mapped_column(String, default="08:00")
    schedule_end: Mapped[str] = mapped_column(String, default="18:30")
    leads_auto_extract: Mapped[bool] = mapped_column(Boolean, default=False)
    leads_auto_extract_minutos_antes: Mapped[int] = mapped_column(Integer, default=15)
    leads_auto_extract_last_run: Mapped[date | None] = mapped_column(Date, nullable=True)


class ErrorLog(Base):
    __tablename__ = "log_erros"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str | None] = mapped_column(ForeignKey("faixas.id"), nullable=True)
    queue_item_id: Mapped[str | None] = mapped_column(ForeignKey("cobranca_fila.id"), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClienteBloqueado(Base):
    """Blacklist: cliente que nunca entra na cobrança, tenha atraso ou não.
    Identificado pelo código SETA (8 dígitos) ou pelo CPF, sempre só dígitos."""

    __tablename__ = "blacklist_clientes"
    __table_args__ = (UniqueConstraint("tipo", "valor"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tipo: Mapped[str] = mapped_column(String)  # "seta" (8 dígitos) ou "cpf" (11 dígitos)
    valor: Mapped[str] = mapped_column(String, index=True)
    motivo: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lead(Base):
    """Retrato de um cliente da base de cobrança no momento em que virou lead
    (faixa, cluster, valor a cobrar, telefone escolhido…). Os dados do cliente
    vêm do SETA e não são atualizados depois; gerar de novo para o mesmo
    cliente/faixa/parcela não duplica."""

    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("codigo_cliente", "faixa", "vencimento_mais_antigo"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    codigo_cliente: Mapped[str] = mapped_column(String, index=True)  # código SETA de 8 dígitos
    nome: Mapped[str] = mapped_column(String, default="")
    cpf: Mapped[str | None] = mapped_column(String, nullable=True)
    celular: Mapped[str | None] = mapped_column(String, nullable=True)  # 55DD9XXXXXXXX; None = sem telefone válido
    celular_origem: Mapped[str | None] = mapped_column(String, nullable=True)
    celular_original: Mapped[str | None] = mapped_column(String, nullable=True)
    cluster: Mapped[str] = mapped_column(String, index=True)
    faixa: Mapped[str] = mapped_column(String, index=True)
    faixa_compra: Mapped[str | None] = mapped_column(String, nullable=True)
    qtd_compras: Mapped[int] = mapped_column(Integer, default=0)
    dias_atraso: Mapped[int] = mapped_column(Integer)
    qtd_parcelas: Mapped[int] = mapped_column(Integer, default=0)
    valor_em_aberto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    valor_cobrar: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    vencimento_mais_antigo: Mapped[date] = mapped_column(Date)
    # Delimitadas por vírgula nas duas pontas (",49,12,") para filtrar com LIKE
    # em qualquer banco; ver schemas.LeadOut.
    lojas: Mapped[str] = mapped_column(String, default=",")
    portadores: Mapped[str] = mapped_column(String, default=",")
    status_cliente: Mapped[str] = mapped_column(String, default="")
    spc_restricao: Mapped[str] = mapped_column(String, default="indeterminado")
    spc_data_consulta: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, default="novo", index=True)  # "novo" ou "cobrado"
    cobrado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    parcelas: Mapped[list["LeadParcela"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class LeadParcela(Base):
    """Snapshot das parcelas em aberto que entraram na cobrança do lead no
    momento de sua criação."""

    __tablename__ = "lead_parcelas"
    __table_args__ = (UniqueConstraint("lead_id", "titulo_codigo"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    titulo_codigo: Mapped[str] = mapped_column(String, index=True)
    empresa: Mapped[str] = mapped_column(String)
    vencimento: Mapped[date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    valor_cobrar: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    lead: Mapped[Lead] = relationship(back_populates="parcelas")


class IntegracaoGoogle(Base):
    """Conta Google conectada por OAuth2 (uma só). Guarda o refresh token
    cifrado, para gerar access tokens sem pedir consentimento de novo."""

    __tablename__ = "integracao_google"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    refresh_token_cifrado: Mapped[str] = mapped_column(String)
    connected_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- Configuração das regras de cobrança ------------------------------------


class ClusterCobranca(Base):
    """Segmentos de cliente configuráveis (antes hardcoded em cobranca_regras.py)."""

    __tablename__ = "config_clusters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(String)
    valor_min: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    regras: Mapped[list["RegraWhatsapp"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class FaixaAtrasoCobranca(Base):
    """Faixas de atraso configuráveis (antes hardcoded em cobranca_regras.py)."""

    __tablename__ = "config_faixas_atraso"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(String)
    dia_min: Mapped[int] = mapped_column(Integer)
    dia_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    regras: Mapped[list["RegraWhatsapp"]] = relationship(
        back_populates="faixa", cascade="all, delete-orphan"
    )


class RegraWhatsapp(Base):
    """Matriz cluster × faixa que recebe cobrança por WhatsApp."""

    __tablename__ = "config_regras_whatsapp"
    __table_args__ = (UniqueConstraint("cluster_id", "faixa_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("config_clusters.id", ondelete="CASCADE"))
    faixa_id: Mapped[str] = mapped_column(ForeignKey("config_faixas_atraso.id", ondelete="CASCADE"))

    cluster: Mapped[ClusterCobranca] = relationship(back_populates="regras")
    faixa: Mapped[FaixaAtrasoCobranca] = relationship(back_populates="regras")


class ConfiguracaoChatwoot(Base):
    """Credenciais da conta Chatwoot usada para enviar cobrança pelas inboxes
    vinculadas aos números (WhatsappNumber.chatwoot_inbox_id) — tabela de uma
    linha única, no mesmo espírito do token da Meta: cadastrada pela tela de
    Configurações, nunca em .env."""

    __tablename__ = "config_chatwoot"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    base_url: Mapped[str] = mapped_column(String)
    account_id: Mapped[str] = mapped_column(String)
    api_access_token_cifrado: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ParametrosCobranca(Base):
    """Parâmetros de multa e juros — tabela de uma linha única."""

    __tablename__ = "config_parametros"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    juros_mes_percentual: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    multa_percentual: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    dias_min_juros: Mapped[int] = mapped_column(Integer)


class OrcamentoMensal(Base):
    """Orçamento (em BRL) de gasto com disparo de WhatsApp por mês/ano —
    comparado no Dashboard com o custo real das conversas (Meta Pricing
    Analytics, ver Tarefa 6) pra mostrar a linha de progressão do mês."""

    __tablename__ = "orcamento_mensal"
    __table_args__ = (UniqueConstraint("ano", "mes", name="uq_orcamento_ano_mes"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int] = mapped_column(Integer)  # 1-12
    valor_orcado: Mapped[Decimal] = mapped_column(Numeric(12, 2))
