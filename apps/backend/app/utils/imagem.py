"""Imagem de cabeçalho de template dentro do limite da Meta (5 MB, JPEG ou PNG,
8 bits RGB/RGBA). Vale para os dois canais: pela Meta a imagem sobe como
mídia; pelo Chatwoot vai só o link, e quem baixa e aplica o limite é a Meta.

Imagem que já cabe e está num formato aceito é guardada como veio (nenhuma
perda). Fora disso, re-codifica na ordem de menor perda: PNG sem perda →
JPEG com a maior qualidade que couber → reduzir a resolução só o necessário."""

import io
import math
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

# 5 MB da Meta com folga (a Meta não diz se o MB é 1000² ou 1024²)
LIMITE_BYTES = 5_000_000
# Teto do que se aceita receber antes de otimizar (protege a memória do backend)
LIMITE_ENTRADA_BYTES = 30 * 1024 * 1024
# Resolução máxima aceita (60 MP, ~240 MB em memória já decodificada)
LIMITE_PIXELS = 60_000_000

FORMATOS_ACEITOS = ("JPEG", "PNG", "WEBP")
_QUALIDADE_MAXIMA = 95
# Abaixo disso compensa mais reduzir a resolução do que borrar a imagem
_QUALIDADE_MINIMA = 82
_QUALIDADE_REDUZIDA = 88
_LADO_MINIMO = 320


class ImagemInvalida(ValueError):
    """Mensagem segura para mostrar ao usuário."""


@dataclass
class ImagemOtimizada:
    conteudo: bytes
    extensao: str  # ".jpg" ou ".png"
    comprimida: bool
    tamanho_original: int
    largura_original: int
    altura_original: int
    largura: int
    altura: int
    formato_original: str
    qualidade: int | None  # JPEG re-codificado; None em PNG ou sem mudança


def _abrir(conteudo: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(conteudo), formats=FORMATOS_ACEITOS)
        # open só lê o cabeçalho: confere a resolução antes de decodificar os pixels
        if img.width * img.height > LIMITE_PIXELS:
            raise ImagemInvalida("Imagem com resolução grande demais — reduza as dimensões e envie de novo")
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise ImagemInvalida("Arquivo não é uma imagem .jpg, .png ou .webp válida") from exc
    return img


def _precisa_recodificar(img: Image.Image) -> bool:
    if img.format not in ("JPEG", "PNG"):
        return True
    # Meta: só 8 bits RGB/RGBA; P, L, CMYK, 16 bits etc. são convertidos
    if img.mode not in ("RGB", "RGBA"):
        return True
    orientacao = img.getexif().get(0x0112, 1)
    return orientacao != 1


def _normalizar(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    tem_transparencia = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if tem_transparencia:
        img = img.convert("RGBA")
        if img.getchannel("A").getextrema()[0] == 255:  # alfa todo opaco: não é transparência de verdade
            img = img.convert("RGB")
    else:
        img = img.convert("RGB")
    return img


def _png(img: Image.Image) -> bytes:
    saida = io.BytesIO()
    img.save(saida, "PNG", optimize=True)
    return saida.getvalue()


def _png_rapido(img: Image.Image) -> bytes:
    # Só para a busca da escala: optimize=True é bem mais lento (no fim fica a
    # menor das duas versões, então o que coube aqui continua cabendo)
    saida = io.BytesIO()
    img.save(saida, "PNG", compress_level=6)
    return saida.getvalue()


def _jpeg(img: Image.Image, qualidade: int) -> bytes:
    saida = io.BytesIO()
    # 4:4:4 nas qualidades altas: não borra texto/cores fortes da arte
    img.save(saida, "JPEG", quality=qualidade, optimize=True, progressive=True,
             subsampling=0 if qualidade >= 90 else 2)
    return saida.getvalue()


def _maior_qualidade_que_cabe(img: Image.Image, minima: int, limite: int) -> tuple[bytes, int] | None:
    dados = _jpeg(img, _QUALIDADE_MAXIMA)
    if len(dados) <= limite:
        return dados, _QUALIDADE_MAXIMA  # caso mais comum: foto que só passou do limite pelo formato/qualidade
    dados = _jpeg(img, minima)
    if len(dados) > limite:
        return None  # nem na qualidade mínima: é caso de reduzir a resolução
    melhor = (dados, minima)
    baixo, alto = minima + 1, _QUALIDADE_MAXIMA - 1
    while baixo <= alto:
        meio = (baixo + alto) // 2
        dados = _jpeg(img, meio)
        if len(dados) <= limite:
            melhor, baixo = (dados, meio), meio + 1
        else:
            alto = meio - 1
    return melhor


def _reduzida(img: Image.Image, escala: float) -> Image.Image:
    tamanho = (max(1, round(img.width * escala)), max(1, round(img.height * escala)))
    return img.resize(tamanho, Image.Resampling.LANCZOS)


def _maior_escala_que_cabe(
    img: Image.Image, codificar, limite: int, tamanho_cheio: int
) -> tuple[bytes, Image.Image] | None:
    """A maior resolução cujo arquivo cabe no limite. O tamanho do arquivo
    cresce mais ou menos com a área, então a busca binária começa perto da
    estimativa (raiz de limite/tamanho) em vez de percorrer de 0 a 1."""
    escala_minima = min(1.0, _LADO_MINIMO / max(img.width, img.height))
    estimativa = math.sqrt(limite / tamanho_cheio)
    baixo, alto = max(escala_minima, estimativa * 0.75), min(1.0, estimativa * 1.25)
    melhor = None
    reduzida = _reduzida(img, baixo)
    dados = codificar(reduzida)
    if len(dados) <= limite:
        melhor = (dados, reduzida)
    else:
        baixo, alto = escala_minima, baixo
    for _ in range(5):  # intervalo já estreito: 5 passos dão ~1,5% de precisão na escala
        meio = (baixo + alto) / 2
        reduzida = _reduzida(img, meio)
        dados = codificar(reduzida)
        if len(dados) <= limite:
            melhor, baixo = (dados, reduzida), meio
        else:
            alto = meio
    if melhor is None:
        reduzida = _reduzida(img, escala_minima)
        dados = codificar(reduzida)
        if len(dados) <= limite:
            melhor = (dados, reduzida)
    return melhor


def otimizar(conteudo: bytes, limite: int = LIMITE_BYTES) -> ImagemOtimizada:
    if len(conteudo) > LIMITE_ENTRADA_BYTES:
        raise ImagemInvalida(f"Imagem maior que {LIMITE_ENTRADA_BYTES // (1024 * 1024)} MB — envie um arquivo menor")
    original = _abrir(conteudo)
    base = dict(
        tamanho_original=len(conteudo), largura_original=original.width, altura_original=original.height,
        formato_original=original.format,
    )

    if len(conteudo) <= limite and not _precisa_recodificar(original):
        ext = ".jpg" if original.format == "JPEG" else ".png"
        return ImagemOtimizada(conteudo, ext, False, largura=original.width, altura=original.height,
                               qualidade=None, **base)

    img = _normalizar(original)
    transparente = img.mode == "RGBA"

    def resultado(dados: bytes, ext: str, final: Image.Image, qualidade: int | None) -> ImagemOtimizada:
        return ImagemOtimizada(dados, ext, True, largura=final.width, altura=final.height,
                               qualidade=qualidade, **base)

    # 1. Sem perda: PNG otimizado (quem veio em PNG ou precisa de transparência)
    tamanho_png = None
    if original.format == "PNG" or transparente:
        dados = _png(img)
        if len(dados) <= limite:
            return resultado(dados, ".png", img, None)
        tamanho_png = len(dados)

    if transparente:
        # JPEG perderia a transparência: só resta reduzir a resolução, sem perda por pixel
        achado = _maior_escala_que_cabe(img, _png_rapido, limite, tamanho_png)
        if achado:
            otimizado = _png(achado[1])
            return resultado(min(otimizado, achado[0], key=len), ".png", achado[1], None)
        raise ImagemInvalida("Não foi possível deixar a imagem dentro de 5 MB — envie uma imagem menor")

    # 2. JPEG na maior qualidade que couber, na resolução original
    achado_q = _maior_qualidade_que_cabe(img, _QUALIDADE_MINIMA, limite)
    if achado_q:
        return resultado(achado_q[0], ".jpg", img, achado_q[1])

    # 3. Reduzir a resolução só o necessário, com qualidade boa
    tamanho_cheio = len(_jpeg(img, _QUALIDADE_REDUZIDA))
    achado = _maior_escala_que_cabe(img, lambda i: _jpeg(i, _QUALIDADE_REDUZIDA), limite, tamanho_cheio)
    if achado:
        return resultado(achado[0], ".jpg", achado[1], _QUALIDADE_REDUZIDA)
    raise ImagemInvalida("Não foi possível deixar a imagem dentro de 5 MB — envie uma imagem menor")
