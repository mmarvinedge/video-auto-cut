"""Modelos de edit: receitas de estilo tiradas de modelos de referência (os do CapCut, por exemplo).

Um modelo é um arquivo `modelos/<id>.yaml` (na pasta do cortes-bot, ao lado do config.yaml):

  nome, descricao, referencia   o que aparece no painel e de onde o modelo veio
  edit:                         valores da seção `edit:` do config que o modelo muda (proporção,
                                transições, ritmo, cor, fim...). Só chaves que existem em edit.PADRAO.
  letreiro:                     (opcional) as falas do filme viram texto palavra por palavra num
                                letreiro de LED sobre o preto, no lugar da legenda (veja legendas.py)

Quem manda, do mais fraco para o mais forte: config.yaml < modelo < o que veio à mão (painel ou
comando) < o que o editor ajusta depois. O modelo é aplicado na seção `edit:` antes das opções da mão.
"""
import re
import threading
from pathlib import Path

import yaml

PASTA = Path(__file__).resolve().parent.parent / "modelos"
IDENT = re.compile(r"^[a-z0-9_-]{1,40}$")

# O letreiro: tudo o que um modelo não disser vem daqui
LETREIRO = {
    "fonte": "Impact",           # fonte do sistema (condensada e grossa, como nos modelos)
    "tamanho": 170,              # no quadro de 1080 de largura
    "cores": ["FFFFFF", "E8202A"],   # RGB, uma por palavra, alternando
    "espacamento": 3,
    "max_palavras": 4,           # palavras por tela
    "max_chars": 22,             # letras por tela (o texto quebra em linhas sozinho)
    "pausa": 0.45,               # uma pausa maior que isso na fala começa outra tela
    "segura": 0.2,               # a tela fica no ar depois da última palavra
    "relampago_min": 0.35,       # um buraco na fala desse tamanho mostra o filme (sem texto)
    "pulo": 1.22,                # a palavra nova chega maior e assenta em 0,1 s (1 = sem pulo)
    "led_passo": 7,              # distância entre os LEDs, em pixels no 1080
    "led_fundo": 0.16,           # brilho entre os LEDs (0 = preto)
    "aberracao": 5,              # deslocamento do vermelho e do azul, em pixels no 1080
    "brilho": 0.5,               # força do brilho em volta das letras (0 = sem)
}


# A legenda em destaque (duas camadas, a de baixo com degradê): o que um modelo não disser vem daqui
DESTAQUE = {
    "fonte": "Impact",           # a linha grande: condensada e grossa
    "tamanho": 150,              # no quadro de 1080 de largura
    "espacamento": 2,
    "fonte_pequena": "Arial",    # a linha pequena, em cima
    "tamanho_pequena": 44,
    "tamanho_editor": 150,       # o texto do editor (uma palavra por batida)
    "cores": [["FF5FB0", "FFB347"], ["FF2D2D", "FF8A3D"], ["7CFF6B", "12A84A"], ["FFE7A0", "C8892B"]],
    "faixas": 8,                 # faixas do degradê (mais = mais liso)
    "altura": 0.62,              # onde fica a linha grande, de 0 (topo da imagem) a 1 (base)
    "max_palavras": 9,           # palavras por frase
    "max_chars": 48,
    "pausa": 0.6,                # uma pausa maior que isso começa outra frase
    "max_grandes": 3,            # as últimas palavras da frase que vão grandes
    "max_chars_grandes": 15,
    "segura": 0.35,              # a frase fica no ar depois da última palavra
    "pulo": 112,                 # a linha grande chega 12% maior e assenta
    "entrada_ms": 120,
    "saida_ms": 140,
}
TEXTO_PREVIA = ["O", "DROP", "CHEGOU"]      # o texto do editor da prévia (sem IA)


def _arquivo(ident: str) -> Path:
    ident = str(ident or "").strip().lower()
    if not IDENT.match(ident):
        raise ValueError(f"modelo inválido: {ident!r}")
    arq = PASTA / f"{ident}.yaml"
    if not arq.is_file():
        raise ValueError(f"modelo desconhecido: {ident} (há: {', '.join(m['id'] for m in listar()) or 'nenhum'})")
    return arq


def carregar(ident: str) -> dict:
    """O modelo, conferido: chaves de `edit:` que existem e transições conhecidas."""
    from . import edit

    arq = _arquivo(ident)
    d = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    ajustes = d.get("edit") or {}
    if erradas := [k for k in ajustes if k not in edit.PADRAO]:
        raise ValueError(f"{arq.name}: chaves que o edit não conhece em edit: {', '.join(erradas)}")
    trans = list(ajustes.get("transicoes") or []) + [ajustes.get("transicao_drop") or "flash"]
    if erradas := [t for t in trans if t not in edit.TRANSICOES]:
        raise ValueError(f"{arq.name}: transição desconhecida: {', '.join(erradas)}")
    letreiro = d.get("letreiro")
    if letreiro is not None:
        if erradas := [k for k in letreiro if k not in LETREIRO]:
            raise ValueError(f"{arq.name}: chaves que o letreiro não conhece: {', '.join(erradas)}")
        letreiro = {**LETREIRO, **letreiro}
    destaque = d.get("destaque")
    if destaque is not None:
        if erradas := [k for k in destaque if k not in DESTAQUE]:
            raise ValueError(f"{arq.name}: chaves que o destaque não conhece: {', '.join(erradas)}")
        destaque = {**DESTAQUE, **destaque}
    return {"id": arq.stem, "nome": d.get("nome") or arq.stem, "descricao": d.get("descricao", ""),
            "referencia": d.get("referencia", ""), "edit": ajustes, "letreiro": letreiro, "destaque": destaque}


def _resumo(m: dict) -> dict:
    """O que a galeria do painel mostra de um modelo (o resto vem do padrão do edit)."""
    from . import edit
    e = {**edit.PADRAO, **m.get("edit", {})}
    return {**{k: m[k] for k in ("id", "nome", "descricao", "referencia")},
            "proporcao": e["proporcao"], "transicoes": list(e["transicoes"] or []),
            "transicao_drop": e["transicao_drop"], "letreiro": bool(m.get("letreiro")),
            "destaque": bool(m.get("destaque")), "texto_editor": bool(e.get("texto_editor")),
            "rampa": bool(e["rampa"]), "preparacao": float(e["preparacao"] or 0)}


def listar(com_padrao: bool = False) -> list[dict]:
    """Os modelos da pasta (os com erro ficam de fora). `com_padrao`: o edit sem modelo primeiro."""
    saida = [_resumo(PADRAO_INFO)] if com_padrao else []
    for arq in sorted(PASTA.glob("*.yaml")):
        try:
            m = carregar(arq.stem)
        except (ValueError, yaml.YAMLError):
            continue
        saida.append(_resumo(m))
    return saida


def aplicar(secao_edit: dict | None, ident: str) -> dict:
    """A seção `edit:` do config com o modelo por cima (a cor se mistura chave a chave)."""
    m = carregar(ident)
    base = dict(secao_edit or {})
    novo = {**base, **m["edit"], "modelo": m["id"], "letreiro": m["letreiro"], "destaque": m["destaque"]}
    if "cor" in m["edit"]:
        novo["cor"] = {**(base.get("cor") or {}), **m["edit"]["cor"]}
    return novo


# ------------------------------------------------------------------ prévia (para a galeria do painel)
#
# Cada modelo ganha um vídeo curto feito pelo próprio edit, sobre um "filme" e uma música sintéticos
# (degradês animados, sem som, e uma batida a 100 BPM com drop): mostra o letreiro, as transições,
# o ritmo e a cor sem usar nada com direitos autorais. Fica em dados/modelos/<id>/previa.mp4 e é
# refeito quando o .yaml ou o código dos efeitos muda. "padrao" é o edit sem modelo, para comparar.

PADRAO_ID = "padrao"
PADRAO_INFO = {"id": PADRAO_ID, "nome": "Edit padrão", "edit": {},
               "descricao": "Sem modelo: a fala do gancho com a legenda neon, 4:5 com tarjas, cor fria e transições "
                            "variadas (zoom, flash, chicote, giro, fusão).", "referencia": ""}
FALA_PREVIA = [("Você", 30.3, 30.6), ("diz", 30.65, 30.9), ("a", 30.95, 31.05), ("eles.", 31.1, 31.5),
               ("Eu", 32.5, 32.65), ("acreditei", 32.7, 33.2), ("em", 33.25, 33.35), ("mim,", 33.4, 33.8),
               ("quando", 34.4, 34.7), ("ninguém", 34.75, 35.15), ("mais", 35.2, 35.4), ("acreditou.", 35.45, 36.1)]
GANCHO_PREVIA = (30.2, 36.3)
# degradês do filme falso: cores (hex), tipo; claros e escuros alternados para o detector de cenas
CENAS_PREVIA = [("0b3d4f:e07a3a", "linear"), ("1a0f2e:c2185b", "radial"), ("f2c879:d84a28", "spiral"),
                ("03121c:146b8c", "circular"), ("e8e2d0:7a9e9f", "linear"), ("2b0a0a:a3271f", "radial"),
                ("9fd3e0:2e5e8c", "spiral"), ("101418:55606b", "linear"), ("ffb35c:7b2d8c", "circular"),
                ("0e2a1c:3f8f5a", "radial"), ("f7e3c4:b5651d", "linear"), ("15051f:6b3fa0", "spiral"),
                ("c9e4ea:1f4e5f", "circular"), ("2a1608:c67a2d", "linear"), ("eacb9e:4a2c5e", "radial"),
                ("081a26:2f7fa6", "spiral")]
_trava = threading.Lock()         # uma prévia por vez (a galeria pede todas juntas)


def _pasta_previas(cfg: dict) -> Path:
    from . import config
    return config.RAIZ / cfg["pasta_dados"] / "modelos"


def _fonte_previa(pasta: Path) -> tuple[Path, Path]:
    """O filme e a música sintéticos (feitos uma vez, para todos os modelos)."""
    import subprocess

    from . import config
    pasta.mkdir(parents=True, exist_ok=True)
    filme, musica = pasta / "filme_v3.mp4", pasta / "musica.wav"     # v3: com as luzes andando
    if not filme.exists():
        entradas, rotulos = [], ""
        for i, (cores, tipo) in enumerate(CENAS_PREVIA):
            c0, c1 = cores.split(":")
            entradas += ["-f", "lavfi", "-i", f"gradients=s=1280x720:r=30:d=4:c0=0x{c0}:c1=0x{c1}:nb_colors=2:"
                                               f"type={tipo}:speed=0.03:seed={i * 7 + 1}"]
            rotulos += f"[{i}:v]"
        n = len(CENAS_PREVIA)
        # luzes desfocadas passando pela tela toda, em duas camadas (perto e rápida, longe e lenta):
        # sem movimento, a rampa de velocidade e o borrão não aparecem na prévia. Cada camada é um
        # quadro só (o geq roda uma vez), com 2560 px de período, que corre em loop
        def luz(celula: int, raio: float, sigma: float, rotulo: str) -> str:
            i, j = f"mod(floor(X/{celula}),{2560 // celula})", f"floor(Y/{celula})"
            alfa = (f"st(0,{i});st(1,{j});"
                    f"st(2,ld(0)*{celula}+{celula / 2}+{celula * 0.3}*sin(ld(0)*1.7+ld(1)*2.3));"
                    f"st(3,ld(1)*{celula}+{celula / 2}+{celula * 0.3}*sin(ld(0)*2.9+ld(1)*1.1));"
                    f"st(4,{raio}*(0.7+0.3*sin(ld(0)*3.1+ld(1)*0.7)));"
                    f"255*pow(max(0,1-hypot(X-ld(2),Y-ld(3))/ld(4)),1.5)*max(0,sin(ld(0)*5.3+ld(1)*4.1))")
            return (f"color=c=black:s=3840x720:r=30:d=0.04,format=yuva420p,"
                    f"geq=lum='235':cb='128':cr='128':a='{alfa}',gblur=sigma={sigma},"
                    f"loop=loop=-1:size=1,setpts=N/30/TB,trim=duration={n * 4}[{rotulo}]")
        tmp = filme.with_suffix(".tmp.mp4")
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", *entradas, "-f", "lavfi", "-i",
                        f"anullsrc=r=48000:cl=stereo:d={n * 4}", "-filter_complex",
                        f"{rotulos}concat=n={n}:v=1:a=0[fundo];" + luz(240, 70, 10, "l1") + ";"
                        + luz(120, 26, 3, "l2") + ";"
                        "[fundo][l1]overlay=x='-mod(t*160,2560)':y=0:eval=frame[a];"
                        "[a][l2]overlay=x='-mod(t*420,2560)':y=0:eval=frame,"
                        "noise=alls=6:allf=t,format=yuv420p[v]",
                        "-map", "[v]", "-map", f"{n}:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-c:a", "aac", "-shortest", str(tmp)], check=True)
        tmp.replace(filme)
    if not musica.exists():
        p, b = 0.6, 0.3          # 100 BPM, primeira batida em 0,3 s; o drop em 20 s
        kick = f"sin(2*PI*52*t*(1+2*exp(-mod(t-{b},{p})*30)))*exp(-mod(t-{b},{p})*9)*gte(t,{b})"
        caixa = f"(random(0)*2-1)*exp(-mod(t-{b}-{p},{2 * p})*22)*gte(t,{b + p})"
        chimbal = f"(random(1)*2-1)*exp(-mod(t-{b}-{p / 2},{p})*60)"
        acorde = "(sin(2*PI*110*t)+0.6*sin(2*PI*164.8*t)+0.5*sin(2*PI*220*t)+0.3*sin(2*PI*261.6*t))"
        expr = (f"if(lt(t,20),0.05*{acorde}+0.12*{chimbal},"
                f"0.55*{kick}+0.22*{caixa}+0.08*{chimbal}+0.09*{acorde})")
        tmp = musica.with_suffix(".tmp.wav")
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"aevalsrc='{expr}':s=44100:d=45", "-ac", "2", str(tmp)], check=True)
        tmp.replace(musica)
    return filme, musica


def _codigo_mudou_depois(arq: Path, ident: str) -> bool:
    fontes = [Path(__file__).with_name(n) for n in ("modelos.py", "efeitos.py", "edit.py", "legendas.py")]
    if ident != PADRAO_ID:
        fontes.append(_arquivo(ident))
    return not arq.exists() or max(f.stat().st_mtime for f in fontes) > arq.stat().st_mtime


def previa(ident: str, cfg: dict) -> Path:
    """O vídeo de prévia do modelo (540 px), feito na hora se ainda não existe ou se ficou velho."""
    from . import batidas, cenas, edit
    ident = str(ident or "").strip().lower()
    m = PADRAO_INFO if ident == PADRAO_ID else carregar(ident)
    pasta = _pasta_previas(cfg)
    destino = pasta / m["id"] / "previa.mp4"
    with _trava:
        if not _codigo_mudou_depois(destino, m["id"]):
            return destino
        filme, musica = _fonte_previa(pasta)
        arq_cenas = pasta / "cenas.json"
        cs = edit._ler_json(arq_cenas) if arq_cenas.exists() and arq_cenas.stat().st_mtime > filme.stat().st_mtime else None
        if not cs:
            cs = cenas.detectar(filme)
            edit._gravar_json(arq_cenas, cs)
        mus = batidas.analisar(musica)
        ce = edit.cfg_edit({"edit": {} if m["id"] == PADRAO_ID else aplicar({}, m["id"])})
        palavras = [{"w": w, "s": s, "e": e} for w, s, e in FALA_PREVIA]
        pre = cenas.candidatas(cs, ce["corte_max"] * 0.5 + 0.3, ce["max_planos_ia"] * 2)
        ctx = {"filme": filme, "musica": musica, "wav": musica, "mus": mus, "cs": cs, "palavras": palavras,
               "pre": pre, "tarja": None, "ce": ce, "tema": "", "trecho": None, "ia": None, "analise": None,
               "texto_editor": TEXTO_PREVIA}
        plano = edit._montar_plano(ctx, GANCHO_PREVIA, None, 8.0, None, None, None, False, None, aviso=lambda *a: None)
        plano.update(titulo=m["nome"], hashtags=[])
        arq = destino.with_name("plano.json")
        edit._gravar_json(arq, plano)
        return edit.renderizar(arq, previa=True)
