import asyncio
import time
import os
import threading
from datetime import datetime, date
import tempfile
from fastapi.testclient import TestClient
import unittest.mock

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_deadlock"
os.environ["JWT_SECRET"] = "segredo-de-teste-longo-e-seguro"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["COOKIE_SECURE"] = "false"

from cryptography.fernet import Fernet
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.main import app
from app.database import SessionLocal, engine
from app import models
from sqlalchemy import text

client = TestClient(app)

def setup_module():
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)

def teardown_module():
    models.Base.metadata.drop_all(bind=engine)

def _criar_dados_base(codigo="00000001", celular="5511999990001"):
    db = SessionLocal()
    try:
        faixa = db.get(models.Faixa, "faixa-teste-dl")
        if not faixa:
            faixa = models.Faixa(id="faixa-teste-dl", name="Faixa DL", tipo=models.TIPO_REGUA)
            db.add(faixa)
            db.commit()

        item = models.QueueItem(
            id=f"item-dl-{codigo}",
            faixa_id="faixa-teste-dl",
            codigo_cliente=codigo,
            celular=celular,
            celular_original=celular[2:],
            status=models.QueueStatus.sent,
            sent_at=datetime.utcnow(),
            whatsapp_message_id=f"chatwoot:1:{int(codigo)}",
        )
        lead = models.Lead(
            id=f"lead-dl-{codigo}",
            faixa="Faixa DL",
            campanha_id="",
            codigo_cliente=codigo,
            nome=f"Cliente DL {codigo}",
            celular=celular,
            cluster="ESPECIAL",
            dias_atraso=10,
            vencimento_mais_antigo=date(2023, 1, 1),
            status="cobrado",
            cobrado_em=item.sent_at,
        )
        db.add(item)
        db.add(lead)
        db.commit()
    finally:
        db.close()

def test_lock_timeout_real():
    _criar_dados_base(codigo="00000009")

    conn_a = engine.connect()
    trans_a = conn_a.begin()
    conn_a.execute(text("UPDATE leads SET status='novo' WHERE codigo_cliente='00000009'"))
    
    t0 = time.time()
    try:
        db_b = SessionLocal()
        try:
            db_b.execute(text("UPDATE leads SET status='cobrado' WHERE codigo_cliente='00000009'"))
            db_b.commit()
            assert False, "Deveria ter disparado timeout!"
        except Exception as exc:
            db_b.rollback()
            t1 = time.time()
            dt = t1 - t0
            assert 4.0 <= dt <= 8.0, f"Tempo incorreto de lock_timeout: {dt}s"
            assert "timeout" in str(exc).lower() or "canceling statement" in str(exc).lower() or "lock_timeout" in str(exc).lower()
        finally:
            db_b.close()
    finally:
        trans_a.rollback()
        conn_a.close()

def test_concorrencia_deadlock_event_loop_fica_livre():
    _criar_dados_base(codigo="00000010")

    conn_a = engine.connect()
    trans_a = conn_a.begin()
    conn_a.execute(text("UPDATE leads SET status='novo' WHERE codigo_cliente='00000010'"))

    resultados_api = []
    
    def _chamar_webhook():
        payload = {
            "event": "message_updated",
            "id": 10,
            "status": "failed",
            "content_attributes": {"external_error": "Mensagem erro 10"},
        }
        try:
            resp = client.post("/chatwoot/webhook", json=payload)
            resultados_api.append(("webhook", resp.status_code))
        except Exception as e:
            resultados_api.append(("webhook", 500))
            
    thread_webhook = threading.Thread(target=_chamar_webhook)
    thread_webhook.start()

    time.sleep(1) 

    t0 = time.time()
    resp_health = client.get("/health")
    t1 = time.time()
    resultados_api.append(("health", resp_health.status_code, t1 - t0))

    trans_a.rollback()
    conn_a.close()
    thread_webhook.join()

    health_result = [r for r in resultados_api if r[0] == "health"][0]
    assert health_result[1] == 200
    assert health_result[2] < 1.0, "O Event Loop bloqueou: api/health demorou > 1s"

def test_webhook_idempotente_duplicado():
    _criar_dados_base(codigo="00000011")
    
    payload = {
        "event": "message_updated",
        "id": 11,
        "status": "failed",
        "content_attributes": {"external_error": "Falha repetida"},
    }
    
    resp1 = client.post("/chatwoot/webhook", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["action"] == "marked_error", resp1.json()

    resp2 = client.post("/chatwoot/webhook", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["action"] == "item_not_found"

    db = SessionLocal()
    try:
        erros = db.query(models.ErrorLog).filter(models.ErrorLog.queue_item_id == "item-dl-00000011").all()
        assert len(erros) == 1, "Webhook processou duas vezes criando 2 logs!"
    finally:
        db.close()

def test_cenario_a_dois_webhooks_diferentes():
    _criar_dados_base(codigo="00000012")
    _criar_dados_base(codigo="00000013")
    
    import threading
    resultados = []
    
    def chamar(id_msg):
        payload = {"event": "message_updated", "id": id_msg, "status": "failed", "content_attributes": {"external_error": "Erro"}}
        resp = client.post("/chatwoot/webhook", json=payload)
        resultados.append((id_msg, resp.status_code, resp.json()))
        
    t1 = threading.Thread(target=chamar, args=(12,))
    t2 = threading.Thread(target=chamar, args=(13,))
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    assert len(resultados) == 2
    for res in resultados:
        assert res[1] == 200
        assert res[2]["action"] == "marked_error"

def test_cenario_b_dois_webhooks_mesmo_cliente():
    _criar_dados_base(codigo="00000014")
    
    import threading
    resultados = []
    
    def chamar():
        payload = {"event": "message_updated", "id": 14, "status": "failed", "content_attributes": {"external_error": "Erro"}}
        resp = client.post("/chatwoot/webhook", json=payload)
        resultados.append(resp.json()["action"])
        
    t1 = threading.Thread(target=chamar)
    t2 = threading.Thread(target=chamar)
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    acoes = sorted(resultados)
    assert "marked_error" in acoes
    assert len(acoes) == 2

def test_cenario_c_webhook_mais_sincronizador_concorrendo():
    _criar_dados_base(codigo="00000015")
    from app import telefones_invalidos as ti
    
    db = SessionLocal()
    try:
        conf = db.query(models.ConfiguracaoChatwoot).first()
        if not conf:
            conf = models.ConfiguracaoChatwoot(base_url="https://x", account_id="1", api_access_token_cifrado="cifrado")
            db.add(conf)
            db.commit()
    finally:
        db.close()
        
    class FakeClient:
        async def obter_mensagem(self, conversation_id: int, message_id: int):
            await asyncio.sleep(1)
            return {"content_attributes": {"external_error": "Mensagem erro 15 sync"}}

    import threading
    resultados = []
    
    def chamar_webhook():
        time.sleep(0.2) 
        payload = {"event": "message_updated", "id": 15, "status": "failed", "content_attributes": {"external_error": "Mensagem erro 15 web"}}
        resp = client.post("/chatwoot/webhook", json=payload)
        resultados.append(("webhook", resp.json()["action"]))
        
    def rodar_sync():
        with unittest.mock.patch.object(ti.chatwoot_client, "is_configured", return_value=True), \
             unittest.mock.patch.object(ti.chatwoot_client, "cliente_configurado", return_value=FakeClient()):
            db_sync = SessionLocal()
            try:
                ti._proxima_sincronizacao = datetime.min
                ti._ultimo_id = ""
                alt = asyncio.run(ti.sincronizar_retornos_chatwoot(db_sync))
                resultados.append(("sync", alt))
            finally:
                db_sync.close()

    t_web = threading.Thread(target=chamar_webhook)
    t_sync = threading.Thread(target=rodar_sync)
    
    t_sync.start()
    t_web.start()
    
    t_sync.join()
    t_web.join()
    
    dict_res = dict(resultados)
    assert dict_res["webhook"] == "marked_error"
    assert dict_res["sync"] == 0

if __name__ == "__main__":
    setup_module()
    test_lock_timeout_real()
    test_concorrencia_deadlock_event_loop_fica_livre()
    test_webhook_idempotente_duplicado()
    test_cenario_a_dois_webhooks_diferentes()
    test_cenario_b_dois_webhooks_mesmo_cliente()
    test_cenario_c_webhook_mais_sincronizador_concorrendo()
    print("OK")
