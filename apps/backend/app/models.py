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


TIPO_REGUA = "regua"
TIPO_CAMPANHA = "campanha"
TIPO_REMARKETING = "remarketing"
TIPOS_FAIXA = (TIPO_REGUA, TIPO_CAMPANHA, TIPO_REMARKETING)


class Faixa(Base):
    __tablename__ = "faixas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # O que a faixa é: "regua" (faixa de atraso, régua de cobrança),
    # "campanha" (faixa própria de uma campanha) ou "remarketing" (segmento do
    # Renegocie). Só a régua aparece em Faixas, recebe planilha e conta como
    # faixa de atraso; campanha e remarketing ficam na tela Campanhas.
    tipo: Mapped[str] = mapped_column(String, default="regua", server_default="regua", index=True)
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
    # Faixa de remarketing do Renegocie: recebe clientes pelo agendador, nunca
    # por planilha. None nas faixas de atraso.
    remarketing: Mapped["RemarketingSegmento | None"] = relationship(
        primaryjoin="Faixa.id == RemarketingSegmento.faixa_id", uselist=False, viewonly=True, lazy="selectin"
    )

    # Faixa de uma campanha (tela Campanhas): também não recebe planilha.
    campanha: Mapped["Campanha | None"] = relationship(
        primaryjoin="Faixa.id == Campanha.faixa_id", uselist=False, viewonly=True, lazy="selectin"
    )

    @property
    def remarketing_segmento(self) -> str | None:
        return self.remarketing.segmento if self.remarketing else None

    @property
    def campanha_id(self) -> str | None:
        return self.campanha.id if self.campanha else None

    @property
    def descricao(self) -> str | None:
        if self.remarketing:
            return DESCRICOES_REMARKETING.get(self.remarketing.segmento)
        if self.campanha:
            return "Campanha: recebe os clientes pelos filtros da campanha, sem planilha."
        return None


DESCRICOES_REMARKETING = {
    "SO_IDENTIFICOU": "Clientes que entraram no Renegocie com CPF e data de nascimento, mas não chegaram a ver a proposta.",
    "VIU_PROPOSTA": "Clientes que simularam proposta no Renegocie e não fecharam, ou fecharam e tiveram a proposta cancelada.",
    "ACORDO_ATIVO": "Clientes com acordo lançado no SETA ainda ativo, com a entrada (primeira parcela do RE) vencida e em aberto.",
}


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
    # parado à mão (Relatórios → Pendentes): não envia e não some da fila
    cancelled = "cancelled"


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
    # Lojas do cliente no mesmo formato de Lead.lojas (",01,07,"), pra pausa
    # por loja; vazio (",") quando o item veio de planilha sem Lead do cliente.
    lojas: Mapped[str] = mapped_column(String, default=",", server_default=",")
    # Faixa de atraso do cliente quando o item é de campanha/remarketing (a
    # fila é da faixa própria delas): é por ela que o Dashboard agrupa "Por
    # faixa". Nulo nos itens da régua (a própria faixa já é a de atraso).
    faixa_atraso: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    faixa: Mapped[Faixa] = relationship()
    whatsapp_number: Mapped["WhatsappNumber | None"] = relationship()


class PausaEnvio(Base):
    """Pausa temporária e reversível do envio dos pendentes de um cliente, de
    uma faixa (régua) ou de uma loja. Não mexe no status dos itens: vale para
    o que já está na fila e para o que entrar depois, enquanto estiver ativa
    (encerrada_em nulo e `ate` nulo ou ainda não passado, em GMT-3)."""

    __tablename__ = "pausas_envio"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # "cliente" (codigo_cliente de 8 dígitos) | "faixa" (faixa_id) | "loja" (filial)
    escopo: Mapped[str] = mapped_column(String, index=True)
    valor: Mapped[str] = mapped_column(String)
    motivo: Mapped[str] = mapped_column(Text)
    ate: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    encerrada_por: Mapped[str | None] = mapped_column(String, nullable=True)


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
    remarketing_last_run: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Ritmo de disparo único pra toda a operação (antes era por envio).
    interval_seconds: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    batch_size: Mapped[int] = mapped_column(Integer, default=3, server_default="3")


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
    cliente/faixa/parcela não duplica. Lead de campanha (`campanha_id`
    preenchido) é separado do da régua: fica na faixa de atraso do cliente,
    mas marca o envio da campanha."""

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint(
            "codigo_cliente", "faixa", "vencimento_mais_antigo", "campanha_id", name="uq_leads_cliente_faixa_parcela"
        ),
    )

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
    # "" = régua (faixa de atraso); id da campanha quando o envio foi da campanha.
    # Sem FK: campanha nunca é apagada (excluir = arquivar) e "" não é nulo, pra
    # unicidade valer também nos leads da régua.
    campanha_id: Mapped[str] = mapped_column(String, default="", server_default="", index=True)
    # Lead de campanha já passou pela régua da faixa (dia seguinte ao envio).
    regua_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class Loja(Base):
    """Base de lojas (uma linha por filial), migrada da aba "Lojas" da
    planilha Bases_Fintech. `cluster_cobradora` diz qual cobradora atende a
    loja (SYSCOB, MJ...); vazio = loja sem cobradora."""

    __tablename__ = "lojas"

    filial: Mapped[str] = mapped_column(String(4), primary_key=True)  # ft.empresa (2 caracteres)
    nome_com_cod: Mapped[str | None] = mapped_column(String, nullable=True)
    regional: Mapped[str | None] = mapped_column(String, nullable=True)
    estado: Mapped[str | None] = mapped_column(String(2), nullable=True)
    cluster_cobradora: Mapped[str | None] = mapped_column(String, nullable=True)
    cluster_inad: Mapped[str | None] = mapped_column(String, nullable=True)
    cluster_populacao: Mapped[str | None] = mapped_column(String, nullable=True)


class IntegracaoRenegocie(Base):
    """Conexão com o portal TopFamaRenegocie (mesma VPS), de onde vêm os
    clientes de remarketing — linha única, cadastrada em Configurações →
    Conexões, nunca em .env. A chave é gerada no admin do Renegocie."""

    __tablename__ = "integracao_renegocie"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    base_url: Mapped[str] = mapped_column(String)
    chave_cifrada: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RemarketingSegmento(Base):
    """Regra de remarketing de um tipo de desistência no Renegocie (só se
    identificou, viu a proposta, cancelou a proposta, acordo sem entrada).
    Cada segmento tem uma faixa própria, onde se atribui número + template
    como em qualquer faixa; os filtros vazios não restringem."""

    __tablename__ = "remarketing_segmentos"

    segmento: Mapped[str] = mapped_column(String, primary_key=True)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id", ondelete="CASCADE"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Até quantos dias depois da desistência o cliente ainda entra.
    janela_dias: Mapped[int] = mapped_column(Integer, default=30)
    # Depois de receber, quantos dias até poder receber de novo neste segmento.
    recontato_dias: Mapped[int] = mapped_column(Integer, default=7)
    cobradoras: Mapped[list] = mapped_column(JSON, default=list)
    faixas_atraso: Mapped[list] = mapped_column(JSON, default=list)
    clusters: Mapped[list] = mapped_column(JSON, default=list)
    valor_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    ultima_execucao: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_resultado: Mapped[dict] = mapped_column(JSON, default=dict)

    faixa: Mapped[Faixa] = relationship()


class Campanha(Base):
    """Campanha de cobrança com filtros e templates próprios (tela Campanhas).
    Como no remarketing, cada campanha tem uma faixa só dela ("Campanha: …"),
    onde ficam os números, templates e variáveis; daí em diante é a fila
    normal (pausas, relatórios, uma cobrança por cliente por dia).

    `filtros` guarda os mesmos filtros da tela Cobrança, com os nomes dos
    parâmetros de /cobranca/clientes (faixa, cluster, loja, cobradora,
    vencimento_de, valor_atraso_min...). `clientes`, quando preenchido, limita
    a base aos códigos SETA da planilha subida na campanha."""

    __tablename__ = "campanhas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(String, unique=True)
    faixa_id: Mapped[str] = mapped_column(ForeignKey("faixas.id", ondelete="CASCADE"), unique=True)
    # "Envio automático": roda sozinha todo dia de disparo entre data_inicio
    # e data_fim (GMT-3, inclusive nas duas pontas; sem data_fim, sem fim).
    # Desligada, só entra na fila pelo "Colocar na fila agora".
    ativa: Mapped[bool] = mapped_column(Boolean, default=False)
    # Legado: "unica" virou período de um dia (data_fim = data_inicio).
    modo: Mapped[str] = mapped_column(String, default="recorrente", server_default="recorrente")
    data_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    filtros: Mapped[dict] = mapped_column(JSON, default=dict)
    clientes: Mapped[list] = mapped_column(JSON, default=list)
    clientes_arquivo: Mapped[str | None] = mapped_column(String, nullable=True)
    # De onde vêm valor, celular e as colunas das variáveis: "seta" (dados do
    # dia no SETA) ou "planilha" (linha da planilha de clientes, por código).
    fonte_valores: Mapped[str] = mapped_column(String, default="seta", server_default="seta")
    planilha_colunas: Mapped[list] = mapped_column(JSON, default=list)
    planilha_linhas: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nulo: cada cliente recebe uma vez por campanha. Com valor: pode receber
    # de novo depois desse número de dias.
    recontato_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ultima_execucao: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultima_execucao_dia: Mapped[date | None] = mapped_column(Date, nullable=True)
    ultimo_resultado: Mapped[dict] = mapped_column(JSON, default=dict)
    arquivada_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # "Parar": pendentes cancelados e envio automático desligado. Some ao
    # religar o envio automático ou colocar na fila de novo.
    parada_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    faixa: Mapped[Faixa] = relationship()


class TokenRevogado(Base):
    """Sessões encerradas pelo "Sair": o token de login continua assinado até
    expirar, então fica aqui até lá e é recusado em get_current_user."""

    __tablename__ = "tokens_revogados"

    jti: Mapped[str] = mapped_column(String, primary_key=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime, index=True)


class PagamentoSeta(Base):
    """Cópia local dos títulos quitados no SETA (status 'B') de quem já foi
    cobrado. Dashboard, Efetividade e Quem pagou leem daqui; o SETA só é
    consultado na sincronização incremental (services/pagamentos_seta.py)."""

    __tablename__ = "pagamentos_seta"

    titulo_codigo: Mapped[str] = mapped_column(String, primary_key=True)
    codigo_cliente: Mapped[str] = mapped_column(String, index=True)
    pagamento: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    rp: Mapped[str] = mapped_column(String, default="")  # R = a receber


class PagamentoSetaCliente(Base):
    """Clientes cujas baixas já estão em pagamentos_seta: a partir de `desde`
    (primeira cobrança) e lidas no SETA até `marca_dagua` (data da última
    leitura). Cliente cobrado que não está aqui é buscado inteiro."""

    __tablename__ = "pagamentos_seta_clientes"

    codigo_cliente: Mapped[str] = mapped_column(String, primary_key=True)
    desde: Mapped[date] = mapped_column(Date)
    marca_dagua: Mapped[date] = mapped_column(Date, index=True)
