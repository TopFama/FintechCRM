"""Imagem de cabeçalho do template dentro do limite da Meta (5 MB): a função
de otimização (utils/imagem.py) e o upload em duas etapas quando precisa
comprimir (subir → ver a versão otimizada → aprovar ou descartar).

Rodar: PYTHONPATH=. .venv/bin/python tests/test_otimizacao_imagem.py
"""

import io
import os
import random
import tempfile

from cryptography.fernet import Fernet
from PIL import Image

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_img")
os.environ["JWT_SECRET"] = "segredo-do-teste-de-imagem-1234567890"
os.environ["ADMIN_PASSWORD"] = "senha-teste-imagem-987"
MEDIA = tempfile.mkdtemp()
os.environ["MEDIA_DIR"] = MEDIA
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.utils import imagem  # noqa: E402

LIMITE = imagem.LIMITE_BYTES
random.seed(7)


def arte(largura, altura, modo="RGB", ruido=0):
    """Imagem parecida com uma arte real (degradê + formas) e, se pedido, ruído
    de foto — ruído é o que faz o arquivo ficar grande."""
    img = Image.new("RGB", (largura, altura))
    img.putdata([((x * 255) // largura, (y * 255) // altura, 120) for y in range(altura) for x in range(largura)]) \
        if largura * altura <= 400_000 else img.paste((30, 90, 200), (0, 0, largura, altura))
    if ruido:
        img = Image.blend(img, Image.effect_noise((largura, altura), ruido).convert("RGB"), 0.5)
    return img.convert(modo)


def codificar(img, formato, **kw):
    saida = io.BytesIO()
    img.save(saida, formato, **kw)
    return saida.getvalue()


def abrir(dados):
    img = Image.open(io.BytesIO(dados))
    img.load()
    return img


# --- utils/imagem.otimizar ---

# 1. Já cabe e está no formato aceito: guardada exatamente como veio
png_pequeno = codificar(arte(40, 30, "RGBA"), "PNG")
r = imagem.otimizar(png_pequeno)
assert not r.comprimida and r.conteudo == png_pequeno and r.extensao == ".png"
jpg_pequeno = codificar(arte(400, 300), "JPEG", quality=90)
r = imagem.otimizar(jpg_pequeno)
assert not r.comprimida and r.conteudo == jpg_pequeno and r.extensao == ".jpg"

# 2. Foto JPEG grande demais: menor perda possível (mesma resolução, qualidade alta)
foto = arte(3000, 2200, ruido=40)
foto_grande = codificar(foto, "JPEG", quality=100, subsampling=0)
assert len(foto_grande) > LIMITE, len(foto_grande)
r = imagem.otimizar(foto_grande)
assert r.comprimida and r.extensao == ".jpg" and len(r.conteudo) <= LIMITE, len(r.conteudo)
assert (r.largura, r.altura) == (3000, 2200), (r.largura, r.altura)
assert r.qualidade >= 82, r.qualidade
assert abrir(r.conteudo).mode == "RGB"

# 3. Ruído pesado demais para caber só baixando a qualidade: reduz a resolução só o necessário
ruidosa = codificar(arte(5200, 4000, ruido=120), "JPEG", quality=100, subsampling=0)
assert len(ruidosa) > LIMITE
r = imagem.otimizar(ruidosa)
assert r.comprimida and len(r.conteudo) <= LIMITE and r.extensao == ".jpg"
assert r.largura < 5200 and r.largura > 2000, r.largura
assert abs(r.largura / r.altura - 5200 / 4000) < 0.01
# a busca pela escala para perto do limite, não reduz à toa
assert len(r.conteudo) > LIMITE * 0.8, len(r.conteudo)

# 4. PNG opaco grande: sem transparência, vira JPEG de qualidade alta
png_opaco = codificar(arte(2600, 2000, ruido=40), "PNG")
assert len(png_opaco) > LIMITE
r = imagem.otimizar(png_opaco)
assert r.comprimida and r.extensao == ".jpg" and len(r.conteudo) <= LIMITE and r.formato_original == "PNG"

# 5. PNG com transparência de verdade: continua PNG (sem perder o fundo transparente)
transparente = arte(2600, 2000, "RGBA", ruido=40)
transparente.putalpha(Image.linear_gradient("L").resize((2600, 2000)))
png_transparente = codificar(transparente, "PNG")
assert len(png_transparente) > LIMITE
r = imagem.otimizar(png_transparente)
assert r.comprimida and r.extensao == ".png" and len(r.conteudo) <= LIMITE
final = abrir(r.conteudo)
assert final.mode == "RGBA" and final.getchannel("A").getextrema()[0] < 255
assert r.qualidade is None

# 6. Formatos que a Meta recusa mesmo pequenos: CMYK, WebP, paleta
r = imagem.otimizar(codificar(arte(200, 100, "CMYK"), "JPEG", quality=90))
assert r.comprimida and r.extensao == ".jpg" and abrir(r.conteudo).mode == "RGB"
r = imagem.otimizar(codificar(arte(200, 100), "WEBP", quality=90))
assert r.comprimida and r.extensao == ".jpg" and r.formato_original == "WEBP"
r = imagem.otimizar(codificar(arte(200, 100, "RGBA"), "WEBP", lossless=True))
assert r.extensao == ".jpg"  # alfa todo opaco não conta como transparência
r = imagem.otimizar(codificar(arte(200, 100).convert("P"), "PNG"))
assert r.comprimida and r.extensao == ".png" and abrir(r.conteudo).mode == "RGB"

# 7. Foto de celular deitada (EXIF de rotação): sai já na orientação certa
exif = Image.Exif()
exif[0x0112] = 6
r = imagem.otimizar(codificar(arte(400, 200), "JPEG", quality=90, exif=exif))
assert r.comprimida and (r.largura, r.altura) == (200, 400)
assert abrir(r.conteudo).getexif().get(0x0112, 1) == 1

# 8. Arquivo que não é imagem, formato fora da lista e arquivo grande demais para processar
for ruim in (b"isto nao e imagem", codificar(arte(50, 50), "GIF")):
    try:
        imagem.otimizar(ruim)
        raise AssertionError("devia recusar")
    except imagem.ImagemInvalida as exc:
        assert ".jpg, .png ou .webp" in str(exc)
# arquivo pequeno, mas de 64 MP: recusado antes de decodificar os pixels
try:
    imagem.otimizar(codificar(Image.new("1", (8000, 8000)), "PNG"))
    raise AssertionError("devia recusar")
except imagem.ImagemInvalida as exc:
    assert "resolução grande demais" in str(exc)
try:
    imagem.otimizar(b"0" * (imagem.LIMITE_ENTRADA_BYTES + 1))
    raise AssertionError("devia recusar")
except imagem.ImagemInvalida as exc:
    assert "30 MB" in str(exc)

# --- Endpoints: subir → validar → aprovar ou descartar ---

client = TestClient(app)
client.__enter__()  # roda o lifespan (migrations e admin)
db = SessionLocal()
db.query(models.Template).filter(models.Template.meta_template_name.like("teste_img_%")).delete(synchronize_session=False)
tpl = models.Template(name="Com imagem", meta_template_name="teste_img_1", header_type=models.TemplateHeaderType.image,
                      body_text="Oi {{1}}")
outro = models.Template(name="Outro", meta_template_name="teste_img_2", header_type=models.TemplateHeaderType.image)
sem_cabecalho = models.Template(name="Sem imagem", meta_template_name="teste_img_3")
db.add_all([tpl, outro, sem_cabecalho])
db.commit()
TID, OUTRO_ID, SEM_ID = tpl.id, outro.id, sem_cabecalho.id
db.close()

login = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": "senha-teste-imagem-987"})
assert login.status_code == 200, login.text
H = {"Authorization": f"Bearer {login.json()['access_token']}"}


def subir(nome, dados, template_id=TID):
    return client.post(f"/templates/{template_id}/image", headers=H, files={"file": (nome, dados, "application/octet-stream")})


def image_url():
    s = SessionLocal()
    try:
        return s.get(models.Template, TID).image_url
    finally:
        s.close()


# 9. Imagem que cabe: vai direto para o template, sem etapa de validação
resp = subir("logo.png", png_pequeno)
assert resp.status_code == 200, resp.text
assert resp.json()["pendente"] is None
assert resp.json()["template"]["image_url"].startswith(f"/media/{TID}.png?v=")
assert open(os.path.join(MEDIA, f"{TID}.png"), "rb").read() == png_pequeno

# 10. Imagem grande: volta a versão otimizada para validar, e o template NÃO muda ainda
antes = image_url()
resp = subir("foto.jpg", foto_grande)
assert resp.status_code == 200, resp.text
pendente = resp.json()["pendente"]
assert pendente and pendente["tamanho_original"] == len(foto_grande) and pendente["tamanho_final"] <= LIMITE
assert pendente["formato_final"] == "JPEG" and pendente["qualidade"] >= 82
assert image_url() == antes
previa = client.get(pendente["url_previa"])
assert previa.status_code == 200 and len(previa.content) == pendente["tamanho_final"]

# 11. Aprovou: a otimizada vira a imagem do template (e o .png antigo sai)
resp = client.post(f"/templates/{TID}/image/confirmar", headers=H, json={"token": pendente["token"]})
assert resp.status_code == 200, resp.text
assert resp.json()["image_url"].startswith(f"/media/{TID}.jpg?v=")
assert os.path.getsize(os.path.join(MEDIA, f"{TID}.jpg")) == pendente["tamanho_final"]
assert not os.path.exists(os.path.join(MEDIA, f"{TID}.png"))
assert client.get(pendente["url_previa"]).status_code == 404
# a mesma aprovação de novo: já foi usada
resp = client.post(f"/templates/{TID}/image/confirmar", headers=H, json={"token": pendente["token"]})
assert resp.status_code == 410 and "suba a imagem de novo" in resp.json()["detail"]

# 12. Recusou: a otimizada é apagada e o template continua com a imagem anterior
antes = image_url()
pendente = subir("foto.jpg", foto_grande).json()["pendente"]
resp = client.delete(f"/templates/{TID}/image/pendente", headers=H, params={"token": pendente["token"]})
assert resp.status_code == 204
assert image_url() == antes
assert not os.listdir(os.path.join(MEDIA, "pendentes"))
assert client.delete(f"/templates/{TID}/image/pendente", headers=H, params={"token": pendente["token"]}).status_code == 204

# 13. Token de outro template ou forjado não vale
pendente = subir("foto.jpg", foto_grande).json()["pendente"]
for template_id, token in ((OUTRO_ID, pendente["token"]), (TID, "../../etc/passwd"), (TID, pendente["token"] + "x")):
    resp = client.post(f"/templates/{template_id}/image/confirmar", headers=H, json={"token": token})
    assert resp.status_code == 400, (template_id, token, resp.text)

# 14. Recusas na subida: extensão, conteúdo que não é imagem, template sem cabeçalho de imagem, sem login
assert subir("arte.gif", png_pequeno).status_code == 400
resp = subir("falsa.png", b"nao sou png")
assert resp.status_code == 400 and "válida" in resp.json()["detail"]
assert subir("logo.png", png_pequeno, SEM_ID).status_code == 400
assert client.post(f"/templates/{TID}/image", files={"file": ("a.png", png_pequeno)}).status_code == 401

client.__exit__(None, None, None)
print("OK")
