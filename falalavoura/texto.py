"""Funções de texto em português: normalização, tokens para a busca e
índice de legibilidade (Flesch adaptado para o português).
"""
import re
import unicodedata

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das no na nos nas em por para pra pro pras pros
com sem sob que se e ou mas ja nao sim eu tu ele ela nos vos eles elas meu minha meus
minhas seu sua seus suas esse essa isso este esta isto aquele aquela aquilo ao aos
como quando onde qual quais quanto quanta quantos quantas porque pq tem ter tenho ta
tao muito muita pouco mais menos ser sao foi era estou esta estao fica ficou vai vou
la aqui ai lhe me te mim ti voce voces gente coisa coisas tudo todo toda todos todas
dia dias sobre entre ate depois antes bem tambem so ainda entao assim pode posso deve
devo faz fazer fiz quero queria preciso planta plantas minha lavoura roca
plantar cultivar consigo conseguir pego pegar saber sei fala falar diz dizer
meio certo verdade bom boa uns umas acontecendo acontece olha olhar
""".split())


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos (o agricultor nem sempre digita acento)."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def radical(palavra: str) -> str:
    """Stemmer bem leve: junta plural e diminutivo ("lagartinhas" -> "lagart").

    Não é um stemmer completo (tipo RSLP), mas resolve os casos mais comuns
    da fala da roça sem precisar de biblioteca extra.
    """
    for suf in ("zinhas", "zinhos", "zinha", "zinho", "inhas", "inhos", "inha", "inho"):
        if palavra.endswith(suf) and len(palavra) - len(suf) >= 3:
            palavra = palavra[: -len(suf)]
            break
    for suf, troca in (("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("res", "r"), ("s", "")):
        if palavra.endswith(suf) and len(palavra) > 4:
            palavra = palavra[: -len(suf)] + troca
            break
    if len(palavra) > 5 and palavra[-1] in "aeo":
        palavra = palavra[:-1]
    return palavra


def tokens(texto: str) -> list[str]:
    palavras = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalizar(texto))
    saida = []
    for p in palavras:
        if p in STOPWORDS or len(p) < 2:
            continue
        saida.append(radical(p))
        if "-" in p:  # "lagarta-do-cartucho" também vale como "lagarta" e "cartucho"
            saida.extend(radical(x) for x in p.split("-") if x not in STOPWORDS and len(x) > 2)
    return saida


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")


# ---------------------------------------------------------------------------
# Legibilidade
# ---------------------------------------------------------------------------
_VOGAIS = "aeiouyáéíóúâêôãõàü"


def contar_silabas(palavra: str) -> int:
    """Aproximação: conta grupos de vogais. Ditongos contam como uma sílaba."""
    palavra = palavra.lower()
    grupos = re.findall(f"[{_VOGAIS}]+", palavra)
    return max(1, len(grupos))


def flesch_pt(texto: str) -> float:
    """Índice de Flesch adaptado ao português (Martins et al., 1996).

    IF = 248,835 - 1,015 x (palavras/frases) - 84,6 x (sílabas/palavras)
    Faixas: 75-100 muito fácil, 50-75 fácil, 25-50 difícil, 0-25 muito difícil.
    """
    limpo = re.sub(r"\[[^\]]*\]", " ", texto)          # tira citações [milho#...]
    limpo = re.sub(r"[*_#>`|]", " ", limpo)            # tira markdown
    frases = [f for f in re.split(r"[.!?:\n]+", limpo) if re.search(r"\w", f)]
    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", limpo)
    if not frases or not palavras:
        return 0.0
    silabas = sum(contar_silabas(p) for p in palavras)
    indice = 248.835 - 1.015 * (len(palavras) / len(frases)) - 84.6 * (silabas / len(palavras))
    return round(max(0.0, min(100.0, indice)), 1)


def faixa_flesch(indice: float) -> str:
    if indice >= 75:
        return "muito fácil"
    if indice >= 50:
        return "fácil"
    if indice >= 25:
        return "difícil"
    return "muito difícil"


_EMOJIS = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+ ?")


def sem_emojis(texto: str) -> str:
    """Remove emojis (o app usa um visual limpo, e emoji atrapalha a leitura em voz alta)."""
    return _EMOJIS.sub("", texto)
