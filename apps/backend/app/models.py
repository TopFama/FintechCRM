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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WhatsappNumber(Base):
    __tablename__ = "whatsapp_numbers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    waba_id: Mapped[str] = mapped_column(String, index=True)
    phone_number_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_phone_number: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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

    template: Mapped[Template] = relationship(back_populates="variables")


class Faixa(Base):
    __tablename__ = "faixas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_number_index: Mapped[int] = mapped_column(Integer, default=0)
    # Último mapeamento coluna-da-planilha -> campo usado num upload, guardado só
    # para pré-preencher os selects na próxima vez (a planilha real pode ter
    # cabeçalhos diferentes a cada upload, então o mapeamento é reconferido
    # sempre, nunca fixo desde a criação da faixa).
    upload_field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    template: Mapped[Template] = relationship()
    numbers: Mapped[list["FaixaNumber"]] = relationship(
        back_populates="faixa", cascade="all, delete-orphan"
    )
    variable_mappings: Mapped[list["FaixaVariableMapping"]] = relationship(
        back_populates="faixa", cascade="all, delete-orphan"
    )
    dispatch_config: Mapped["DispatchConfig | None"] = relationship(
        back_populates="faixa", uselist=False, cascade="all, delete-orphan"
    )


class FaixaNumber(Base):
    __tablename__ = "faixa_numbers"
    __table_args__ = (UniqueConstraint("faixa_id", "whatsapp_number_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"))
    whatsapp_number_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_numbers.id"))

    faixa: Mapped[Faixa] = relationship(back_populates="numbers")
    whatsapp_number: Mapped[WhatsappNumber] = relationship()


class FaixaVariableMapping(Base):
    __tablename__ = "faixa_variable_mappings"
    __table_args__ = (UniqueConstraint("faixa_id", "template_variable_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"))
    template_variable_id: Mapped[str] = mapped_column(ForeignKey("template_variables.id"))
    column_name: Mapped[str] = mapped_column(String)

    faixa: Mapped[Faixa] = relationship(back_populates="variable_mappings")
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
    codigo_tipo: Mapped[str] = mapped_column(String)  # "seta" (8 dígitos) ou "cpf"
    nome: Mapped[str] = mapped_column(String, default="")
    valor: Mapped[str | None] = mapped_column(String, nullable=True)
    celular: Mapped[str] = mapped_column(String, index=True)
    celular_original: Mapped[str] = mapped_column(String)
    variables_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[QueueStatus] = mapped_column(Enum(QueueStatus), default=QueueStatus.pending, index=True)
    whatsapp_number_id: Mapped[str | None] = mapped_column(
        ForeignKey("whatsapp_numbers.id"), nullable=True
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
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id"), unique=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5)
    batch_size: Mapped[int] = mapped_column(Integer, default=3)
    schedule_days: Mapped[str] = mapped_column(String, default="1,2,3,4,5")
    schedule_start: Mapped[str] = mapped_column(String, default="08:00")
    schedule_end: Mapped[str] = mapped_column(String, default="18:30")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    force_run: Mapped[bool] = mapped_column(Boolean, default=False)

    faixa: Mapped[Faixa] = relationship(back_populates="dispatch_config")


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
    tipo: Mapped[str] = mapped_column(String)  # "seta" ou "cpf", igual a QueueItem.codigo_tipo
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


class IntegracaoGoogle(Base):
    """Conta Google conectada por OAuth2 (uma só). Guarda o refresh token
    cifrado, para gerar access tokens sem pedir consentimento de novo."""

    __tablename__ = "integracao_google"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    refresh_token_cifrado: Mapped[str] = mapped_column(String)
    connected_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
