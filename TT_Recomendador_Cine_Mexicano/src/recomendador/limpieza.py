"""Limpieza de texto para BETO, el LLM (JEV) y los embeddings de sinopsis.

Principio: limpiar lo que es ruido (URLs, HTML, espacios, letras repetidas),
pero no destruir señal. Por eso NO se quitan acentos, mayúsculas ni signos de
puntuación en el texto que va a los modelos de lenguaje: BETO y los modelos de
embeddings tienen su propio tokenizador y esa información les sirve. La
normalización agresiva (minúsculas, sin acentos, sin stopwords) solo se aplica
en la representación TF-IDF, dentro del propio vectorizador.

Hallazgos en una muestra de 4,000 reseñas en español (ver docs/Datos_y_limpieza.md):
emojis en 8.7 %, saltos de línea en 17.5 %, letras repetidas ("buenísimaaaa")
en 3.9 %, URLs y HTML en 0.02 %.
"""

from __future__ import annotations

import html
import re
import unicodedata

# --------------------------------------------------------------------------
# Emojis -> palabras. BETO no tiene emojis en su vocabulario (los vuelve [UNK]),
# así que los más frecuentes del corpus se traducen a una palabra en español que
# conserve su carga emocional. El LLM sí los entiende: para él se conservan.
# Lista construida con los 60 emojis más usados en las reseñas en español.
# --------------------------------------------------------------------------
EMOJI_A_TEXTO = {
    "😭": "llorando", "💔": "corazón roto", "👏": "aplausos", "❤": "amor",
    "🔥": "excelente", "🙏": "gracias", "💀": "muerto de risa", "😔": "triste",
    "👍": "bien", "✨": "brillante", "⭐": "estrella", "🌟": "estrella",
    "🥺": "conmovido", "🤣": "risa", "😂": "risa", "😆": "risa", "😞": "decepcionado",
    "😍": "me encanta", "🫶": "amor", "🥹": "conmovido", "😢": "triste",
    "🙌": "celebración", "👌": "perfecto", "😿": "triste", "🤌": "perfecto",
    "💋": "beso", "🥲": "triste", "💗": "amor", "💜": "amor", "🤍": "amor",
    "💕": "amor", "💖": "amor", "🥰": "amor", "😘": "amor", "🙂": "bien",
    "☹": "triste", "😮": "sorpresa", "👎": "malo", "🥀": "triste", "😩": "agobiado",
    "🤨": "desconfianza", "🖕": "odio", "😅": "nervios", "🙄": "fastidio",
    "✊": "fuerza", "😪": "sueño", "🤯": "impactante", "😡": "enojo", "😠": "enojo",
    "🤬": "enojo", "\U0001fae9": "cansado", "🤷": "indiferente", "😴": "aburrido",
    "🥱": "aburrido", "🤮": "asco", "🤢": "asco", "💩": "basura", "🤡": "ridículo",
    "😐": "indiferente", "😑": "indiferente", "😁": "feliz", "😊": "feliz",
    "☺": "feliz", "😃": "feliz", "😄": "feliz", "🤩": "increíble", "💯": "perfecto",
    "🏆": "premio", "😱": "miedo", "😨": "miedo", "😰": "miedo", "😬": "incómodo",
    "🫠": "incómodo", "😳": "sorpresa", "🤔": "duda", "😒": "fastidio",
    "🫂": "abrazo", "💞": "amor", "💓": "amor", "🖤": "amor", "💙": "amor", "💚": "amor",
    "💛": "amor", "🧡": "amor", "😻": "me encanta", "🤗": "abrazo", "😥": "triste",
}

# Modificadores que no aportan significado: tonos de piel, selector de variación,
# unión de emojis (ZWJ) y símbolos de género que acompañan a otro emoji.
_MODIFICADORES = re.compile("[\U0001F3FB-\U0001F3FF️‍♀♂]")
_BANDERA_MX = re.compile("\U0001F1F2\U0001F1FD")  # 🇲🇽
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿\U0001F1E6-\U0001F1FF]"
)
_URL = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_MENCION = re.compile(r"(?<!\w)@\w+")
_HASHTAG = re.compile(r"#(\w+)")
_LETRA_REPETIDA = re.compile(r"([^\W\d_])\1{3,}")  # 4+ veces la misma letra
_SIGNO_REPETIDO = re.compile(r"([!?.¡¿,;:\-*~])\1{3,}")
_ESPACIOS = re.compile(r"\s+")


def normalizar_unicode(texto: str) -> str:
    """NFC (acentos en una sola forma) y espacios raros a espacio normal."""
    texto = unicodedata.normalize("NFC", texto)
    return texto.replace(" ", " ").replace("​", "")


def limpiar_resena(texto, emojis: str = "texto") -> str:
    """Limpia una reseña para un modelo de lenguaje.

    emojis:
        "texto"     los emojis frecuentes se traducen a palabras y el resto se quita (BETO)
        "conservar" se dejan tal cual (LLM)
        "quitar"    se eliminan (TF-IDF)
    """
    if texto is None or (isinstance(texto, float) and texto != texto):
        return ""
    t = normalizar_unicode(html.unescape(str(texto)))
    t = _HTML_TAG.sub(" ", t)
    t = _URL.sub(" ", t)
    t = _MENCION.sub(" ", t)
    t = _HASHTAG.sub(r"\1", t)
    t = _LETRA_REPETIDA.sub(r"\1\1\1", t)   # buenísimaaaaa -> buenísimaaa
    t = _SIGNO_REPETIDO.sub(r"\1\1\1", t)   # !!!!!!! -> !!!
    if emojis != "conservar":
        t = _MODIFICADORES.sub("", t)
        if emojis == "texto":
            t = _BANDERA_MX.sub(" México ", t)
            for emoji, palabra in EMOJI_A_TEXTO.items():
                if emoji in t:
                    t = t.replace(emoji, f" {palabra} ")
        t = _EMOJI.sub(" ", t)
    t = _ESPACIOS.sub(" ", t)  # incluye saltos de línea
    return t.strip()


# --------------------------------------------------------------------------
# Sinopsis
# --------------------------------------------------------------------------
# Notas de crédito que TMDb/IMDb agregan al final: "Written by X", "(Source: Y)".
_CREDITO = re.compile(
    r"(\s*[\(\[]?\s*(written by|source:|fuente:|escrito por|sinopsis de)[^\)\]]*[\)\]]?\s*)$",
    re.IGNORECASE,
)
# Textos de relleno sin contenido argumental.
_RELLENO = re.compile(
    r"^(no overview|we don't have an overview|sin sinopsis|no hay sinopsis|tbd|n/?a)\b",
    re.IGNORECASE,
)
MIN_CARACTERES_SINOPSIS = 40


def limpiar_sinopsis(texto) -> str:
    """Limpia una sinopsis para TF-IDF o embeddings."""
    if texto is None or (isinstance(texto, float) and texto != texto):
        return ""
    t = normalizar_unicode(html.unescape(str(texto)))
    t = _HTML_TAG.sub(" ", t)
    t = _URL.sub(" ", t)
    t = _ESPACIOS.sub(" ", t).strip()
    t = _CREDITO.sub("", t).strip()
    if len(t) >= 2 and t[0] in '"“' and t[-1] in '"”':  # sinopsis entera entre comillas
        t = t[1:-1].strip()
    if _RELLENO.match(t):
        return ""
    return t


def sinopsis_informativa(texto: str, genericas: set | None = None) -> bool:
    """Una sinopsis sirve si tiene contenido argumental.

    Se descartan las muy cortas ("Mexican feature film", "1962 Japanese movie")
    y las genéricas: textos idénticos repetidos en varias películas distintas.
    """
    if not texto or len(texto) < MIN_CARACTERES_SINOPSIS:
        return False
    if genericas and texto in genericas:
        return False
    return True


def texto_util(texto: str, minimo: int = 3) -> bool:
    """Una reseña limpia es útil si conserva al menos `minimo` caracteres con letra."""
    return bool(texto) and sum(c.isalpha() for c in texto) >= minimo
