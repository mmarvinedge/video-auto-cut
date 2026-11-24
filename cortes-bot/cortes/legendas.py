"""Legendas no estilo Shorts/TikTok: poucas palavras por vez, MAIÚSCULAS, a palavra falada destacada."""
from pathlib import Path

CABECALHO = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Fala,Arial Black,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

DESTAQUE = r"{\c&H00D7FF&}"   # amarelo (BGR)
NORMAL = r"{\c&HFFFFFF&}"


def _t(s: float) -> str:
    s = max(0.0, s)
    h, r = divmod(s, 3600)
    m, r = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{r:05.2f}"


def _grupos(palavras: list[dict], max_palavras: int = 3, max_chars: int = 18, pausa: float = 0.6) -> list[list[dict]]:
    grupos, atual = [], []
    for p in palavras:
        quebra = atual and (
            len(atual) >= max_palavras
            or len(" ".join(x["w"] for x in atual + [p])) > max_chars
            or p["s"] - atual[-1]["e"] > pausa
            or atual[-1]["w"][-1:] in ".!?"
        )
        if quebra:
            grupos.append(atual)
            atual = []
        atual.append(p)
    if atual:
        grupos.append(atual)
    return grupos


CABECALHO_EDIT = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Brilho,Arial Black,{tam},&H00{cor},&H00{cor},&H00{cor},&H00000000,-1,0,0,0,100,100,{esp},0,1,{borda},0,5,40,40,0,1
Style: Letra,Arial Black,{tam},&H00{clara},&H00{clara},&H00{cor},&H00000000,-1,0,0,0,100,100,{esp},0,1,1.5,0,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _bgr(hex_rgb: str) -> str:
    """'FF2A3A' (RGB, como se escreve no config) -> '3A2AFF' (o ASS guarda ao contrário)."""
    h = hex_rgb.strip().lstrip("#").upper()
    return h[4:6] + h[2:4] + h[0:2]


def gerar_ass_edit(palavras: list[dict], inicio: float, fim: float, destino: Path, y: int,
                   cor: str = "FF1E3C", clara: str = "FFE6EC", tamanho: int = 58) -> Path | None:
    """Legenda de edit: a frase inteira de uma vez, em maiúsculas espaçadas, com brilho neon.

    O brilho são duas camadas do mesmo texto: embaixo, borda grossa e desfocada na cor; em cima,
    a letra clara com contorno fino. Cada grupo entra e sai com fade curto, sem karaokê: no edit a
    fala é para ser lida como frase de efeito, não acompanhada palavra a palavra."""
    dentro = [p for p in palavras if p["e"] > inicio and p["s"] < fim]
    if not dentro:
        return None
    grupos = _grupos(dentro, max_palavras=4, max_chars=22, pausa=0.45)
    eventos = []
    for i, g in enumerate(grupos):
        ini = g[0]["s"]
        ate = g[-1]["e"] + 0.25
        if i + 1 < len(grupos):
            ate = min(ate + 0.3, grupos[i + 1][0]["s"])   # segura até a próxima frase, sem encostar
        texto = " ".join(x["w"] for x in g).upper().replace("{", "").replace("}", "")
        eventos.append((max(ini, inicio), min(ate, fim), texto))
    cor_b, clara_b = _bgr(cor), _bgr(clara)
    linhas = []
    for ini, f, txt in eventos:
        if f <= ini:
            continue
        pos = rf"{{\pos(540,{y})\fad(90,120)"
        linhas.append(f"Dialogue: 0,{_t(ini - inicio)},{_t(f - inicio)},Brilho,,0,0,0,,{pos}\\blur14}}{txt}")
        linhas.append(f"Dialogue: 1,{_t(ini - inicio)},{_t(f - inicio)},Letra,,0,0,0,,{pos}\\blur0.8}}{txt}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(CABECALHO_EDIT.format(tam=tamanho, cor=cor_b, clara=clara_b, esp=4, borda=7)
                       + "\n".join(linhas) + "\n", encoding="utf-8")
    return destino


def gerar_ass(palavras: list[dict], inicio: float, fim: float, destino: Path, y: int) -> Path | None:
    """Gera um .ass com tempos relativos ao início do corte. `y` = altura do centro da legenda."""
    dentro = [p for p in palavras if p["e"] > inicio and p["s"] < fim]
    if not dentro:
        return None
    eventos = []
    for g in _grupos(dentro):
        fim_grupo = g[-1]["e"]
        for i, p in enumerate(g):
            ate = g[i + 1]["s"] if i + 1 < len(g) else fim_grupo + 0.15
            partes = [(DESTAQUE if j == i else NORMAL) + x["w"].upper().replace("{", "").replace("}", "")
                      for j, x in enumerate(g)]
            txt = rf"{{\pos(540,{y})}}" + " ".join(partes)
            eventos.append([p["s"], min(ate, fim), txt])
    # a folga de 0,15s da ultima palavra de um grupo nao pode invadir o grupo seguinte:
    # como todos usam o mesmo \pos, dois eventos ao mesmo tempo sao desenhados um sobre o outro
    for atual, proximo in zip(eventos, eventos[1:]):
        atual[1] = min(atual[1], proximo[0])
    linhas = [f"Dialogue: 0,{_t(ini - inicio)},{_t(f - inicio)},Fala,,0,0,0,,{txt}"
              for ini, f, txt in eventos if f > ini]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(CABECALHO + "\n".join(linhas) + "\n", encoding="utf-8")
    return destino
