"""Só responde a quem chegou por lojastopfama.com.br (ou subdomínio): Host de fora
ou Origin de outro site recebem 403. Sem Origin passa (webhook, /media, healthcheck).

Sem banco: /health e o webhook do Chatwoot (evento ignorado) não tocam nele.
Rodar: PYTHONPATH=. .venv/bin/python tests/test_hosts_permitidos.py
"""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def status(caminho="/health", host=None, origin=None, metodo="get", **kw):
    headers = {}
    if host:
        headers["Host"] = host
    if origin:
        headers["Origin"] = origin
    return getattr(client, metodo)(caminho, headers=headers, **kw).status_code


# 1. Host: o domínio, qualquer subdomínio, a rede local e o endereço interno do proxy passam
for host in ["lojastopfama.com.br", "fintech.lojastopfama.com.br", "chat.lojastopfama.com.br", "a.b.lojastopfama.com.br",
             "FINTECH.LojasTopFama.com.br", "fintech.lojastopfama.com.br.", "localhost:8000", "127.0.0.1:18001", "testserver"]:
    assert status(host=host) == 200, host

# 2. Host de fora, inclusive os que só parecem o domínio
for host in ["evil.com", "lojastopfama.com.br.evil.com", "evil-lojastopfama.com.br", "evillojastopfama.com.br", "lojastopfama.com"]:
    assert status(host=host) == 403, host

# 3. Origin: do domínio e subdomínios passa; de outro site, não; sem Origin passa
assert status(origin="https://fintech.lojastopfama.com.br") == 200
assert status(origin="https://chat.lojastopfama.com.br") == 200
assert status(origin="http://localhost:4174") == 200  # e2e
assert status(origin="https://evil.com") == 403
assert status(origin="https://lojastopfama.com.br.evil.com") == 403
assert status(origin="null") == 403
assert status(host="fintech.lojastopfama.com.br", origin="https://evil.com") == 403
assert status(host="evil.com", origin="https://fintech.lojastopfama.com.br") == 403
assert status() == 200

# 4. Webhook do Chatwoot sem Origin passa (evento ignorado pelo app, não barrado); de outro Host, não
assert status("/chatwoot/webhook", metodo="post", json={}) == 200
assert status("/chatwoot/webhook", host="chat.lojastopfama.com.br", origin="https://chat.lojastopfama.com.br", metodo="post", json={}) == 200
assert status("/chatwoot/webhook", host="evil.com", metodo="post", json={}) == 403

# 5. O 403 sai com os cabeçalhos de CORS da origem permitida (o frontend enxerga o erro)
r = client.get("/health", headers={"Host": "evil.com", "Origin": "https://fintech.lojastopfama.com.br"})
assert r.status_code == 403 and r.json() == {"detail": "Forbidden"}, r.text
assert r.headers["access-control-allow-origin"] == "https://fintech.lojastopfama.com.br", r.headers

print("OK")
