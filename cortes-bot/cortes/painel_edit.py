"""O lado do painel dos edits de filme: navegar nas pastas, validar o pedido e listar os edits feitos.

O navegador não entrega o caminho de um arquivo escolhido num <input type=file> (só o nome),
e o comando precisa do caminho: por isso quem lista as pastas é o painel, que roda na mesma máquina
e só aceita conexão de localhost.
"""
import functools
import json
import os
import re
import subprocess
from pathlib import Path

from . import config, edit

VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".wmv", ".mpg", ".mpeg"}
AUDIO = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma"}
TEMPO = re.compile(r"^\d{1,3}(:\d{1,2}){0,2}(\.\d+)?$")
IDENT = re.compile(r"^[\w\-]+/[\w\-]+$")


def _lembradas(dados: Path) -> Path:
    return dados / "edits" / "pastas.json"


def lembrar(dados: Path, filme: str, musica: str) -> None:
    """A pasta do filme e a da música, para o seletor abrir nelas da próxima vez (endereço do
    YouTube não tem pasta: fica a de antes)."""
    from . import youtube
    arq = _lembradas(dados)
    arq.parent.mkdir(parents=True, exist_ok=True)
    antes = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    novas = {"video": None if youtube.eh_url(filme) else str(Path(filme).parent),
             "audio": None if youtube.eh_url(musica) else str(Path(musica).parent)}
    arq.write_text(json.dumps({k: v or antes.get(k) for k, v in novas.items()}, ensure_ascii=False), encoding="utf-8")


def _atalhos(dados: Path) -> list[dict]:
    casa = Path.home()
    saida = [{"nome": n, "pasta": str(p)} for n, p in (
        ("Baixados do YouTube", dados / "edits" / "_youtube"),
        ("Início", casa), ("Vídeos", casa / "Videos"), ("Músicas", casa / "Music"),
        ("Downloads", casa / "Downloads"), ("Área de trabalho", casa / "Desktop")) if p.is_dir()]
    unidades = os.listdrives() if hasattr(os, "listdrives") else []
    return saida + [{"nome": u.rstrip("\\"), "pasta": u} for u in unidades]


def navegar(dados: Path, pasta: str, tipo: str) -> dict:
    """Conteúdo de uma pasta: subpastas e os arquivos de mídia do `tipo` (video|audio)."""
    aceitos = VIDEO if tipo == "video" else AUDIO | VIDEO      # música pode vir dentro de um vídeo
    if not pasta:
        try:
            pasta = json.loads(_lembradas(dados).read_text(encoding="utf-8")).get(tipo, "")
        except (OSError, json.JSONDecodeError):
            pasta = ""
        if not pasta or not Path(pasta).is_dir():
            padrao = Path.home() / ("Videos" if tipo == "video" else "Music")
            pasta = str(padrao if padrao.is_dir() else Path.home())
    p = Path(pasta).expanduser()
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        raise ValueError(f"a pasta {pasta} não existe")
    pastas, arquivos = [], []
    try:
        itens = sorted(p.iterdir(), key=lambda x: x.name.lower())
    except PermissionError:
        raise ValueError(f"sem permissão para abrir {p}")
    for x in itens:
        if x.name.startswith((".", "$")) or x.name in ("System Volume Information",):
            continue
        try:
            if x.is_dir():
                pastas.append(x.name)
            elif x.suffix.lower() in aceitos:
                arquivos.append({"nome": x.name, "mb": round(x.stat().st_size / 1e6, 1)})
        except OSError:
            continue
    return {"pasta": str(p), "pai": str(p.parent) if p.parent != p else None,
            "pastas": pastas, "arquivos": arquivos, "atalhos": _atalhos(dados)}


def _tempo(valor, nome: str) -> str | None:
    v = str(valor or "").strip().replace(",", ".")
    if not v:
        return None
    if not TEMPO.match(v):
        raise ValueError(f"{nome}: use segundos ou h:mm:ss, ex.: 1:23:10")
    return v


def _intervalo(corpo: dict, chave: str, nome: str) -> str | None:
    a, b = _tempo(corpo.get(f"{chave}_inicio"), f"{nome} (início)"), _tempo(corpo.get(f"{chave}_fim"), f"{nome} (fim)")
    if not a and not b:
        return None
    if not (a and b):
        raise ValueError(f"{nome}: preencha o início e o fim, ou deixe os dois em branco")
    if edit.ler_tempo(b) <= edit.ler_tempo(a):
        raise ValueError(f"{nome}: o fim precisa vir depois do início")
    return f"{a}-{b}"


def argumentos(corpo: dict) -> tuple[list[str], str]:
    """Pedido do formulário -> argumentos do `python -m cortes edit`. Tudo vai como `--opcao=valor`:
    um tema começando com "-" não vira opção por engano."""
    filme, extra_f, nome_f = _fonte(corpo, "filme")
    musica, extra_m, nome_m = _fonte(corpo, "musica")
    args = ["edit", filme, musica] + extra_f + extra_m
    if tema := str(corpo.get("tema") or "").strip()[:300]:
        args.append(f"--tema={tema}")
    if trecho := _intervalo(corpo, "trecho", "Trecho do filme"):
        args.append(f"--trecho={trecho}")
    if gancho := _intervalo(corpo, "gancho", "Gancho"):
        args.append(f"--gancho={gancho}")
    if drop_filme := _tempo(corpo.get("drop_filme"), "Drop no filme"):
        args.append(f"--drop-filme={drop_filme}")
    if fala_drop := _tempo(corpo.get("fala_drop"), "Fala no drop"):
        if not drop_filme:
            raise ValueError("a fala no drop precisa do drop no filme")
        args.append(f"--fala-drop={fala_drop}")
    if (df := str(corpo.get("drop_fala") or "")) in ("depois", "durante"):
        args.append(f"--drop-fala={df}")
    if (ritmo := str(corpo.get("ritmo") or "")) in ("rapido", "normal", "lento"):
        args.append(f"--ritmo={ritmo}")
    if (ab := str(corpo.get("abertura") or "")) in ("sim", "nao"):
        args.append(f"--abertura={ab}")
    if drop := _tempo(corpo.get("drop"), "Drop"):
        args.append(f"--drop={drop}")
    if (prop := str(corpo.get("proporcao") or "")) in ("4:5", "9:16"):
        args.append(f"--proporcao={prop}")
    if corpo.get("slowed") not in (None, ""):
        v = float(corpo["slowed"])
        if not 0.5 <= v <= 1.2:
            raise ValueError("velocidade da música entre 0,5 e 1,2")
        args.append(f"--slowed={v}")
    if corpo.get("duracao") not in (None, ""):
        v = float(corpo["duracao"])
        if not 5 <= v <= 60:
            raise ValueError("a parte da música precisa ter entre 5 e 60 segundos")
        args.append(f"--duracao={v:g}")
    if (vm := str(corpo.get("volume_musica") or "")) in ("0.5", "0.7", "1", "1.3"):
        args.append(f"--volume-musica={vm}")
    if (mg := str(corpo.get("musica_gancho") or "")) in ("sim", "nao"):
        args.append(f"--musica-no-gancho={mg}")
    if (idioma := str(corpo.get("idioma") or "").strip()):
        from . import edit
        args.append(f"--idioma={edit.ler_idioma(idioma)}")
    if (trans := str(corpo.get("transicoes") or "").strip()):
        from . import edit
        edit.ler_transicoes(trans)              # recusa aqui o que o comando recusaria
        args.append(f"--transicoes={trans}")
    for chave, opcao in (("sem_ia", "--sem-ia"), ("so_planejar", "--so-planejar"), ("prontos", "--prontos")):
        if corpo.get(chave):
            args.append(opcao)
    return args, f"Edit: {nome_f} + {nome_m}"


def _fonte(corpo: dict, campo: str) -> tuple[str, list[str], str]:
    """O filme (ou a música) do formulário: um arquivo do computador ou um endereço do YouTube,
    com a qualidade do download. Devolve (argumento, opções extras, nome para o título)."""
    from . import youtube
    audio = campo == "musica"
    nome = "música" if audio else "filme"
    valor = str(corpo.get(campo) or "").strip().strip('"')
    if youtube.eh_url(valor) or corpo.get(f"{campo}_de") == "youtube":
        url = youtube.validar(valor)
        q = youtube.qualidade(corpo.get(f"{campo}_qualidade"), audio)
        return url, [f"--qualidade-{campo}={q}"], f"YouTube ({nome})"
    arq = Path(valor)
    if not arq.is_file():
        raise ValueError(f"escolha o arquivo d{'a' if audio else 'o'} {nome}, ou cole o endereço do YouTube")
    tipos = AUDIO | VIDEO if audio else VIDEO
    if arq.suffix.lower() not in tipos:
        raise ValueError(f"{'a música precisa ser um áudio' if audio else 'o filme precisa ser um vídeo'} "
                         f"({', '.join(sorted(AUDIO if audio else VIDEO))})")
    return str(arq), [], arq.stem


# ------------------------------------------------------------------ edits feitos

def pasta_edit(dados: Path, ident: str) -> Path:
    if not IDENT.match(ident or ""):
        raise ValueError("edit inválido")
    p = dados / "edits" / ident
    if not (p / "plano.json").exists():
        raise FileNotFoundError("esse edit não existe mais")
    return p


def video(dados: Path, ident: str) -> Path:
    v = pasta_edit(dados, ident) / "edit.mp4"
    if not v.exists():
        raise FileNotFoundError("esse edit ainda não foi renderizado")
    return v


def listar(dados: Path) -> list[dict]:
    saida = []
    for plano in (dados / "edits").glob("*/*/plano.json"):
        try:
            d = json.loads(plano.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pasta, v = plano.parent, plano.parent / "edit.mp4"
        saida.append({
            "id": f"{pasta.parent.name}/{pasta.name}",
            "filme": Path(d.get("filme", "")).name, "musica": Path(d.get("musica_original", "")).name,
            "titulo": d.get("titulo", ""), "descricao": d.get("descricao", ""), "hashtags": d.get("hashtags", []),
            "gancho": " ".join(p["w"] for p in d.get("gancho", {}).get("palavras", [])),
            "gancho_inicio": d.get("gancho", {}).get("inicio"),
            "duracao": d.get("duracao"), "bpm": d.get("bpm"), "cortes": len(d.get("cortes", [])),
            "motivo": (d.get("ia") or {}).get("motivo", ""), "com_ia": bool(d.get("ia")),
            "renderizado": v.exists(), "bytes": v.stat().st_size if v.exists() else 0,
            "quando": max(plano.stat().st_mtime, v.stat().st_mtime if v.exists() else 0),
            "plano": str(plano),
        })
    return sorted(saida, key=lambda e: e["quando"], reverse=True)


def salvar_texto(dados: Path, ident: str, corpo: dict) -> None:
    """Título, descrição e hashtags editados no painel: vão para o plano e para o edit.txt."""
    arq = pasta_edit(dados, ident) / "plano.json"
    d = json.loads(arq.read_text(encoding="utf-8"))
    if "titulo" in corpo:
        d["titulo"] = str(corpo["titulo"])[:100]
    if "descricao" in corpo:
        d["descricao"] = str(corpo["descricao"])[:2000]
    if "hashtags" in corpo:
        d["hashtags"] = [h.lstrip("#").strip().lower() for h in re.split(r"[\s,]+", str(corpo["hashtags"])) if h.strip("#")][:8]
    arq.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    if (arq.parent / "edit.mp4").exists():
        tags = " ".join("#" + h for h in d["hashtags"])
        (arq.parent / "edit.txt").write_text(f"{d['titulo']}\n\n{d['descricao']}\n\n{tags}\n", encoding="utf-8")


def para_prontos(dados: Path, ident: str) -> str:
    return str(edit.copiar_para_prontos(video(dados, ident), config.carregar()) or "")


# ------------------------------------------------------------------ ajuste do drop e do gancho
#
# A tela de ajuste mostra o filme quadro a quadro (o navegador não toca mkv/HEVC de filme, então
# cada quadro vem do ffmpeg, já no recorte vertical do edit), a música desenhada com as batidas e
# as falas da transcrição. O editor marca o gancho, o momento do drop e a fala do gatilho; o painel
# refaz o plano sem IA (`edit.replanejar`) e gera uma prévia rápida.

def _plano(dados: Path, ident: str) -> tuple[Path, dict]:
    arq = pasta_edit(dados, ident) / "plano.json"
    return arq, json.loads(arq.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=32)
def _info_filme(caminho: str) -> tuple[int, int, float, float]:
    """(largura, altura, duração, fps) do filme: o ffmpeg -i custa, e a tela pede muitos quadros."""
    from . import cenas
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", caminho], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    w, h = cenas.tamanho(Path(caminho))
    return w, h, cenas.duracao(Path(caminho)), float(m.group(1)) if m else 24.0


def quadro(dados: Path, ident: str, t: float, largura: int = 360) -> bytes:
    """O quadro do filme no segundo `t`, no recorte vertical do edit (sem as tarjas)."""
    from . import cenas
    _, d = _plano(dados, ident)
    w, h, dur, _ = _info_filme(d["filme"])
    t = min(max(0.0, float(t)), max(0.0, dur - 0.05))
    largura = min(max(120, int(largura)), 720)
    rec = cenas._recorte(w, h, edit._proporcao(d["estilo"]["proporcao"]), d.get("tarja"))
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", d["filme"], "-frames:v", "1",
                        "-vf", f"{rec},scale={largura}:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "4", "-"],
                       capture_output=True)
    if r.returncode or not r.stdout:
        raise RuntimeError("não consegui tirar o quadro do filme")
    return r.stdout


def audio(dados: Path, ident: str) -> Path:
    """A música já tratada (slowed) do edit, para ouvir o drop na tela de ajuste."""
    _, d = _plano(dados, ident)
    return config.absoluto(d["musica"])


def linha(dados: Path, ident: str) -> dict:
    """Tudo que a tela de ajuste desenha: o plano, a música (onda e batidas) e as falas."""
    import numpy as np
    from . import batidas
    arq, d = _plano(dados, ident)
    pasta = arq.parent
    w, h, dur_filme, fps = _info_filme(d["filme"])
    wav = config.absoluto(d["musica"])
    mus = edit._ler_json(pasta / "batidas.json")
    if mus is None:
        mus = batidas.analisar(wav)
        edit._gravar_json(pasta / "batidas.json", mus)
    sr, passo = 8000, 0.05
    y = np.abs(batidas.carregar(wav, sr))
    n = len(y) // int(sr * passo)
    picos = y[:n * int(sr * passo)].reshape(n, -1).max(axis=1) if n else np.zeros(0)
    onda = (picos / (picos.max() or 1) * 100).round().astype(int).tolist()

    analise = d.get("analise") or {}
    arq_falas = config.absoluto(analise["falas"]) if analise.get("falas") else edit._mais_novo(pasta.parent, "falas_*.json")
    palavras = (edit._ler_json(arq_falas) if arq_falas and arq_falas.exists() else None) or []
    if len(palavras) > 6000:            # filme inteiro: só a região do gancho e do drop
        centro = d["gancho"]["inicio"] if d["gancho"]["fim"] > d["gancho"]["inicio"] else (d.get("drop_filme") or 0)
        palavras = [p for p in palavras if abs(p["s"] - centro) < 300]

    fd = d.get("fala_drop")
    gatilho = d.get("gatilho") or {"momento": d.get("drop_filme"), "fala_fim": fd["fim"] if fd else None,
                                   "modo": d.get("drop_fala") or ("durante" if fd else "depois")}
    g = d["gancho"]
    return {
        "filme": {"nome": Path(d["filme"]).name, "duracao": dur_filme, "fps": fps},
        "musica": {"duracao": len(y) / sr, "passo": passo, "onda": onda,
                   "batidas": [round(b, 3) for b in mus["batidas"]], "bpm": mus["bpm"]},
        "plano": {
            "gancho": {"inicio": g["inicio"], "fim": g["fim"], "texto": " ".join(p["w"] for p in g["palavras"])}
            if g["fim"] > g["inicio"] else None,
            "drop": d["drop"], "gatilho": gatilho, "duracao": d["duracao"],
            "volume_musica": (d.get("estilo") or {}).get("volume_musica", 1.0),
            "musica_no_gancho": (d.get("estilo") or {}).get("musica_no_gancho", True),
            "ritmo": d.get("ritmo") or "normal",
            "duracao_musica": round(d["duracao"] - (d.get("abertura_dur") or 0) - (g["fim"] - g["inicio"]), 2),
            "abertura": bool(d.get("abertura_falas")), "abertura_falas": len(d.get("abertura_falas") or []),
            "transicoes": (d.get("config") or {}).get("transicoes", edit.PADRAO["transicoes"]),
            "abertura_dur": d.get("abertura_dur") or 0,
            "cortes": [{"saida": c["saida"], "dur": c["dur"], "cena": c["cena"], "fonte": c["fonte"], "vel": c["vel"],
                        "transicao": c.get("transicao")} for c in d["cortes"]],
            "cortes_editados": bool(d.get("cortes_editados")),
        },
        "palavras": [{"w": p["w"], "s": p["s"], "e": p["e"]} for p in palavras],
        "tem_anterior": (pasta / "plano.anterior.json").exists(),
        "tem_previa": (pasta / "previa.mp4").exists(),
    }


def ajustar(dados: Path, ident: str, corpo: dict) -> dict:
    """Valida o que veio da tela e refaz o plano (sem IA). Devolve o resumo para a tela."""
    arq, d = _plano(dados, ident)
    _, _, dur_filme, _ = _info_filme(d["filme"])

    def tempo(chave: str, maximo: float) -> float | None:
        v = corpo.get(chave)
        if v in (None, ""):
            return None
        v = float(v)
        if not 0 <= v <= maximo:
            raise ValueError(f"{chave}: fora do filme (0 a {maximo:.0f}s)")
        return v

    gancho = corpo.get("gancho")
    if gancho:
        a, b = (float(x) for x in gancho)
        if not 0 <= a < b <= dur_filme:
            raise ValueError("o gancho precisa terminar depois de começar, dentro do filme")
        gancho = [a, b]
    modo = corpo.get("drop_fala") or "depois"
    if modo not in ("depois", "durante"):
        raise ValueError("drop_fala: depois ou durante")
    volume = corpo.get("volume_musica")
    if volume not in (None, ""):
        volume = float(volume)
        if not 0.2 <= volume <= 2.0:
            raise ValueError("volume da música entre 20% e 200%")
    else:
        volume = None
    ajuste = {"gancho": gancho, "drop_filme": tempo("drop_filme", dur_filme), "fala_fim": tempo("fala_fim", dur_filme),
              "drop_fala": modo, "drop_musica": tempo("drop_musica", 3600), "volume_musica": volume}
    # ajustes gerais (aba Geral): o que não vier fica como está
    if (ritmo := corpo.get("ritmo")) not in (None, ""):
        if ritmo not in ("rapido", "normal", "lento"):
            raise ValueError("ritmo: rapido, normal ou lento")
        ajuste["ritmo"] = ritmo
    if corpo.get("duracao_musica") not in (None, ""):
        dm = float(corpo["duracao_musica"])
        if not 5 <= dm <= 60:
            raise ValueError("a parte da música precisa ter entre 5 e 60 segundos")
        ajuste["duracao_musica"] = dm
    if corpo.get("transicoes") is not None:
        ajuste["transicoes"] = edit.ler_transicoes(str(corpo["transicoes"]))
    for chave in ("abertura", "musica_no_gancho"):
        if corpo.get(chave) is not None:
            ajuste[chave] = bool(corpo[chave])
    if ajuste["fala_fim"] is not None and (ajuste["drop_filme"] is None or ajuste["fala_fim"] <= ajuste["drop_filme"]):
        raise ValueError("a fala do gatilho termina depois do momento do drop: marque o drop antes")
    edit.replanejar(arq, ajuste, aviso=lambda *a: None)
    return linha(dados, ident)["plano"]


def desfazer(dados: Path, ident: str) -> dict:
    arq, _ = _plano(dados, ident)
    edit.desfazer_ajuste(arq)
    return linha(dados, ident)["plano"]


def planos(dados: Path, ident: str) -> list[dict]:
    """Os planos do filme que têm miniatura (os candidatos), para trocar o plano de um corte."""
    arq, d = _plano(dados, ident)
    arq_planos, _ = edit.arquivos_da_analise(d, arq)
    cs = (edit._ler_json(arq_planos) if arq_planos else None) or []
    usados = {c["cena"] for c in d["cortes"]}
    return [{"id": c["id"], "inicio": c["inicio"], "fim": c["fim"], "brilho": c.get("brilho"),
             "usado": c["id"] in usados} for c in cs if c.get("mini")]


def miniatura(dados: Path, ident: str, cena: int) -> Path:
    arq, d = _plano(dados, ident)
    arq_planos, _ = edit.arquivos_da_analise(d, arq)
    c = next((x for x in (edit._ler_json(arq_planos) if arq_planos else None) or [] if x["id"] == int(cena)), None)
    if not c or not c.get("mini"):
        raise FileNotFoundError("esse plano não tem miniatura")
    m = config.absoluto(c["mini"]).resolve()
    if dados.resolve() not in m.parents and config.RAIZ.resolve() not in m.parents:
        raise ValueError("miniatura fora da pasta de dados")
    return m


def editar_corte(dados: Path, ident: str, corpo: dict) -> dict:
    arq, _ = _plano(dados, ident)
    edit.editar_corte(arq, corpo)
    return linha(dados, ident)["plano"]


def previa(dados: Path, ident: str) -> Path:
    v = pasta_edit(dados, ident) / "previa.mp4"
    if not v.exists():
        raise FileNotFoundError("a prévia ainda não foi gerada")
    return v
