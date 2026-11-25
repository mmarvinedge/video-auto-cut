"""Legendas no estilo Shorts/TikTok: poucas palavras por vez, MAIÚSCULAS, a palavra falada destacada."""
import re
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


# ------------------------------------------------------------------ letreiro (modelos de edit)

LIMPA = re.compile(r"[^\w'\-]+", re.UNICODE)


def _palavra_letreiro(w: str) -> str:
    return LIMPA.sub("", w).strip("-'").upper()


def telas_letreiro(palavras: list[dict], dur: float, est: dict) -> tuple[list[list[dict]], list[tuple], list[tuple]]:
    """Divide a fala de um trecho (tempos já relativos ao começo dele, 0..dur) em telas do letreiro.

    Devolve (telas, janelas, relampagos): as palavras de cada tela; quando cada tela fica no ar;
    e os buracos da fala de pelo menos `relampago_min` segundos, em que o letreiro sai e aparece o
    filme (no modelo Honorable são os relâmpagos de imagem entre as frases)."""
    ps = [p for p in palavras if p["e"] > 0 and p["s"] < dur and _palavra_letreiro(p["w"])]
    # agrupa com a pontuação (um ponto fecha a tela) e só depois limpa
    telas = [[dict(p, w=_palavra_letreiro(p["w"])) for p in t]
             for t in _grupos(ps, max_palavras=est["max_palavras"], max_chars=est["max_chars"], pausa=est["pausa"])]
    janelas = []
    for i, t in enumerate(telas):
        a = max(0.0, t[0]["s"] - 0.04)
        b = t[-1]["e"] + est["segura"]
        if i + 1 < len(telas):
            b = min(b, telas[i + 1][0]["s"] - 0.04)
        janelas.append((round(a, 3), round(min(b, dur), 3)))
    relampagos, ant = [], 0.0
    for a, b in janelas + [(dur, dur)]:
        if a - ant >= est["relampago_min"]:
            relampagos.append((round(ant, 3), round(a, 3)))
        ant = max(ant, b)
    return telas, janelas, relampagos


def gerar_ass_letreiro(telas: list[list[dict]], janelas: list[tuple], destino: Path, est: dict,
                       alto: int = 1920) -> Path | None:
    """O texto do letreiro: cada palavra entra na hora em que é dita, maior, e assenta em 0,1 s;
    as cores se alternam palavra a palavra. O LED e a aberração vêm depois, no ffmpeg.
    `alto`: a altura do quadro numa largura de 1080 (1920 no 9:16, 1350 no 4:5)."""
    if not telas:
        return None
    cores = [_bgr(c) for c in est["cores"]] or ["FFFFFF"]
    pulo = int(round(est["pulo"] * 100))
    linhas = []
    for t, (a, b) in zip(telas, janelas):
        for j, p in enumerate(t):
            ini = a if j == 0 else p["s"]
            fim = t[j + 1]["s"] if j + 1 < len(t) else b
            if fim - ini < 0.01:
                continue
            partes = []
            for k, x in enumerate(t[:j + 1]):
                cor = cores[k % len(cores)]
                novo = rf"\fscx{pulo}\fscy{pulo}\t(0,100,\fscx100\fscy100)" if k == j and pulo != 100 else ""
                partes.append(rf"{{\c&H00{cor}&{novo}}}{x['w']}")
            linhas.append(rf"Dialogue: 0,{_t(ini)},{_t(fim)},Letreiro,,0,0,0,,{{\an5\pos(540,{alto // 2})}}"
                          + " ".join(partes))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: {alto}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Letreiro,{est['fonte']},{est['tamanho']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,{est['espacamento']},0,1,0,0,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(linhas) + "\n", encoding="utf-8")
    return destino


# ------------------------------------------------------------------ legenda em destaque (modelos)
#
# A legenda dos edits de hype ("PEAK DAYS", do Parthedits): cada frase em duas camadas. Em cima, as
# palavras pequenas e brancas, entrando uma a uma no instante em que são ditas ("lend me the strength
# of"); embaixo, as palavras-chave da frase em letra grande e estreita, com degradê de cor e brilho
# ("THE ALL FATHERS"), também entrando quando ditas. Cada frase usa a cor seguinte da paleta.
# O libass não pinta degradê: ele sai de faixas horizontais da mesma linha, cada uma recortada
# (\clip) e com a cor do seu ponto entre o topo e a base.

def frases_destaque(palavras: list[dict], est: dict) -> list[tuple[list[dict], list[dict]]]:
    """As frases da fala, cada uma dividida em (pequenas, grandes): as grandes são as últimas
    palavras, até `max_grandes` palavras, `max_chars_grandes` letras e metade da frase (pelo menos
    uma): "let's get / STARTED", "to me / MY X-MEN", "lend me the strength of / THE ALL FATHERS"."""
    frases = []
    for g in _grupos(palavras, max_palavras=est["max_palavras"], max_chars=est["max_chars"], pausa=est["pausa"]):
        g = [dict(p, w=p["w"].strip()) for p in g if _palavra_letreiro(p["w"])]
        if not g:
            continue
        n = 1                   # no máximo metade da frase: as pequenas em cima nunca somem
        while (n < min(est["max_grandes"], max(1, len(g) // 2))
               and len(" ".join(_palavra_letreiro(p["w"]) for p in g[-(n + 1):])) <= est["max_chars_grandes"]):
            n += 1
        frases.append((g[:-n], g[-n:]))
    return frases


def _mistura(c0: str, c1: str, f: float) -> str:
    a = [int(c0[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(x + (y - x) * f):02X}" for x, y in zip(a, b))


def _pequena(w: str) -> str:
    return w.replace("{", "").replace("}", "").lower()


def gerar_ass_destaque(palavras: list[dict], editor: list[dict], destino: Path, est: dict, y: int,
                       centro: int = 960) -> Path | None:
    """O .ass da legenda em destaque (tempos no vídeo) e do texto do editor (`editor`: palavras
    grandes e brancas, uma por batida, no meio da imagem, `centro`). `y`: altura da linha grande."""
    frases = frases_destaque(palavras, est)
    if not frases and not editor:
        return None
    tam, peq = est["tamanho"], est["tamanho_pequena"]
    faixas = max(2, int(est["faixas"]))
    topo, base = y - tam * 0.42, y + tam * 0.42          # a altura das maiúsculas da linha grande
    y_peq = round(y - tam * 0.55 - peq * 0.6)
    linhas = []

    def grande(texto: str, ini: float, fim: float, cores: tuple[str, str], entra: bool, sai: bool):
        fad = rf"\fad({est['entrada_ms'] if entra else 0},{est['saida_ms'] if sai else 0})"
        cresce = rf"\fscx{est['pulo']}\fscy{est['pulo']}\t(0,{est['entrada_ms']},\fscx100\fscy100)" if entra else ""
        borra = rf"\t({max(0, round((fim - ini) * 1000) - est['saida_ms'])},{round((fim - ini) * 1000)},\blur8)" if sai else ""
        meio = _mistura(*cores, 0.5)
        pos = rf"\an5\pos(540,{y})"
        linhas.append(f"Dialogue: 0,{_t(ini)},{_t(fim)},Brilho,,0,0,0,,"
                      rf"{{{pos}{fad}{cresce}\1c&H00{_bgr(meio)}&\3c&H00{_bgr(meio)}&\alpha&H70&\blur12}}{texto}")
        for k in range(faixas):
            y0 = 0 if k == 0 else round(topo + (base - topo) * k / faixas)
            y1 = 1920 * 2 if k == faixas - 1 else round(topo + (base - topo) * (k + 1) / faixas)
            cor = _bgr(_mistura(*cores, (k + 0.5) / faixas))
            linhas.append(f"Dialogue: 1,{_t(ini)},{_t(fim)},Grande,,0,0,0,,"
                          rf"{{{pos}{fad}{cresce}{borra}\clip(0,{y0},1080,{y1})\c&H00{cor}&}}{texto}")

    for i, (pequenas, grandes) in enumerate(frases):
        cores = tuple(est["cores"][i % len(est["cores"])])
        fim_frase = grandes[-1]["e"] + est["segura"]
        if i + 1 < len(frases):
            prox = (frases[i + 1][0] or frases[i + 1][1])[0]["s"]
            fim_frase = min(fim_frase, prox - 0.03)
        for j, p in enumerate(pequenas):           # as pequenas, uma a uma, até a frase acabar
            fim = pequenas[j + 1]["s"] if j + 1 < len(pequenas) else fim_frase
            if fim - p["s"] < 0.02:
                continue
            fad = rf"\fad({est['entrada_ms'] if j == 0 else 0},{est['saida_ms'] if j + 1 == len(pequenas) else 0})"
            texto = " ".join(_pequena(x["w"]) for x in pequenas[:j + 1])
            linhas.append(f"Dialogue: 1,{_t(p['s'])},{_t(fim)},Pequena,,0,0,0,,"
                          + rf"{{\an5\pos(540,{y_peq}){fad}}}{texto}")
        for j, p in enumerate(grandes):            # as grandes também, uma a uma
            fim = grandes[j + 1]["s"] if j + 1 < len(grandes) else fim_frase
            if fim - p["s"] < 0.02:
                continue
            texto = " ".join(_palavra_letreiro(x["w"]) for x in grandes[:j + 1])
            grande(texto, p["s"], fim, cores, entra=(j == 0), sai=(j + 1 == len(grandes)))

    for k, p in enumerate(editor):                 # o texto do editor: uma palavra por batida, branca
        linhas.append(f"Dialogue: 0,{_t(p['s'])},{_t(p['e'])},Brilho,,0,0,0,,"
                      rf"{{\an5\pos(540,{centro})\fs{est['tamanho_editor']}\1c&H00FFFFFF&\3c&H00FFFFFF&\alpha&H80&\blur14}}"
                      f"{_palavra_letreiro(p['w'])}")
        linhas.append(f"Dialogue: 1,{_t(p['s'])},{_t(p['e'])},Grande,,0,0,0,,"
                      rf"{{\an5\pos(540,{centro})\fs{est['tamanho_editor']}\c&H00FFFFFF&}}{_palavra_letreiro(p['w'])}")

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Grande,{est['fonte']},{tam},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,{est['espacamento']},0,1,0,0,5,50,50,0,1
Style: Brilho,{est['fonte']},{tam},&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,{est['espacamento']},0,1,5,0,5,50,50,0,1
Style: Pequena,{est['fonte_pequena']},{peq},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,0,3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(linhas) + "\n", encoding="utf-8")
    return destino
