"""API de configuração das regras de cobrança: clusters, faixas de atraso,
matriz WhatsApp, parâmetros de multa/juros e janela de pagamento do Dashboard."""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/config/cobranca", tags=["config"])


def _ler_config(db: Session) -> schemas.ConfigCobrancaOut:
    """Lê o estado atual das 4 tabelas de configuração."""
    clusters = db.query(models.ClusterCobranca).order_by(models.ClusterCobranca.valor_min).all()
    faixas = db.query(models.FaixaAtrasoCobranca).order_by(models.FaixaAtrasoCobranca.dia_min).all()
    regras = db.query(models.RegraWhatsapp).all()
    params = db.query(models.ParametrosCobranca).first()

    if params is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Parâmetros de cobrança não encontrados no banco")

    return schemas.ConfigCobrancaOut(
        clusters=[schemas.ClusterConfigOut.model_validate(c) for c in clusters],
        faixas=[schemas.FaixaAtrasoConfigOut.model_validate(f) for f in faixas],
        matriz=[schemas.CelulaMatrizOut(cluster_id=r.cluster_id, faixa_id=r.faixa_id) for r in regras],
        parametros=schemas.ParametrosCobrancaOut.model_validate(params),
    )


@router.get("", response_model=schemas.ConfigCobrancaOut)
def get_config(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _ler_config(db)


@router.put("/clusters", response_model=schemas.ConfigCobrancaOut)
def put_clusters(
    body: list[schemas.ClusterConfigIn],
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    # --- Validações (nada é gravado se falhar) ---
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "É preciso ao menos 1 cluster")

    nomes = [c.nome.strip() for c in body]
    for n in nomes:
        if not n:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nome de cluster não pode ser vazio")

    nomes_lower = [n.lower() for n in nomes]
    if len(nomes_lower) != len(set(nomes_lower)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nomes de cluster repetidos (ignorando maiúsculas)")

    valores = [c.valor_min for c in body]
    for v in valores:
        if v < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"O valor mínimo do cluster não pode ser negativo (recebido: {v})")

    if len(valores) != len(set(valores)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Valores mínimos de cluster repetidos")

    if min(valores) != Decimal(0):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "O primeiro cluster precisa começar em R$ 0,00, senão há clientes sem cluster",
        )

    # ids informados precisam existir no banco
    ids_informados = [c.id for c in body if c.id is not None]
    if ids_informados:
        existentes = {r.id for r in db.query(models.ClusterCobranca.id).filter(models.ClusterCobranca.id.in_(ids_informados)).all()}
        for cid in ids_informados:
            if cid not in existentes:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cluster com id {cid!r} não encontrado")

    # --- Sincronização ---
    ids_novos = {c.id for c in body if c.id is not None}
    # Clusters que estão no banco mas não foram enviados: remover
    # Remover células da matriz antes (SQLite não honra ON DELETE CASCADE)
    db_clusters = db.query(models.ClusterCobranca).all()
    for dc in db_clusters:
        if dc.id not in ids_novos:
            db.query(models.RegraWhatsapp).filter(models.RegraWhatsapp.cluster_id == dc.id).delete()
            db.delete(dc)

    for c in body:
        nome = c.nome.strip()
        if c.id is not None:
            obj = db.query(models.ClusterCobranca).filter(models.ClusterCobranca.id == c.id).one()
            obj.nome = nome
            obj.valor_min = c.valor_min
        else:
            db.add(models.ClusterCobranca(id=str(uuid.uuid4()), nome=nome, valor_min=c.valor_min))

    db.commit()
    return _ler_config(db)


@router.put("/faixas", response_model=schemas.ConfigCobrancaOut)
def put_faixas(
    body: list[schemas.FaixaAtrasoConfigIn],
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    # --- Validações ---
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "É preciso ao menos 1 faixa de atraso")

    nomes = [f.nome.strip() for f in body]
    for n in nomes:
        if not n:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nome de faixa não pode ser vazio")

    nomes_lower = [n.lower() for n in nomes]
    if len(nomes_lower) != len(set(nomes_lower)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nomes de faixa repetidos (ignorando maiúsculas)")

    LIMITE_DIAS = (-365, 100000)
    for f in body:
        if not (LIMITE_DIAS[0] <= f.dia_min <= LIMITE_DIAS[1]):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Dia inicial {f.dia_min} fora do intervalo permitido (-365 a 100000)")
        if f.dia_max is not None:
            if not (LIMITE_DIAS[0] <= f.dia_max <= LIMITE_DIAS[1]):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Dia final {f.dia_max} fora do intervalo permitido (-365 a 100000)")
            if f.dia_max < f.dia_min:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"O dia final ({f.dia_max}) não pode ser menor que o dia inicial ({f.dia_min}) na faixa '{f.nome}'")

    # Ordenar e verificar sobreposições
    ordenadas = sorted(body, key=lambda f: f.dia_min)
    for i, f in enumerate(ordenadas):
        if i > 0:
            anterior = ordenadas[i - 1]
            if anterior.dia_max is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Faixa '{anterior.nome}' não tem dia_max (ilimitada) mas não é a última na ordem",
                )
            if f.dia_min <= anterior.dia_max:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Sobreposição: faixa '{f.nome}' (dia_min={f.dia_min}) sobrepõe '{anterior.nome}' (dia_max={anterior.dia_max})",
                )

    # ids informados precisam existir
    ids_informados = [f.id for f in body if f.id is not None]
    if ids_informados:
        existentes = {r.id for r in db.query(models.FaixaAtrasoCobranca.id).filter(models.FaixaAtrasoCobranca.id.in_(ids_informados)).all()}
        for fid in ids_informados:
            if fid not in existentes:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Faixa com id {fid!r} não encontrada")

    # --- Sincronização ---
    ids_novos = {f.id for f in body if f.id is not None}
    db_faixas = db.query(models.FaixaAtrasoCobranca).all()
    for df in db_faixas:
        if df.id not in ids_novos:
            db.query(models.RegraWhatsapp).filter(models.RegraWhatsapp.faixa_id == df.id).delete()
            db.delete(df)

    for f in body:
        nome = f.nome.strip()
        if f.id is not None:
            obj = db.query(models.FaixaAtrasoCobranca).filter(models.FaixaAtrasoCobranca.id == f.id).one()
            obj.nome = nome
            obj.dia_min = f.dia_min
            obj.dia_max = f.dia_max
        else:
            db.add(models.FaixaAtrasoCobranca(id=str(uuid.uuid4()), nome=nome, dia_min=f.dia_min, dia_max=f.dia_max))

    db.commit()
    return _ler_config(db)


@router.put("/matriz", response_model=schemas.ConfigCobrancaOut)
def put_matriz(
    body: list[schemas.CelulaMatrizIn],
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    # --- Validação: cluster_id e faixa_id precisam existir ---
    cluster_ids = {c.cluster_id for c in body}
    faixa_ids = {c.faixa_id for c in body}

    existentes_cluster = {r.id for r in db.query(models.ClusterCobranca.id).filter(models.ClusterCobranca.id.in_(cluster_ids)).all()}
    for cid in cluster_ids:
        if cid not in existentes_cluster:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cluster com id {cid!r} não encontrado")

    existentes_faixa = {r.id for r in db.query(models.FaixaAtrasoCobranca.id).filter(models.FaixaAtrasoCobranca.id.in_(faixa_ids)).all()}
    for fid in faixa_ids:
        if fid not in existentes_faixa:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Faixa com id {fid!r} não encontrada")

    # --- Substitui todas as células ---
    db.query(models.RegraWhatsapp).delete()
    vistos: set[tuple[str, str]] = set()
    for c in body:
        par = (c.cluster_id, c.faixa_id)
        if par in vistos:
            continue  # ignora duplicadas
        vistos.add(par)
        db.add(models.RegraWhatsapp(id=str(uuid.uuid4()), cluster_id=c.cluster_id, faixa_id=c.faixa_id))

    db.commit()
    return _ler_config(db)


@router.put("/parametros", response_model=schemas.ConfigCobrancaOut)
def put_parametros(
    body: schemas.ParametrosCobrancaIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    # --- Validações (só dos campos enviados) ---
    limites = {
        "juros_mes_percentual": (Decimal(0), Decimal(1000), "Juros ao mês deve estar entre 0% e 1000%"),
        "multa_percentual": (Decimal(0), Decimal(100), "Multa deve estar entre 0% e 100%"),
        "dias_min_juros": (0, 3650, "Carência deve estar entre 0 e 3650 dias"),
        # mesma faixa do filtro dias_janela dos relatórios
        "dias_janela_dashboard": (0, 365, "Janela de pagamento deve estar entre 0 e 365 dias"),
    }
    enviados = body.model_dump(include=body.model_fields_set)
    for campo, valor in enviados.items():
        minimo, maximo, mensagem = limites[campo]
        # só a janela aceita nulo (= qualquer data após a cobrança)
        if valor is None and campo == "dias_janela_dashboard":
            continue
        if valor is None or not (minimo <= valor <= maximo):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, mensagem)

    params = db.query(models.ParametrosCobranca).first()
    if params is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Parâmetros de cobrança não encontrados no banco")

    for campo, valor in enviados.items():
        setattr(params, campo, valor)
    db.commit()
    return _ler_config(db)


def _ler_config_disparo(db: Session) -> models.GlobalDispatchConfig:
    config = db.query(models.GlobalDispatchConfig).filter(models.GlobalDispatchConfig.id == "global").first()
    if config is None:
        config = models.GlobalDispatchConfig(id="global")
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/disparo", response_model=schemas.GlobalDispatchConfigOut)
def get_config_disparo(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _ler_config_disparo(db)


@router.put("/disparo", response_model=schemas.GlobalDispatchConfigOut)
def put_config_disparo(
    body: schemas.GlobalDispatchConfigUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    dias_validos = {"1", "2", "3", "4", "5", "6", "7"}
    dias = [d.strip() for d in body.schedule_days.split(",") if d.strip()]
    if not dias or any(d not in dias_validos for d in dias):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha ao menos um dia da semana para o disparo")
    try:
        inicio = datetime.strptime(body.schedule_start, "%H:%M")
        fim = datetime.strptime(body.schedule_end, "%H:%M")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Início e fim do disparo devem estar no formato HH:MM") from exc
    if fim <= inicio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O horário de fim deve ser depois do horário de início")
    if not (0 <= body.leads_auto_extract_minutos_antes <= 240):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A extração automática de leads deve ser entre 0 e 240 minutos antes do disparo")
    if not (1 <= body.interval_seconds <= 3600):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O intervalo deve estar entre 1 e 3600 segundos")
    if not (1 <= body.batch_size <= 500):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A quantidade por vez deve estar entre 1 e 500")

    config = _ler_config_disparo(db)
    config.schedule_days = ",".join(dias)
    # Grava sempre HH:MM com zero à esquerda: o worker lê com time.fromisoformat,
    # que recusa "8:00" e derrubaria todo ciclo de disparo.
    config.schedule_start = inicio.strftime("%H:%M")
    config.schedule_end = fim.strftime("%H:%M")
    config.leads_auto_extract = body.leads_auto_extract
    config.leads_auto_extract_minutos_antes = body.leads_auto_extract_minutos_antes
    config.interval_seconds = body.interval_seconds
    config.batch_size = body.batch_size
    db.commit()
    db.refresh(config)
    return config


@router.get("/orcamento", response_model=list[schemas.OrcamentoMesOut])
def get_orcamento(ano: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Orçamento dos 12 meses do ano — meses sem linha cadastrada voltam com
    valor_orcado = 0, pra tela sempre mostrar as 12 linhas."""

    if not (2000 <= ano <= 2100):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ano inválido")
    existentes = {
        o.mes: o for o in db.query(models.OrcamentoMensal).filter(models.OrcamentoMensal.ano == ano).all()
    }
    return [
        schemas.OrcamentoMesOut(ano=ano, mes=mes, valor_orcado=existentes[mes].valor_orcado)
        if mes in existentes
        else schemas.OrcamentoMesOut(ano=ano, mes=mes, valor_orcado=Decimal("0.00"))
        for mes in range(1, 13)
    ]


@router.put("/orcamento", response_model=list[schemas.OrcamentoMesOut])
def put_orcamento(
    ano: int,
    body: list[schemas.OrcamentoMesIn],
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    if not (2000 <= ano <= 2100):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ano inválido")
    meses_informados = [m.mes for m in body]
    if len(meses_informados) != len(set(meses_informados)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mês repetido no orçamento")

    existentes = {
        o.mes: o for o in db.query(models.OrcamentoMensal).filter(models.OrcamentoMensal.ano == ano).all()
    }
    for item in body:
        if item.mes in existentes:
            existentes[item.mes].valor_orcado = item.valor_orcado
        else:
            db.add(models.OrcamentoMensal(ano=ano, mes=item.mes, valor_orcado=item.valor_orcado))
    db.commit()
    return get_orcamento(ano, db=db, _user=_user)
