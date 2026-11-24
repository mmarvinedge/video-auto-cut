"""Edits de filme: gancho com fala + planos cortados na batida da música.

O trabalho é dividido em duas etapas, com um arquivo no meio:

  planejar()   filme + música  ->  plano.json   (o que entra, onde corta, que efeito)
  renderizar() plano.json      ->  edit.mp4

O plano.json é a "timeline" do edit em texto. Dá para abrir, trocar um plano, mexer no gancho
ou no drop e renderizar de novo sem refazer a análise (`python -m cortes edit-render plano.json`).

Pasta de trabalho: <pasta_dados>/edits/<filme>/ guarda o que vale para qualquer edit daquele
filme (cenas, transcrição, miniaturas) e uma subpasta por edit (música tratada, plano, vídeo).
"""
import json
import re
import shutil
from pathlib import Path

import numpy as np

from . import batidas, cenas, config, legendas, render

FPS = 30
PADRAO = {
    "gancho_min": 4, "gancho_max": 12,
    "gancho_longo": 40,          # quando o tema pede a conversa inteira (a IA decide)
    "duracao_musica": 15,        # segundos da parte cortada na batida
    "corte_min": 0.55, "corte_max": 1.6,
    "velocidade": 0.85,          # câmera lenta dos planos da música (1 = normal)
    "proporcao": "4:5",          # 4:5 com tarjas pretas (o visual dos edits) | 9:16 tela cheia
    "idioma": "pt",              # da fala do filme, para o Whisper: pt, en, es... ou auto
    "slowed": 0.85, "reverb": True,
    "volume_gancho": 0.18,       # a música começa baixinha debaixo da fala
    "musica_no_gancho": True,    # False: muda até o drop, que entra de uma vez (mais impacto)
    "volume_musica": 1.0,        # sobre o nível padrão da música (-15 dB RMS): 0.5 = metade, 1.3 = mais alta
    "drop_fala": "depois",       # fala do gatilho ("A mim, meus X-Men"): depois = o drop entra quando ela acaba;
                                 # durante = o drop entra com ela, e a música fica mais baixa até ela acabar
    "ritmo": "normal",           # rapido (1 batida por corte) | normal (corte_min..corte_max) | lento
    "abertura": False,           # falas do filme antes do gancho, sem música (só se o tema pedir)
    "legenda_cor": "FF1E3C", "legenda_clara": "FFE6EC", "legenda_y": 1130,
    "max_planos_ia": 150,
    "cor": {"contraste": 1.12, "saturacao": 0.78, "brilho": -0.03, "vinheta": True, "grao": 3},
    "transicoes": ["zoom", "flash", "chicote", "giro", "fusao"],   # [] = corte seco
}

# Transições entre os planos (o campo "transicao" de cada corte diz como se entra nele):
#   zoom     o plano que sai acelera para dentro, o que entra chega apertado e desfocado e solta
#   flash    o que sai aproxima e estoura no branco; o que entra aparece saindo do branco
#   chicote  movimento de câmera rápido para o lado, com borrão de movimento, continuando no próximo
#   giro     o que entra chega girado, apertado e desfocado e se endireita
#   fusao    os dois planos se misturam (8 quadros); só em cortes longos
#   corte    corte seco (o soco de zoom do plano continua valendo)
TRANSICOES = ("zoom", "flash", "chicote", "giro", "fusao", "corte")
# Duração de cada corte por ritmo (min, max), em segundos; "normal" usa corte_min/corte_max do config
RITMOS = {"rapido": (0.25, 0.75), "lento": (1.4, 3.2)}
FALA_DROP_MAX = 8.0             # a fala em cima do drop não passa disso
CAUDA = 0.3                     # o som de uma fala segue por baixo da seguinte (a imagem corta seco)
ABAFA = 0.3                     # drop durante a fala: a música fica em 30% (-10 dB) até a fala acabar
MUSICA_DB = -15.0               # nível da música (RMS) depois do drop: ~5 dB acima do diálogo de filme
ABERTURA_MAX = 15.0             # a abertura inteira (falas antes do gancho) não passa disso
ABERTURA_FALA_MAX = 8.0         # cada fala da abertura
FUSAO = 8                       # quadros da fusão
FIM_PRETO = 0.4                 # o edit termina escurecendo


def cfg_edit(cfg: dict) -> dict:
    c = {**PADRAO, **(cfg.get("edit") or {})}
    c["cor"] = {**PADRAO["cor"], **((cfg.get("edit") or {}).get("cor") or {})}
    return c


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", Path(s).stem, flags=re.UNICODE).strip("_")
    return s[:60] or "filme"


def _proporcao(texto: str) -> float:
    a, b = (float(x) for x in texto.split(":"))
    return a / b


def _ler_json(arq: Path):
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else None


def _gravar_json(arq: Path, dado) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dado, ensure_ascii=False, indent=1), encoding="utf-8")


def ler_tempo(s: str) -> float:
    """'1:23:45.5', '83:10' ou '4990' -> segundos."""
    partes = [float(p) for p in str(s).strip().split(":")]
    t = 0.0
    for p in partes:
        t = t * 60 + p
    return t


def ler_transicoes(s: str) -> list[str]:
    """'variadas', 'nenhuma' ou uma lista como 'zoom,flash' -> lista de transições."""
    s = (s or "").strip().lower()
    if s in ("", "variadas", "padrao"):
        return list(PADRAO["transicoes"])
    if s in ("nenhuma", "corte", "seco"):
        return []
    lista = [t.strip() for t in s.split(",") if t.strip()]
    if erradas := [t for t in lista if t not in TRANSICOES]:
        raise ValueError(f"transição desconhecida: {', '.join(erradas)} (use {', '.join(TRANSICOES)})")
    return lista


IDIOMA = re.compile(r"^(auto|[a-z]{2,3})$")


def ler_idioma(s: str) -> str:
    """Código de idioma do Whisper ('pt', 'en', 'es'...) ou 'auto'."""
    s = (s or "").strip().lower()
    if not IDIOMA.match(s):
        raise ValueError(f"idioma inválido: {s!r} (use o código de duas letras, como pt, en, es, ou auto)")
    return s


def ler_intervalo(s: str | None) -> tuple[float, float] | None:
    if not s:
        return None
    a, _, b = s.partition("-")
    return ler_tempo(a), ler_tempo(b)


# ------------------------------------------------------------------ análise do filme (com cache)

def analisar_filme(filme: Path, pasta: Path, trecho: tuple[float, float] | None, cfg: dict,
                   aviso=print, com_fala: bool = True) -> tuple[list[dict], list[dict], Path, list | None]:
    """Cenas, transcrição e tarja do filme (ou só do `trecho`). Ficam em cache na pasta do filme.
    Devolve (cenas, palavras, arquivo das cenas, tarja): o arquivo é para quem acrescentar dados
    nas cenas (brilho) gravar de volta; a tarja é a área sem as faixas pretas, ou None.

    Os nomes dos caches mudaram junto com o jeito de medir (planos_, falas_): os antigos
    (cenas_, transcricao_) vinham do detector que perdia cortes e do Whisper com filtro de voz,
    que devolvia transcrição vazia em filme, e não são reaproveitados."""
    ini, fim = trecho or (0.0, cenas.duracao(filme))
    chave = f"{ini:.0f}_{fim:.0f}"
    arq_tarja = pasta / f"tarja_{chave}.json"
    tarja = _ler_json(arq_tarja)
    if tarja is None:
        t = cenas.tarja(filme, ini, fim)
        tarja = list(t) if t else []
        _gravar_json(arq_tarja, tarja)
    tarja = tarja or None
    if tarja:
        aviso(f"  tarjas pretas: a imagem é {tarja[0]}x{tarja[1]}, o recorte fica dentro dela")
    arq_cenas = pasta / f"planos_{chave}.json"
    cs = _ler_json(arq_cenas)
    if cs is None:
        aviso(f"Procurando os cortes de câmera ({(fim - ini) / 60:.0f} min de filme)...")
        cs = cenas.detectar(filme, ini, fim, tarja_=tarja)
        _gravar_json(arq_cenas, cs)
    aviso(f"  {len(cs)} planos")

    palavras = []
    if com_fala:
        idioma = cfg_edit(cfg)["idioma"]
        arq_fala = pasta / f"falas_{chave}_{idioma}.json"      # um cache por idioma
        palavras = _ler_json(arq_fala)
        if palavras is None:
            aviso(f"Transcrevendo as falas (Whisper, {'idioma detectado sozinho' if idioma == 'auto' else idioma})...")
            from .transcrever import Transcritor
            w = cfg.get("whisper") or {}
            tr = Transcritor(w.get("modelo", "large-v3-turbo"), w.get("dispositivo", "auto"))
            palavras, t = [], ini
            while t < fim:                       # em blocos: um filme inteiro não cabe na memória de uma vez
                # sem filtro de voz: em filme ele descarta o diálogo junto com a trilha
                palavras += [p for p in tr.transcrever(filme, t, min(fim, t + 600), idioma, vad=False)
                             if p["s"] >= t]
                t += 600
                aviso(f"  {min(t, fim) - ini:.0f}/{fim - ini:.0f}s")
            _gravar_json(arq_fala, palavras)
        aviso(f"  {len(palavras)} palavras")
    return cs, palavras, arq_cenas, tarja


# ------------------------------------------------------------------ escolhas (IA ou heurística)

def _encaixar_gancho(palavras: list[dict], ini: float, fim: float, ce: dict) -> dict:
    """Ajusta o gancho às palavras: começa um pouco antes da primeira e termina um pouco depois da
    última, sem passar de gancho_max (corta frases do fim, nunca uma palavra no meio)."""
    dentro = [p for p in palavras if p["s"] >= ini - 0.4 and p["e"] <= fim + 0.4]
    if not dentro:          # sem fala no intervalo: vale o que foi pedido (pode ser vazio = sem gancho)
        return {"inicio": round(ini, 2), "fim": round(max(ini, min(fim, ini + ce["gancho_max"])), 2), "palavras": []}
    while len(dentro) > 1 and dentro[-1]["e"] - dentro[0]["s"] + 0.5 > ce["gancho_max"]:
        dentro.pop()
    # termina a frase: a IA às vezes marca o fim uma palavra antes ("E lutem" sem o "juntos")
    seguintes = [p for p in palavras if p["s"] > dentro[-1]["s"]]
    for p in seguintes:
        ultima = dentro[-1]
        if ultima["w"][-1:] in ".!?" or p["s"] - ultima["e"] > 0.35 or p["e"] - dentro[0]["s"] + 0.5 > ce["gancho_max"]:
            break
        dentro.append(p)
    a = dentro[0]["s"] - 0.15
    b = max(dentro[-1]["e"] + 0.35, a + ce["gancho_min"])
    return {"inicio": round(a, 2), "fim": round(b, 2), "palavras": dentro}


def _linhas(palavras: list[dict], pausa: float = 0.6) -> list[list[dict]]:
    """Palavras agrupadas em frases: quebra em pausa ou fim de frase (como a IA vê a transcrição)."""
    linhas, atual = [], []
    for p in palavras:
        if atual and (p["s"] - atual[-1]["e"] > pausa or atual[-1]["w"][-1:] in ".!?"):
            linhas.append(atual)
            atual = []
        atual.append(p)
    return linhas + ([atual] if atual else [])


def _abertura_falas(palavras: list[dict], pedidos: list[tuple[float, float]], g: dict, ce: dict,
                    heuristica: bool) -> list[dict]:
    """As falas da abertura: trechos do filme com o som e a legenda originais, sem música, que
    criam expectativa antes do gancho ("A hora chegou." / "Agrupem-se."). Cada pedido da IA é
    ajustado às palavras como o gancho; o que encosta no gancho ou passa do total sai.
    Sem pedidos e com `heuristica`: as 3 últimas frases (2 palavras ou mais) antes do gancho."""
    ce_f = dict(ce, gancho_min=0.5, gancho_max=ABERTURA_FALA_MAX)
    if not pedidos and heuristica:
        antes = [ln for ln in _linhas(palavras) if ln[-1]["e"] < g["inicio"] - 0.3 and len(ln) >= 2]
        pedidos = [(ln[0]["s"], ln[-1]["e"]) for ln in antes[-3:]]
    falas, total = [], 0.0
    for a, b in pedidos:
        f = _encaixar_gancho(palavras, a, b, ce_f)
        if not f["palavras"] or (f["inicio"] < g["fim"] and f["fim"] > g["inicio"]):
            continue
        dur = round(round((f["fim"] - f["inicio"]) * FPS) / FPS, 4)
        if total + dur > ABERTURA_MAX:
            break
        falas.append({"inicio": f["inicio"], "fim": round(f["inicio"] + dur, 3), "palavras": f["palavras"]})
        total += dur
    return falas


def _gancho_ate(g: dict, drop_filme: float, limite: float, palavras: list[dict] | None = None) -> dict:
    """O gancho termina no momento do drop (o estalo): a música entra ali. Se o drop cai depois do
    fim da fala, o gancho estica até ele (o silêncio antes do estalo faz parte) e, com `palavras`,
    ganha as falas do caminho (a fala do gatilho, no drop "depois"); se cai no meio, as palavras
    depois dele saem. Drop longe demais do gancho (passaria de `limite`): não mexe."""
    if g["fim"] <= g["inicio"] or not g["inicio"] < drop_filme <= g["inicio"] + limite:
        return g
    fonte = palavras if palavras is not None else g["palavras"]
    return {"inicio": g["inicio"], "fim": round(drop_filme, 2),
            "palavras": [p for p in fonte if g["inicio"] - 0.01 <= p["s"] < drop_filme]}


def _gancho_heuristico(palavras: list[dict], ce: dict, trecho: tuple[float, float] | None) -> dict:
    """Sem IA: o trecho de fala mais denso que caiba no gancho, terminando numa pausa.
    Sem fala nenhuma, não há gancho: o edit abre direto no drop."""
    if not palavras:
        ini = (trecho or (0, 0))[0]
        return {"inicio": ini, "fim": ini, "palavras": []}
    melhor, alvo = None, None
    for i, p in enumerate(palavras):
        j = i
        while j + 1 < len(palavras) and palavras[j + 1]["e"] - p["s"] <= ce["gancho_max"] - 0.5:
            j += 1
        dur = palavras[j]["e"] - p["s"]
        pausa_depois = (palavras[j + 1]["s"] - palavras[j]["e"]) if j + 1 < len(palavras) else 2.0
        if dur < ce["gancho_min"] - 0.5:
            continue
        nota = (j - i + 1) / max(dur, 1) + min(pausa_depois, 1.5)
        if melhor is None or nota > melhor:
            melhor, alvo = nota, (p["s"], palavras[j]["e"])
    if alvo is None:
        alvo = (palavras[0]["s"], palavras[0]["s"] + ce["gancho_min"])
    return _encaixar_gancho(palavras, *alvo, ce)


def _planos_heuristicos(cands: list[dict], n: int) -> list[int]:
    """Sem IA: os planos mais longos e claros, espalhados pelo filme, na ordem do filme."""
    if not cands:
        return []
    nota = sorted(cands, key=lambda c: (c["fim"] - c["inicio"]) * (0.5 + c.get("brilho", 0.3)), reverse=True)
    escolhidos = sorted(nota[:n], key=lambda c: c["inicio"])
    return [c["id"] for c in escolhidos]


# ------------------------------------------------------------------ plano

def _efeito(i: int) -> dict:
    """Variação dos efeitos ao longo dos cortes. O primeiro (no drop) ganha tudo."""
    if i == 0:
        return {"zoom": "soco", "tremer": True}
    return {"zoom": "soco" if i % 2 == 0 else "empurra", "tremer": i % 4 == 0}


def _transicao(i: int, dur: float, permitidas: list[str], cabe_fusao: bool) -> str:
    """Como se entra no corte i. O drop entra no flash; a fusão só em corte longo (num corte
    rápido ela embola os dois planos); o resto alterna, com o zoom como base, como nos edits."""
    ok = [t for t in permitidas if t in TRANSICOES]
    if not ok:
        return "corte"
    if i == 0:
        return "flash" if "flash" in ok else ok[0]
    if "fusao" in ok and cabe_fusao and dur >= 1.0 and i % 3 == 0:
        return "fusao"
    if "flash" in ok and i % 8 == 0:
        return "flash"
    ciclo = ([t for t in ("zoom", "chicote", "zoom", "giro") if t in ok]
             or [t for t in ok if t not in ("fusao", "flash")] or ok)
    return ciclo[i % len(ciclo)]


def montar_cortes(pontos: list[float], drop: float, gancho_dur: float, escolhidos: list[dict],
                  vel: float, transicoes: list[str] | None = None,
                  ocupado: tuple[float, float] | None = None,
                  primeiro: tuple | None = None, usados: dict | None = None) -> list[dict]:
    """Casa cada intervalo entre batidas com um plano. Plano curto demais para a câmera lenta
    pedida fica mais lento (até 0,5x); se nem assim couber, passa para o próximo da lista.

    `primeiro` = (plano, segundo do filme[, velocidade]): o corte do drop começa exatamente nesse
    momento (o estalo, o soco), mesmo que passe do fim do plano: ali o que importa é a continuidade.
    Com fala em cima do drop a velocidade é 1, para o som do filme bater com a boca.
    `usados`: trechos já usados por plano (para quem monta cortes em mais de uma vez)."""
    transicoes = PADRAO["transicoes"] if transicoes is None else transicoes
    cortes, fila = [], list(escolhidos)
    usados = {} if usados is None else usados             # trechos de cada plano já usados
    if ocupado:             # o trecho do gancho já apareceu: o plano dele só entra com outro pedaço
        for c in escolhidos:
            if c["inicio"] < ocupado[1] and c["fim"] > ocupado[0]:
                usados[c["id"]] = [ocupado]
    sobra = 0.0             # filme que o plano anterior ainda tem depois do trecho usado

    def janela(c: dict) -> tuple[float, float]:
        """O maior pedaço do plano ainda não usado (0,1 s de folga nas pontas e entre usos)."""
        livres, ini = [], c["inicio"] + 0.1
        for a, b in sorted(usados.get(c["id"], [])):
            livres.append((ini, a - 0.1))
            ini = max(ini, b + 0.1)
        livres.append((ini, c["fim"] - 0.1))
        return max(livres, key=lambda x: x[1] - x[0])

    for i, (a, b) in enumerate(zip(pontos, pontos[1:])):
        dur = b - a
        if i == 0 and primeiro:
            c, ini_fonte = primeiro[:2]
            v0 = primeiro[2] if len(primeiro) > 2 else vel
            fonte = dur * v0
            usados.setdefault(c["id"], []).append((ini_fonte, ini_fonte + fonte))
            # o momento já é o impacto (o estalo tem o próprio clarão): entra no zoom, não no flash
            trans = "zoom" if "zoom" in transicoes else _transicao(0, dur, transicoes, False)
            cortes.append({"cena": c["id"], "fonte": round(ini_fonte, 3), "dur": round(dur, 3),
                           "vel": round(v0, 3), "saida": round(gancho_dur + a - drop, 3), **_efeito(0),
                           "transicao": trans})
            sobra = max(0.0, c["fim"] - (ini_fonte + fonte))
            continue
        while fila:
            c = fila.pop(0)
            j0, j1 = janela(c)
            v = min(vel, (j1 - j0) / dur) if dur > 0 else vel
            if v >= 0.5:
                break
        else:
            raise RuntimeError(f"faltaram planos: {len(pontos) - 1} cortes e só {i} couberam")
        fonte = dur * v
        ini_fonte = (j0 + j1) / 2 - fonte / 2
        usados.setdefault(c["id"], []).append((ini_fonte, ini_fonte + fonte))
        # um plano longo pode voltar mais tarde, com outro pedaço dele
        if c["fim"] - c["inicio"] >= 2 * (fonte + 0.3):
            fila.append(c)
        # a fusão estica o plano anterior por FUSAO quadros: sem filme sobrando nele, apareceria
        # um pedaço do plano seguinte do filme no meio da mistura
        cabe = i > 0 and sobra >= FUSAO / FPS * cortes[-1]["vel"] + 0.02
        cortes.append({"cena": c["id"], "fonte": round(ini_fonte, 3), "dur": round(dur, 3),
                       "vel": round(v, 3), "saida": round(gancho_dur + a - drop, 3), **_efeito(i),
                       "transicao": _transicao(i, dur, transicoes, cabe)})
        sobra = j1 + 0.1 - (ini_fonte + fonte)
    return cortes


def _n_cortes(mus: dict, duracao: float, ce: dict) -> int:
    """Quantos planos a música pede (o drop exato ainda depende do gancho, mas o passo não)."""
    b0 = mus["batidas"][len(mus["batidas"]) // 3] if mus["batidas"] else 0
    return len(batidas.cortes_na_batida(mus["batidas"], b0, duracao, ce["corte_min"], ce["corte_max"])) - 1


def planejar(filme: Path, musica: Path, cfg: dict, tema: str = "", trecho=None, gancho=None,
             drop: float | None = None, usar_ia: bool = True, aviso=print,
             duracao: float | None = None, drop_filme: float | None = None,
             ritmo: str | None = None, fala_drop: float | None = None, abertura: bool | None = None,
             drop_fala: str | None = None) -> Path:
    """Analisa, escolhe e grava o plano.json. Devolve o caminho dele.

    Quem manda, do mais forte para o mais fraco: o que veio à mão (`gancho`, `drop`, `duracao`,
    `drop_filme`), o que a IA tirou do tema, o config."""
    ce = cfg_edit(cfg)
    pasta_filme = config.RAIZ / cfg["pasta_dados"] / "edits" / _slug(filme.name)
    pasta = pasta_filme / _slug(musica.name)
    n = 2
    while (pasta / "plano.json").exists():                 # cada edit novo numa pasta nova
        pasta = pasta_filme / f"{_slug(musica.name)}_{n}"
        n += 1
    pasta.mkdir(parents=True, exist_ok=True)

    # 1. música: trata (slowed/reverb) e acha as batidas
    aviso("Preparando a música...")
    wav = batidas.preparar(musica, pasta / "musica.wav", ce["slowed"], ce["reverb"])
    mus = batidas.analisar(wav)
    aviso(f"  {mus['bpm']} BPM, {len(mus['batidas'])} batidas, {mus['duracao']:.0f}s")

    # 2. filme: planos e falas
    cs, palavras, arq_cenas, tarja = analisar_filme(filme, pasta_filme, trecho, cfg, aviso)
    prop = _proporcao(ce["proporcao"])
    dur_min_plano = ce["corte_max"] * 0.5 + 0.3    # o pior caso: o corte mais longo a 0,5x
    pre = cenas.candidatas(cs, dur_min_plano, ce["max_planos_ia"] * 2)
    aviso(f"Tirando miniaturas de {len(pre)} planos...")
    # uma pasta de miniaturas por trecho: os números dos planos mudam de um trecho para outro
    cenas.miniaturas(filme, pre, pasta_filme / arq_cenas.stem.replace("planos_", "miniaturas_"), prop, tarja)
    _gravar_json(arq_cenas, cs)          # o brilho medido fica no cache: a próxima vez não refaz

    # quantos planos pedir: com tema e sem duração à mão, a IA pode esticar até 60 s
    n_cortes = _n_cortes(mus, duracao or ce["duracao_musica"], ce)
    ce_rapido = dict(ce, corte_min=RITMOS["rapido"][0], corte_max=RITMOS["rapido"][1])
    n_pedir = min(80, _n_cortes(mus, 60 if duracao is None else duracao, ce_rapido)) if tema else n_cortes
    gancho_manual = ler_intervalo(gancho) if isinstance(gancho, str) else gancho

    # 3. escolhas: gancho e planos
    escolha_ia = None
    if usar_ia:
        from . import ia_edit
        if not ia_edit.credenciais_disponiveis():
            aviso("Sem ANTHROPIC_API_KEY: escolhendo gancho e planos sem IA.")
        else:
            cands = cenas.candidatas(pre, dur_min_plano, ce["max_planos_ia"])
            folhas = cenas.folhas(cands, pasta / "folhas")
            por = cenas.COLUNAS * cenas.LINHAS
            faixas = [(cands[i]["id"], cands[min(i + por, len(cands)) - 1]["id"]) for i in range(0, len(cands), por)]
            aviso(f"IA escolhendo gancho e planos ({len(cands)} planos em {len(folhas)} folhas)...")
            escolha_ia = ia_edit.escolher(palavras, folhas, faixas, n_pedir + 6, n_cortes, ce,
                                          filme.stem, tema, cands)
            aviso(f"  gancho: “{escolha_ia.gancho_texto}”")
            if escolha_ia.duracao_musica:
                aviso(f"  duração pedida no tema: {escolha_ia.duracao_musica:.0f}s de música")
            if escolha_ia.drop_no_filme is not None:
                aviso(f"  drop no filme: {escolha_ia.drop_no_filme:.1f}s"
                      + (f", com a fala até {escolha_ia.fala_drop_fim:.1f}s" if escolha_ia.fala_drop_fim else ""))
            if escolha_ia.ritmo:
                aviso(f"  ritmo: {escolha_ia.ritmo}")
            if escolha_ia.abertura:
                aviso(f"  abertura: {len(escolha_ia.abertura)} falas antes do gancho")
            aviso(f"  {escolha_ia.motivo}")

    _gravar_json(pasta / "batidas.json", mus)            # para ajustar depois sem analisar de novo
    ctx = {"filme": filme, "musica": musica, "wav": wav, "mus": mus, "cs": cs, "palavras": palavras, "pre": pre,
           "tarja": tarja, "ce": ce, "tema": tema, "trecho": trecho, "ia": escolha_ia,
           "analise": {"planos": config.relativo(arq_cenas),
                       "falas": config.relativo(arq_cenas.with_name(
                           arq_cenas.name.replace("planos_", "falas_").replace(".json", f"_{ce['idioma']}.json")))}}
    plano = _montar_plano(ctx, gancho_manual, drop, duracao, drop_filme, fala_drop, ritmo, abertura, drop_fala, aviso)
    _gravar_json(pasta / "plano.json", plano)
    return pasta / "plano.json"


def _montar_plano(ctx: dict, gancho_manual, drop, duracao, drop_filme, fala_drop, ritmo, abertura, drop_fala,
                  aviso=print) -> dict:
    """Do que já foi analisado e escolhido (`ctx`) ao plano: gancho, drop, abertura e cortes.
    Não chama a IA nem o Whisper: é o que `planejar` faz depois da IA e o que `replanejar` refaz
    quando o editor ajusta o drop ou o gancho no painel. `gancho_manual="nenhum"`: sem gancho."""
    filme, musica, wav, mus = ctx["filme"], ctx["musica"], ctx["wav"], ctx["mus"]
    cs, palavras, pre, tarja, ce = ctx["cs"], ctx["palavras"], ctx["pre"], ctx["tarja"], ctx["ce"]
    tema, trecho, escolha_ia = ctx["tema"], ctx["trecho"], ctx["ia"]
    gatilho = {"momento": drop_filme, "fala_fim": fala_drop}      # o que foi pedido, antes do "depois"
    # duração da música e momento do drop no filme: à mão > tema (IA) > config
    dur_musica = duracao or (min(60.0, max(5.0, escolha_ia.duracao_musica))
                             if escolha_ia and escolha_ia.duracao_musica else ce["duracao_musica"])
    if drop_filme is None and escolha_ia and escolha_ia.drop_no_filme is not None:
        drop_filme = escolha_ia.drop_no_filme
    if fala_drop is None and escolha_ia and escolha_ia.fala_drop_fim is not None:
        fala_drop = escolha_ia.fala_drop_fim
    ritmo = ritmo or (escolha_ia.ritmo if escolha_ia and escolha_ia.ritmo else None) or ce["ritmo"]
    # fala do gatilho: "depois" = ela fecha o gancho, limpa, e o drop entra quando ela acaba;
    # "durante" = o drop entra com ela, por cima da música abafada (em cima dela não dava para entender)
    drop_fala = (drop_fala or (escolha_ia.drop_na_fala if escolha_ia and escolha_ia.drop_na_fala else None)
                 or ce["drop_fala"])
    if drop_fala == "depois" and drop_filme is not None and fala_drop is not None and fala_drop > drop_filme:
        drop_filme, fala_drop = round(fala_drop + 0.25, 3), None
    c_min, c_max = RITMOS.get(ritmo, (ce["corte_min"], ce["corte_max"]))
    # com tema, o gancho pode ir até gancho_longo (a conversa inteira); o prompt diz quando
    ce_g = dict(ce, gancho_max=max(ce["gancho_max"], ce["gancho_longo"])) if tema else ce

    if gancho_manual == "nenhum":
        g = {"inicio": 0.0, "fim": 0.0, "palavras": []}
    elif gancho_manual:
        g = _encaixar_gancho(palavras, *gancho_manual, ce_g)
    elif escolha_ia:
        g = _encaixar_gancho(palavras, escolha_ia.gancho_inicio, escolha_ia.gancho_fim, ce_g)
        if not g["palavras"]:           # a IA não achou fala (ou devolveu 0–0): tenta a heurística
            g = _gancho_heuristico(palavras, ce, trecho)
    else:
        g = _gancho_heuristico(palavras, ce, trecho)
    if drop_filme is not None:
        g = _gancho_ate(g, drop_filme, ce_g["gancho_max"], palavras)
    g_dur = round(round((g["fim"] - g["inicio"]) * FPS) / FPS, 4)
    if g_dur <= 0:
        aviso("  sem fala no filme (ou no trecho): o edit abre direto no drop, sem gancho")

    # 4. drop e pontos de corte
    bt, en = np.array(mus["batidas"]), np.array(mus["energia"])
    if drop is not None:
        i_drop = int(np.argmin(np.abs(bt - drop)))
    else:
        i_drop = batidas.achar_drop(en, bt, antes=max(min(g_dur, 8), 4), depois=dur_musica)
    t_drop = float(bt[i_drop])
    pontos = batidas.cortes_na_batida(mus["batidas"], t_drop, dur_musica, c_min, c_max)

    # fala em cima do drop: o primeiro corte dura a frase inteira (juntando batidas), na velocidade 1
    fala_fim = None
    if drop_filme is not None and fala_drop is not None and 0.3 < fala_drop - drop_filme <= FALA_DROP_MAX:
        fala_fim = fala_drop
        precisa = fala_fim - drop_filme + 0.25
        j = next((k for k in range(1, len(pontos)) if pontos[k] - pontos[0] >= precisa), len(pontos) - 1)
        pontos = [pontos[0]] + pontos[j:]

    # abertura: falas do filme antes do gancho (som e legenda originais, sem música). À mão > tema > config
    pedidos = [(t.inicio, t.fim) for t in escolha_ia.abertura] if escolha_ia else []
    quer_abertura = abertura if abertura is not None else bool(pedidos) or bool(ce["abertura"])
    falas_ab = _abertura_falas(palavras, pedidos, g, ce, heuristica=True) if quer_abertura and g_dur else []
    a_dur = round(sum(f["fim"] - f["inicio"] for f in falas_ab), 4)

    # 5. planos
    por_id = {c["id"]: c for c in pre}
    ids = list(dict.fromkeys(i for i in (escolha_ia.planos if escolha_ia else []) if i in por_id))
    ids += [i for i in _planos_heuristicos([c for c in pre if c["id"] not in ids
                                            and not (c["inicio"] < g["fim"] and c["fim"] > g["inicio"])],
                                           len(pontos) + 6) if i not in ids]      # reserva
    primeiro = None
    if drop_filme is not None:
        cena_drop = next((c for c in cs if c["inicio"] <= drop_filme < c["fim"]), None)
        # o próprio momento pode ser só clarão (o estalo) ou preto: aí o gancho termina nele, mas
        # a música entra com o primeiro plano da IA e uma transição, sem mostrar a tela estourada
        if cena_drop and not cenas.imagem_util(filme, drop_filme + 0.05, tarja):
            aviso("  o momento do drop é um clarão (ou tela escura): a música entra com o primeiro plano da IA")
            cena_drop = None
        if cena_drop:
            primeiro = (cena_drop, drop_filme, 1.0 if fala_fim else ce["velocidade"])
            ids = [i for i in ids if i != cena_drop["id"]] + [cena_drop["id"]]   # o resto dele, só no fim
            por_id.setdefault(cena_drop["id"], cena_drop)
    if not primeiro:
        fala_fim = None                 # sem o plano do momento, não há fala para sincronizar
    usados: dict = {}
    for f in falas_ab:                  # o que a abertura mostrou não volta depois do drop
        for c in cs:
            if c["inicio"] < f["fim"] and c["fim"] > f["inicio"]:
                usados.setdefault(c["id"], []).append((f["inicio"], f["fim"]))
    cortes = montar_cortes(pontos, t_drop, a_dur + g_dur, [por_id[i] for i in ids], ce["velocidade"],
                           list(ce["transicoes"] or []), (g["inicio"], g["inicio"] + g_dur) if g_dur else None,
                           primeiro, usados)
    if drop_filme is not None and cortes and "zoom" in (ce["transicoes"] or []):
        cortes[0]["transicao"] = "zoom"     # drop num momento do filme: sem o branco do flash

    gatilho["modo"] = drop_fala
    plano = {
        "filme": str(filme.resolve()), "musica_original": str(musica.resolve()),
        "tema": tema, "analise": ctx.get("analise"), "config": ce, "gatilho": gatilho,
        "musica": config.relativo(wav), "bpm": mus["bpm"],
        "drop": round(t_drop, 3), "musica_inicio": round(t_drop - g_dur, 3), "tarja": tarja,
        "drop_filme": round(drop_filme, 3) if drop_filme is not None else None,
        "ritmo": ritmo, "drop_fala": drop_fala,
        "abertura_falas": falas_ab, "abertura_dur": a_dur,
        "fala_drop": {"inicio": round(drop_filme, 3), "fim": round(fala_fim, 3),
                      "palavras": [p for p in palavras if drop_filme - 0.15 <= p["s"] < fala_fim]}
        if fala_fim else None,
        "gancho": {"inicio": g["inicio"], "fim": round(g["inicio"] + g_dur, 3), "palavras": g["palavras"]},
        "cortes": cortes,
        "duracao": round(a_dur + g_dur + pontos[-1] - t_drop, 3),
        "titulo": escolha_ia.titulo if escolha_ia else f"{filme.stem} edit",
        "descricao": escolha_ia.descricao if escolha_ia else "",
        "hashtags": (["edit"] + [h.strip("#").lower().replace(" ", "") for h in escolha_ia.hashtags])[:5]
        if escolha_ia else ["edit"],
        "ia": escolha_ia.model_dump() if escolha_ia else None,
        "estilo": {k: ce[k] for k in ("proporcao", "volume_gancho", "musica_no_gancho", "volume_musica",
                                      "legenda_cor", "legenda_clara",
                                      "legenda_y", "cor")},
    }
    aviso(f"Plano: {f'abertura {a_dur:.1f}s + ' if a_dur else ''}gancho {g_dur:.1f}s + {len(cortes)} cortes "
          f"na batida ({ritmo}) = {plano['duracao']:.1f}s")
    return plano


def _mais_novo(pasta: Path, padrao: str) -> Path | None:
    achados = sorted(pasta.glob(padrao), key=lambda a: a.stat().st_mtime, reverse=True)
    return achados[0] if achados else None


def replanejar(arq_plano: Path, ajuste: dict, aviso=print) -> dict:
    """Refaz o plano de um edit pronto com o drop e o gancho ajustados no painel, sem IA nem
    Whisper: reaproveita a análise em cache e as escolhas da IA (planos, abertura, título).
    Guarda o plano anterior em plano.anterior.json (o "desfazer").

    ajuste: {"gancho": [início, fim] ou None (sem gancho), "drop_filme": s ou None,
             "fala_fim": s ou None, "drop_fala": "depois"|"durante", "drop_musica": s ou None (automático),
             "volume_musica": multiplicador sobre o nível padrão, ou None (mantém),
             e os ajustes gerais (None = mantém): "ritmo", "duracao_musica", "transicoes" (lista),
             "abertura" (bool), "musica_no_gancho" (bool)}"""
    from .ia_edit import PlanoIA

    arq = Path(arq_plano)
    velho = json.loads(arq.read_text(encoding="utf-8"))
    pasta, pasta_filme = arq.parent, arq.parent.parent
    ce = {**cfg_edit(config.carregar()), **(velho.get("config") or {})}
    if ajuste.get("transicoes") is not None:
        ce["transicoes"] = list(ajuste["transicoes"])
    wav = config.absoluto(velho["musica"])
    mus = batidas_do_edit(velho, arq)
    arq_planos, arq_falas = arquivos_da_analise(velho, arq)
    cs = _ler_json(arq_planos) if arq_planos else None
    if not cs:
        raise RuntimeError("a análise do filme deste edit não está mais na pasta: crie o edit de novo")
    palavras = (_ler_json(arq_falas) if arq_falas else None) or []
    pre = cenas.candidatas(cs, ce["corte_max"] * 0.5 + 0.3, ce["max_planos_ia"] * 2)
    ia = PlanoIA.model_validate(velho["ia"]) if velho.get("ia") else None
    if ia:      # o que o editor ajustou vale mais que o tema: a IA não decide de novo nada disso
        ia = ia.model_copy(update={"drop_no_filme": None, "fala_drop_fim": None, "drop_na_fala": None,
                                   "duracao_musica": None, "ritmo": None})
    g = velho["gancho"]
    dur_musica = velho["duracao"] - (velho.get("abertura_dur") or 0) - (g["fim"] - g["inicio"])
    gancho = ajuste.get("gancho")
    gancho_manual = (float(gancho[0]), float(gancho[1])) if gancho else "nenhum"
    ctx = {"filme": Path(velho["filme"]), "musica": Path(velho.get("musica_original") or velho["filme"]),
           "wav": wav, "mus": mus, "cs": cs, "palavras": palavras, "pre": pre, "tarja": velho.get("tarja"),
           "ce": ce, "tema": velho.get("tema", ""), "trecho": None, "ia": ia,
           "analise": {"planos": config.relativo(arq_planos), "falas": config.relativo(arq_falas) if arq_falas else None}}
    num = lambda k: float(ajuste[k]) if ajuste.get(k) is not None else None
    if ajuste.get("duracao_musica") is not None:
        dur_musica = min(60.0, max(5.0, float(ajuste["duracao_musica"])))
    abertura = ajuste["abertura"] if ajuste.get("abertura") is not None else bool(velho.get("abertura_falas"))
    novo = _montar_plano(ctx, gancho_manual, num("drop_musica"), max(5.0, round(dur_musica, 3)),
                         num("drop_filme"), num("fala_fim"), ajuste.get("ritmo") or velho.get("ritmo"), abertura,
                         ajuste.get("drop_fala") or velho.get("drop_fala"), aviso)
    for k in ("titulo", "descricao", "hashtags", "ia", "estilo", "musica_original", "tema"):
        if k in velho:
            novo[k] = velho[k]
    # refazer o drop monta os cortes de novo: o que foi editado à mão nos cortes se perde (a tela avisa)
    if ajuste.get("volume_musica") is not None:        # o volume da música depois do drop, da tela
        novo["estilo"] = dict(novo["estilo"], volume_musica=round(float(ajuste["volume_musica"]), 2))
    if ajuste.get("musica_no_gancho") is not None:
        novo["estilo"] = dict(novo["estilo"], musica_no_gancho=bool(ajuste["musica_no_gancho"]))
    (pasta / "plano.anterior.json").write_text(arq.read_text(encoding="utf-8"), encoding="utf-8")
    _gravar_json(arq, novo)
    return novo


def arquivos_da_analise(plano: dict, arq_plano: Path) -> tuple[Path | None, Path | None]:
    """Os caches de planos e de falas do filme deste edit (planos antigos: os mais novos da pasta)."""
    analise, pasta_filme = plano.get("analise") or {}, Path(arq_plano).parent.parent
    planos = config.absoluto(analise["planos"]) if analise.get("planos") else _mais_novo(pasta_filme, "planos_*.json")
    falas = config.absoluto(analise["falas"]) if analise.get("falas") else _mais_novo(pasta_filme, "falas_*.json")
    return planos, falas


def batidas_do_edit(plano: dict, arq_plano: Path) -> dict:
    """As batidas da música tratada (batidas.json; planos antigos analisam agora e guardam)."""
    arq = Path(arq_plano).with_name("batidas.json")
    mus = _ler_json(arq)
    if mus is None:
        mus = batidas.analisar(config.absoluto(plano["musica"]))
        _gravar_json(arq, mus)
    return mus


def _caber(c: dict, cena: dict) -> None:
    """Faz o corte `c` (dur na saída, vel) caber no plano `cena`: puxa o início para trás e, se
    ainda faltar filme, deixa mais lento (até 0,5x). Sem jeito: ValueError."""
    ini, fim = cena["inicio"] + 0.05, cena["fim"] - 0.05
    if c["fonte"] + c["dur"] * c["vel"] > fim:
        c["fonte"] = round(max(ini, fim - c["dur"] * c["vel"]), 3)
    if c["fonte"] + c["dur"] * c["vel"] > fim:
        v = (fim - c["fonte"]) / c["dur"]
        if v < 0.5:
            raise ValueError(f"o plano {cena['id']} é curto demais para {c['dur']:.1f}s de corte "
                             f"(precisa de {c['dur'] * 0.5:.1f}s de filme, tem {fim - ini:.1f}s)")
        c["vel"] = round(v, 3)


def editar_corte(arq_plano: Path, op: dict) -> dict:
    """Muda um corte da música no plano, sem refazer o resto (a fase 2 do ajuste no painel).

    op: {"op": "plano", "i", "cena"}       troca o plano (o trecho do meio dele)
        {"op": "deslizar", "i", "fonte"}   começa em outro ponto do mesmo plano
        {"op": "transicao", "i", "transicao"}
        {"op": "excluir", "i"}             o corte de antes fica com a vez dele (o de depois, se for o 1º)
        {"op": "dividir", "i"}             parte na batida mais perto do meio; a 2ª metade continua o plano
    A duração total e as batidas não mudam. O plano anterior fica em plano.anterior.json."""
    arq = Path(arq_plano)
    d = json.loads(arq.read_text(encoding="utf-8"))
    cortes = d["cortes"]
    i = int(op.get("i", -1))
    if not 0 <= i < len(cortes):
        raise ValueError("esse corte não existe")
    arq_planos, _ = arquivos_da_analise(d, arq)
    cs = {x["id"]: x for x in (_ler_json(arq_planos) if arq_planos else None) or []}
    if not cs:
        raise RuntimeError("a análise do filme deste edit não está mais na pasta")
    c, tipo = cortes[i], op.get("op")
    cena_de = lambda k: cs.get(int(k)) or {"id": int(k), "inicio": 0.0, "fim": 1e9}

    if tipo == "plano":
        cena = cs.get(int(op["cena"]))
        if not cena:
            raise ValueError("esse plano não existe no filme")
        novo = dict(c, cena=cena["id"])
        novo["fonte"] = round((cena["inicio"] + cena["fim"]) / 2 - c["dur"] * c["vel"] / 2, 3)
        _caber(novo, cena)
        cortes[i] = c = novo
    elif tipo == "deslizar":
        cena = cena_de(c["cena"])
        comp = c["dur"] * c["vel"]
        lo, hi = cena["inicio"] + 0.05, cena["fim"] - comp - 0.05
        c["fonte"] = round(min(max(float(op["fonte"]), lo), max(lo, hi)), 3)
    elif tipo == "transicao":
        t = str(op.get("transicao") or "")
        if t not in TRANSICOES:
            raise ValueError(f"transição desconhecida: {t}")
        if t == "fusao" and i > 0:
            ant = cortes[i - 1]
            sobra = cena_de(ant["cena"])["fim"] - (ant["fonte"] + ant["dur"] * ant["vel"])
            if sobra < FUSAO / FPS * ant["vel"] + 0.02:
                raise ValueError("a fusão estica o corte de antes, e o plano dele acaba logo depois do trecho usado: "
                                 "deslize o corte de antes para trás ou escolha outra transição")
        c["transicao"] = t
    elif tipo == "excluir":
        if len(cortes) == 1:
            raise ValueError("é o único corte da música")
        if i > 0:
            ant = cortes[i - 1]
            ant["dur"] = round(ant["dur"] + c["dur"], 3)
            _caber(ant, cena_de(ant["cena"]))
        else:
            prox = cortes[1]
            prox.update(dur=round(prox["dur"] + c["dur"], 3), transicao=c.get("transicao", prox.get("transicao")))
            _caber(prox, cena_de(prox["cena"]))
        del cortes[i]
    elif tipo == "dividir":
        mus = batidas_do_edit(d, arq)
        m0 = d["drop"] + (c["saida"] - cortes[0]["saida"])           # o corte na música
        m1 = m0 + c["dur"]
        dentro = [b for b in mus["batidas"] if m0 + 0.25 <= b <= m1 - 0.25]
        if not dentro:
            raise ValueError("o corte é curto demais para dividir (precisa de duas batidas)")
        b = min(dentro, key=lambda x: abs(x - (m0 + m1) / 2))
        d1 = round(b - m0, 3)
        segunda = dict(c, dur=round(c["dur"] - d1, 3), fonte=round(c["fonte"] + d1 * c["vel"], 3), zoom="soco",
                       transicao="zoom" if "zoom" in (d.get("config") or {}).get("transicoes", TRANSICOES) else "corte")
        c["dur"] = d1
        cortes.insert(i + 1, segunda)
    else:
        raise ValueError("operação desconhecida")

    s0 = cortes[0]["saida"]                 # as saídas seguem as durações (o total não muda)
    for k, x in enumerate(cortes):
        x["saida"] = round(s0 + sum(y["dur"] for y in cortes[:k]), 3)
    d["cortes_editados"] = True
    arq.with_name("plano.anterior.json").write_text(arq.read_text(encoding="utf-8"), encoding="utf-8")
    _gravar_json(arq, d)
    return d


def desfazer_ajuste(arq_plano: Path) -> None:
    """Volta o plano de antes do último ajuste (troca os dois: desfazer de novo refaz)."""
    arq = Path(arq_plano)
    anterior = arq.with_name("plano.anterior.json")
    if not anterior.exists():
        raise FileNotFoundError("não há ajuste para desfazer")
    atual = arq.read_text(encoding="utf-8")
    arq.write_text(anterior.read_text(encoding="utf-8"), encoding="utf-8")
    anterior.write_text(atual, encoding="utf-8")


# ------------------------------------------------------------------ render

def _zoom(efeito: str, dur: float) -> str:
    if efeito == "soco":          # entra apertado e solta: o "punch" na batida
        return "1.05+0.16*pow(max(0,1-it/0.35),2)"
    if efeito == "empurra":       # aproxima devagar durante o plano
        return f"1.05+0.07*min(1,it/{dur:.3f})"
    return "1.05"


def _transicao_do(c: dict | None) -> str:
    """A transição de entrada de um corte. Planos antigos só tinham `flash: true`."""
    if c is None:
        return "corte"
    t = c.get("transicao") or ("flash" if c.get("flash") else "corte")
    return t if t in TRANSICOES else "corte"


# Quanto cada transição mexe na cabeça (plano que entra) e no rabo (plano que sai):
# segundos da cabeça, zoom extra, giro (rad) e borrão (gblur em sigma, chicote em pixels de rastro).
CABECA = {"zoom": (0.27, 0.30, 0, 14), "flash": (0.25, 0.12, 0, 8), "chicote": (0.22, 0.30, 0, 60),
          "giro": (0.30, 0.42, 0.22, 12)}
RABO = {"zoom": (4, 0.28, 0, 12), "flash": (4, 0.25, 0, 8), "chicote": (4, 0.30, 0, 60),
        "giro": (4, 0.30, -0.14, 10)}       # o rabo é em quadros: os últimos N do plano que sai


def _envelopes(var: str, entra: str, sai: str, dur: float) -> tuple[str, str]:
    """Curvas de 0 a 1 no tempo `var`: a da cabeça cai de 1 a 0 (solta), a do rabo sobe (acelera)."""
    cab = rab = "0"
    if entra in CABECA:
        cab = f"pow(max(0,1-{var}/{CABECA[entra][0]}),2)"
    if sai in RABO:
        n = RABO[sai][0]
        ini, passo = dur - n / FPS, (n - 1) / FPS
        rab = f"pow(min(1,max(0,({var}-{ini:.4f})/{passo:.4f})),2)"
    return cab, rab


def _rampa(filtro: str, valores: list[float], quadros: list[int]) -> str:
    """O mesmo filtro com força diferente em cada quadro (o borrão vai sumindo/aparecendo)."""
    return ",".join(filtro.format(v) + f":enable='eq(n,{q})'" for v, q in zip(valores, quadros) if v > 0.3)


def _filtro_plano(entrada: str, saida: str, rec: str, alto: tuple[int, int], quadros: int, vel: float,
                  zoom: str, tremer: bool, entra: str = "corte", sai: str = "corte", lado: int = 1) -> str:
    """Um plano pronto para emendar: câmera lenta, recorte, zoom com a transição de entrada
    (`entra`) na cabeça e a de saída (`sai`) no rabo. Com `sai == "fusao"` o plano sai FUSAO
    quadros mais comprido, para se misturar com o seguinte."""
    W2, H2 = alto
    w, h = W2 // 2, H2 // 2
    escala = w / 1080               # borrões medidos no 1080: a prévia (540) usa a metade
    if sai in RABO and quadros < RABO[sai][0] + 2:   # plano curtíssimo: o rabo passaria do começo
        sai = "corte"
    dur = quadros / FPS
    total = quadros + (FUSAO if sai == "fusao" else 0)
    cab, rab = _envelopes("it", entra, sai, dur)
    z = zoom
    if entra in CABECA:
        z += f"+{CABECA[entra][1]}*{cab}"
    if sai in RABO:
        z += f"+{RABO[sai][1]}*{rab}"
    dx = "(iw/zoom)*0.014*sin(it*57)*max(0,1-it/0.45)" if tremer else "0"
    dy = "(ih/zoom)*0.010*sin(it*43+1)*max(0,1-it/0.45)" if tremer else "0"
    # chicote: a câmera corre para o lado dentro da folga que o zoom extra abre
    folga = "(iw-iw/zoom)/2*0.9"
    if entra == "chicote":
        dx += f"-({lado})*{folga}*{cab}"
    if sai == "chicote":
        dx += f"+({lado})*{folga}*{rab}"

    f = f"[{entrada}]setpts=(PTS-STARTPTS)/{vel:.4f},fps={FPS},{rec},scale={W2}:{H2}:flags=bicubic"
    # giro: roda antes do zoompan, e o zoom extra (maior que o necessário) esconde os cantos
    giro = []
    if entra == "giro":
        c_t, _ = _envelopes("t", entra, "corte", dur)
        giro.append(f"({lado})*({CABECA['giro'][2]})*{c_t}")
    if sai == "giro":
        _, r_t = _envelopes("t", "corte", sai, dur)
        giro.append(f"({lado})*({RABO['giro'][2]})*{r_t}")
    if giro:
        cond = []
        if entra == "giro":
            cond.append(f"lt(t,{CABECA['giro'][0]})")
        if sai == "giro":
            cond.append(f"gte(t,{dur - RABO['giro'][0] / FPS:.4f})")
        f += f",rotate=a='{'+'.join(giro)}':fillcolor=black:enable='{'+'.join(cond)}'"
    f += (f",zoompan=z='{z}':x='iw/2-iw/zoom/2+{dx}':y='ih/2-ih/zoom/2+{dy}':d=1:s={w}x{h}:fps={FPS},"
          f"trim=end_frame={total},setpts=PTS-STARTPTS,setsar=1")

    # borrão de movimento: forte no quadro do corte, sumindo em 4 quadros
    perto = [1, 0.55, 0.25, 0.1]
    blur = []
    for tr, lado_corte in ((entra, "cab"), (sai, "rab")):
        tab = CABECA if lado_corte == "cab" else RABO
        if tr not in tab:
            continue
        forca = tab[tr][3] * escala
        qs = list(range(4)) if lado_corte == "cab" else [quadros - 1 - k for k in range(4)]
        modelo = "dblur=angle=0:radius={:.0f}" if tr == "chicote" else "gblur=sigma={:.1f}"
        blur.append(_rampa(modelo, [forca * p for p in perto], qs))
    f += "".join("," + b for b in blur if b)
    if entra == "flash":
        f += f",fade=t=in:st=0:d={CABECA['flash'][0]}:color=white"
    if sai == "flash":
        f += f",fade=t=out:st={dur - 3 / FPS:.4f}:d={3 / FPS:.4f}:color=white"
    return f + f",format=yuv420p,settb=AVTB[{saida}]"


def _cor(c: dict) -> str:
    f = (f"eq=contrast={c['contraste']}:saturation={c['saturacao']}:brightness={c['brilho']},"
         "colorbalance=rs=-0.04:bs=0.06:rh=0.04:bh=-0.03")
    if c.get("vinheta"):
        f += ",vignette=angle=PI/4.5"
    if c.get("grao"):
        f += f",noise=alls={int(c['grao'])}:allf=t"
    return f


def _ganho_musica(musica: str, drop: float, dur: float, volume: float = 1.0) -> float:
    """Quanto multiplicar a música para a parte depois do drop ficar em MUSICA_DB (RMS), vezes o
    `volume_musica` do edit. Música de edit vem masterizada alta (-5 a -8 dB): por cima do diálogo
    de filme (~-20 dB) ela engolia tudo, inclusive a fala do drop."""
    y = batidas.carregar(Path(musica))
    trecho = y[int(drop * batidas.SR):int((drop + max(dur, 1.0)) * batidas.SR)]
    if len(trecho) < batidas.SR // 2:
        return float(volume)
    rms_db = 20 * np.log10(float(np.sqrt((trecho.astype(np.float64) ** 2).mean())) + 1e-9)
    ganho_db = min(6.0, max(-30.0, MUSICA_DB - rms_db))
    return float(10 ** (ganho_db / 20) * max(0.0, volume))


def renderizar(arq_plano: Path, destino: Path | None = None, progresso=None, previa: bool = False) -> Path:
    """O plano vira o vídeo. `previa=True`: o mesmo edit em 540 px e codificação rápida, em
    previa.mp4, para conferir um ajuste no painel antes do render final."""
    plano = json.loads(Path(arq_plano).read_text(encoding="utf-8"))
    pasta = Path(arq_plano).resolve().parent
    destino = (destino or pasta / ("previa.mp4" if previa else "edit.mp4")).resolve()
    est, filme = plano["estilo"], plano["filme"]
    prop = _proporcao(est["proporcao"])
    LARG = 540 if previa else 1080
    ALT = LARG * 16 // 9
    W, H = LARG, round(LARG / prop / 2) * 2
    H = min(H, ALT)
    alto = (W * 2, H * 2)            # o zoompan trabalha no dobro: sem isso o zoom lento treme
    rec = cenas._recorte(*cenas.tamanho(Path(filme)), prop, plano.get("tarja"))

    g = plano["gancho"]
    g_q = round((g["fim"] - g["inicio"]) * FPS)
    g_dur = g_q / FPS
    tem_gancho = g_q > 0            # filme sem fala: o edit abre direto no drop
    total = plano["duracao"]
    abertura = plano.get("abertura_falas") or []          # falas antes do gancho (planos antigos: nenhuma)
    a_qs = [round((f["fim"] - f["inicio"]) * FPS) for f in abertura]
    a_q = sum(a_qs)
    a_dur = a_q / FPS
    cortes = plano["cortes"]
    fala_drop = plano.get("fala_drop")
    t_drop = a_q / FPS + g_dur                            # onde o drop cai no vídeo

    # a linha do tempo: as falas da abertura, o gancho e os cortes da música. Fala e gancho são
    # trechos do filme com som, na velocidade 1 (dict com "inicio"/"fim"); corte tem "fonte"
    trechos = list(abertura) + ([g] if tem_gancho else []) + list(cortes)
    inicios = ([sum(a_qs[:k]) for k in range(len(abertura))] + ([a_q] if tem_gancho else [])
               + [round(c["saida"] * FPS) for c in cortes])
    if cortes:
        inicios[len(abertura) + (1 if tem_gancho else 0)] = a_q + g_q     # o drop cai no quadro exato
    bordas = inicios + [round(total * FPS)]
    entra = [_transicao_do(c) if "fonte" in c else "corte" for c in trechos]
    sai = lambda k: entra[k + 1] if k + 1 < len(trechos) else "corte"

    entradas, filtros, rotulos = [], [], []
    com_som = []                        # (entrada, início no vídeo, duração) dos trechos com som do filme
    for k, c in enumerate(trechos):
        e = sum(1 for x in entradas if x == "-i")          # índice desta entrada
        quadros = bordas[k + 1] - bordas[k]
        if "fonte" not in c:
            dur_t = quadros / FPS
            entradas += ["-ss", f"{c['inicio']:.3f}", "-t", f"{dur_t + 0.5:.3f}", "-i", filme]
            filtros.append(_filtro_plano(f"{e}:v", f"v{k}", rec, alto, quadros, 1.0,
                                         f"1.0+0.06*min(1,it/{dur_t:.3f})", False, "corte", sai(k), 1))
            com_som.append((e, bordas[k] / FPS, dur_t))
        else:
            entradas += ["-ss", f"{c['fonte']:.3f}", "-t", f"{c['dur'] * c['vel'] + 0.4:.3f}", "-an", "-i", filme]
            filtros.append(_filtro_plano(f"{e}:v", f"v{k}", rec, alto, quadros, c["vel"],
                                         _zoom(c["zoom"], c["dur"]), c["tremer"], entra[k], sai(k),
                                         1 if k % 2 else -1))
        rotulos.append(f"v{k}")

    # emenda: concat nos cortes, xfade na fusão (o plano anterior veio FUSAO quadros mais longo
    # e a mistura começa na batida). O offset fica meio quadro antes: o xfade só começa num quadro
    # com tempo >= offset, e o arredondamento do tempo do quadro atrasava todo o resto em um quadro.
    atual = rotulos[0]
    for k in range(1, len(rotulos)):
        prox = f"e{k}"
        if entra[k] == "fusao":
            filtros.append(f"[{atual}][{rotulos[k]}]xfade=transition=fade:duration={FUSAO / FPS:.4f}:"
                           f"offset={(bordas[k] - 0.5) / FPS:.4f}[{prox}]")
        else:
            filtros.append(f"[{atual}][{rotulos[k]}]concat=n=2:v=1:a=0[{prox}]")
        atual = prox

    def nova_entrada(*args) -> int:
        i = sum(1 for x in entradas if x == "-i")
        entradas.extend(args)
        return i

    # legenda: as falas da abertura, do gancho e a fala em cima do drop, no tempo do vídeo
    leg_palavras = []
    for k, c in enumerate(trechos):
        if "fonte" not in c:
            leg_palavras += [dict(p, s=p["s"] - c["inicio"] + bordas[k] / FPS, e=p["e"] - c["inicio"] + bordas[k] / FPS)
                             for p in c["palavras"] if p["s"] < c["inicio"] + (bordas[k + 1] - bordas[k]) / FPS]
    if fala_drop:
        leg_palavras += [dict(p, s=p["s"] - fala_drop["inicio"] + t_drop, e=p["e"] - fala_drop["inicio"] + t_drop)
                         for p in fala_drop["palavras"]]
    ass = legendas.gerar_ass_edit(leg_palavras, 0.0, total, pasta / "gancho.ass",
                                  est["legenda_y"], est["legenda_cor"], est["legenda_clara"])
    pad = f",pad={LARG}:{ALT}:0:(oh-ih)/2:black" if H < ALT else ""
    leg = f",subtitles=filename={ass.name}" if ass else ""
    fim = f",fade=t=out:st={max(0, total - FIM_PRETO):.3f}:d={FIM_PRETO}"
    filtros.append(f"[{atual}]{_cor(est['cor'])}{fim}{pad}{leg},format=yuv420p[v]")

    # áudio. Música: começa `musica_inicio` antes do drop, baixinha debaixo da fala; se o drop vem cedo
    # demais, entra com atraso. Com `musica_no_gancho: false` ou com abertura, a música só entra no
    # drop, no volume cheio: antes dele é só o filme falando (planos antigos tocam como antes).
    musica = str(config.absoluto(plano["musica"]))
    vg = est["volume_gancho"]
    sons = []
    no_drop = bool(abertura) or (tem_gancho and not est.get("musica_no_gancho", True))
    if no_drop:
        ini_mus, atraso = plano["drop"], t_drop
        volume = f"afade=t=in:st={t_drop:.3f}:d=0.015,"          # 15 ms só para não estalar
    else:
        ini_mus, atraso = plano["musica_inicio"], 0.0
        if ini_mus < 0:
            ini_mus, atraso = 0.0, -plano["musica_inicio"]
        volume = (f"volume='{vg}+(1-{vg})*min(1,max(0,(t-{g_dur - 0.2:.3f})/0.2))':eval=frame,"
                  if tem_gancho else "")               # sem gancho, a música já entra cheia no drop
    m = nova_entrada("-ss", f"{ini_mus:.3f}", "-i", musica)
    ganho = _ganho_musica(musica, plano["drop"], total - t_drop, est.get("volume_musica", 1.0))
    if fala_drop:       # a fala do drop por cima: a música abafada até ela acabar, e sobe em 0,4 s
        f0, f1 = t_drop, t_drop + fala_drop["fim"] - fala_drop["inicio"]
        volume += (f"volume='if(lt(t,{f0:.3f}),1,if(lt(t,{f1:.3f}),{ABAFA},"
                   f"min(1,{ABAFA}+(1-{ABAFA})*(t-{f1:.3f})/0.4)))':eval=frame,")
    filtros.append(f"[{m}:a]aresample=48000,volume={ganho:.3f},"
                   + (f"adelay={atraso * 1000:.0f}:all=1," if atraso else "")
                   + f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS,{volume}"
                   f"afade=t=out:st={max(0, total - 1.2):.3f}:d=1.2[mus]")
    sons.append("mus")
    # falas da abertura e o gancho. A imagem corta seco, o som não: cada trecho segue CAUDA segundos
    # por baixo do seguinte, sumindo, enquanto o seguinte entra em 80 ms (uma mistura curta). Antes
    # cada fala sumia 0,25 s ANTES do corte e o som caía a -40 dB em cada emenda.
    for n_som, (e, ini_v, dur_t) in enumerate(com_som):
        ultimo = n_som == len(com_som) - 1
        # o gancho emenda direto na fala do drop (o mesmo filme, sem pulo): sem cauda, sem sumir
        continua = ultimo and fala_drop and abs(fala_drop["inicio"] - g["fim"]) < 0.1
        cauda = 0.0 if continua else CAUDA
        entrada = "afade=t=in:d=0.03," if n_som == 0 else "afade=t=in:d=0.08,"
        saida = "" if continua else f"afade=t=out:st={dur_t:.3f}:d={cauda:.3f},"
        filtros.append(f"[{e}:a]atrim=0:{dur_t + cauda:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                       f"{entrada}{saida}"
                       + (f"adelay={ini_v * 1000:.0f}:all=1," if ini_v else "")
                       + f"apad=whole_dur={total:.3f}[fala{n_som}]")
        sons.append(f"fala{n_som}")
    if fala_drop:       # a fala em cima do drop: o som do filme continua até a frase acabar
        dur_f = fala_drop["fim"] - fala_drop["inicio"] + 0.3
        f = nova_entrada("-ss", f"{fala_drop['inicio']:.3f}", "-t", f"{dur_f:.3f}", "-vn", "-i", filme)
        continua = tem_gancho and abs(fala_drop["inicio"] - g["fim"]) < 0.1
        filtros.append(f"[{f}:a]aresample=48000,atrim=0:{dur_f:.3f},asetpts=PTS-STARTPTS,"
                       + ("" if continua else "afade=t=in:d=0.03,")
                       + f"afade=t=out:st={max(0, dur_f - 0.3):.3f}:d=0.3,volume=1.3,"
                       f"adelay={t_drop * 1000:.0f}:all=1,apad=whole_dur={total:.3f}[faladrop]")
        sons.append("faladrop")
    if len(sons) == 1:
        filtros.append(f"[{sons[0]}]alimiter=limit=0.95[a]")
    else:
        filtros.append("".join(f"[{x}]" for x in sons)
                       + f"amix=inputs={len(sons)}:duration=longest:normalize=0,alimiter=limit=0.95[a]")

    tmp = destino.with_name(destino.stem + ".tmp.mp4")
    # o filtro vai por arquivo (`-/filter_complex`): com as transições ele cresce uns 1.000 caracteres
    # por plano, e com 40+ cortes passava do limite de 32.767 da linha de comando do Windows (WinError 206)
    arq_filtro = destino.with_name(destino.stem + ".filtro.txt")
    arq_filtro.write_text(";\n".join(filtros), encoding="utf-8")
    cmd = [config.ffmpeg(), "-y", "-v", "error", *entradas,
           "-/filter_complex", str(arq_filtro), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "libx264", *(["-preset", "ultrafast", "-crf", "28"] if previa else
                                ["-preset", "slow", "-crf", "20", "-maxrate", "16M", "-bufsize", "32M"]), "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(tmp)]
    try:
        if progresso:
            render._com_progresso(cmd, pasta, total, progresso)
        else:
            import subprocess
            subprocess.run(cmd, check=True, cwd=pasta)
        if tmp.stat().st_size < render.MINIMO_BYTES:
            raise RuntimeError(f"o render saiu vazio ({tmp.stat().st_size} bytes)")
        tmp.replace(destino)
    finally:
        tmp.unlink(missing_ok=True)
        arq_filtro.unlink(missing_ok=True)

    if previa:
        return destino
    tags = " ".join("#" + h for h in plano.get("hashtags", []))
    destino.with_suffix(".txt").write_text(f"{plano.get('titulo', '')}\n\n{plano.get('descricao', '')}\n\n{tags}\n",
                                           encoding="utf-8")
    return destino


def copiar_para_prontos(video: Path, cfg: dict) -> Path | None:
    pronto = config.pasta_prontos(cfg)
    if not pronto:
        return None
    pronto.mkdir(parents=True, exist_ok=True)
    nome = f"edit_{video.parent.parent.name}_{video.parent.name}"
    shutil.copy2(video, pronto / f"{nome}.mp4")
    if video.with_suffix(".txt").exists():
        shutil.copy2(video.with_suffix(".txt"), pronto / f"{nome}.txt")
    return pronto / f"{nome}.mp4"
