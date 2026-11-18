"""Painel local de revisão e publicação: http://localhost:8800

- Lives: lista os VODs recentes do streamer e processa o escolhido com um clique.
- Revisão: assiste aos cortes de todos os canais, edita título/descrição/hashtags, aprova ou rejeita.
- Ao aprovar: escolhe em quais contas publicar e quando (próximo horário livre, agora ou data/hora).
- Fila: acompanha, cancela, adianta ou tenta de novo cada publicação.
- Contas: vincula canais do YouTube e contas do TikTok (login no site de cada um) e define as contas
  padrão de cada streamer.

Só escuta em 127.0.0.1 e recusa pedidos vindos de outros sites (checagem de Host/Origin), para que
uma página qualquer aberta no navegador não consiga publicar nada em seu nome.
"""
import html as html_mod
import json
import re
import shutil
import subprocess
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import config, contas, fila, trabalho

_trava = threading.Lock()
SEGURO = re.compile(r"^[\w.-]+$")
LISTAS = {"candidatos": "curto", "longos": "tiktok", "compilacoes": "compilacao"}


# ------------------------------------------------------------------ cortes

_fichas: dict[tuple, dict] = {}


def ficha(p: Path) -> dict:
    """Tamanho e resolucao do mp4. O ffprobe custa caro para rodar a cada listagem,
    entao guardamos por (caminho, mtime): o arquivo so muda se for re-renderizado."""
    st = p.stat()
    chave = (str(p), st.st_mtime_ns)
    if (f := _fichas.get(chave)) is not None:
        return f
    f = {"bytes": st.st_size, "largura": None, "altura": None}
    try:
        saida = subprocess.run(
            [config.ffmpeg(), "-hide_banner", "-i", str(p)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20).stderr
        if m := re.search(r"Video:.*?,\s(\d{2,5})x(\d{2,5})", saida):
            f["largura"], f["altura"] = int(m.group(1)), int(m.group(2))
    except (OSError, subprocess.SubprocessError):
        pass
    _fichas[chave] = f
    return f


def _arquivos_json(dados: Path) -> list[Path]:
    return sorted(dados.glob("*/candidatos/*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def listar(dados: Path) -> list[dict]:
    publicacoes: dict[str, list] = {}
    for item in fila.listar():
        if item["status"] != "cancelado":
            publicacoes.setdefault(item["corte_id"], []).append(
                {"conta": item["conta_nome"], "conta_id": item["conta_id"], "plataforma": item["plataforma"], "status": item["status"],
                 "quando": item["agendado_para"], "url": (item.get("resultado") or {}).get("url"),
                 "modo": (item.get("resultado") or {}).get("modo")})
    saida = []
    for arq in _arquivos_json(dados):
        canal, live = arq.parent.parent.name, arq.stem
        d = json.loads(arq.read_text(encoding="utf-8"))
        textos = {c.get("id"): c.get("texto", "") for c in d.get("candidatos", [])}
        for lista, formato in LISTAS.items():
            for i, c in enumerate(d.get(lista) or []):
                if not c.get("arquivo") or not config.absoluto(c["arquivo"]).exists():
                    continue
                ia = c.get("ia") or {}
                rev = c.get("revisao") or {}
                texto = c.get("texto", "") if lista != "compilacoes" else " … ".join(textos.get(p, "") for p in c["partes"])
                ident = f"{canal}/{live}/{lista}/{i}"
                saida.append({
                    "id": ident, "canal": canal, "live": live.removesuffix("_audio"),
                    "formato": formato, "inicio": c["inicio"],
                    "duracao": round(c.get("duracao") or (c["fim"] - c["inicio"])),
                    "partes": len(c.get("partes", [])),
                    "nota": c.get("nota"), "nota_ia": ia.get("nota"), "motivo_ia": ia.get("motivo", ""),
                    "texto": texto,
                    "titulo": rev.get("titulo", ia.get("titulo", "")),
                    "descricao": rev.get("descricao", ia.get("descricao", "")),
                    "hashtags": rev.get("hashtags", ia.get("hashtags", [])),
                    "status": rev.get("status", "pendente"),
                    "capa_t": rev.get("capa_t"),
                    **ficha(config.absoluto(c["arquivo"])),
                    "publicacoes": publicacoes.get(ident, []),
                })
    return saida


def _localizar(dados: Path, ident: str) -> tuple[Path, str, int]:
    canal, live, lista, idx = ident.split("/")
    if not (SEGURO.match(canal) and SEGURO.match(live) and lista in LISTAS and idx.isdigit()):
        raise ValueError("id inválido")
    return dados / canal / "candidatos" / f"{live}.json", lista, int(idx)


def _slug(texto: str, limite: int = 48) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:limite].strip("-")


def exportar(canal: str, c: dict) -> str | None:
    """Copia o corte aprovado para a pasta de prontos, com a legenda num .txt ao lado.

    Serve enquanto as contas de publicacao nao estao vinculadas: o video e o texto ficam juntos,
    prontos para subir a mao. Devolve o nome do arquivo copiado."""
    destino_pasta = config.pasta_prontos(config.carregar())
    if not destino_pasta or not c.get("arquivo"):
        return None
    origem = config.absoluto(c["arquivo"])
    if not origem.exists():
        return None
    rev = c.get("revisao") or {}
    titulo = rev.get("titulo") or (c.get("ia") or {}).get("titulo") or ""
    nome = f"{canal}-{int(c['inicio'])}" + (f"-{_slug(titulo)}" if titulo else "")
    destino_pasta.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino_pasta / f"{nome}.mp4")
    hashtags = " ".join("#" + h for h in rev.get("hashtags", []))
    legenda = [x for x in (titulo, rev.get("descricao", ""), hashtags) if x]
    (destino_pasta / f"{nome}.txt").write_text("\n".join(legenda) + "\n", encoding="utf-8")
    return f"{nome}.mp4"


def capa_bytes(video: Path, t: float, largura: int = 540) -> bytes:
    """Um quadro do corte, em JPEG. E o mesmo quadro que vira a capa no arquivo exportado."""
    r = subprocess.run(
        [config.ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={largura}:-2", "-f", "mjpeg", "-q:v", "3", "-"],
        capture_output=True, timeout=30)
    if not r.stdout:
        raise RuntimeError("não consegui tirar o quadro nesse instante")
    return r.stdout


def _apagar_exportado(nome: str) -> None:
    pasta = config.pasta_prontos(config.carregar())
    if not pasta or not nome:
        return
    for arq in (pasta / nome, (pasta / nome).with_suffix(".txt"), (pasta / nome).with_suffix(".jpg")):
        try:
            arq.unlink(missing_ok=True)
        except OSError:
            pass


def atualizar(dados: Path, ident: str, mudancas: dict) -> dict:
    arq, lista, idx = _localizar(dados, ident)
    with _trava:
        d = json.loads(arq.read_text(encoding="utf-8"))
        c = d[lista][idx]
        rev = c.setdefault("revisao", {})
        if "capa_t" in mudancas:
            rev["capa_t"] = max(0.0, float(mudancas["capa_t"]))
        for k in ("titulo", "descricao", "status"):
            if k in mudancas:
                rev[k] = str(mudancas[k])[:500]
        if "hashtags" in mudancas:
            rev["hashtags"] = [str(h).strip().lstrip("#") for h in mudancas["hashtags"] if str(h).strip()][:10]
        if rev.get("status") not in ("pendente", "aprovado", "rejeitado"):
            rev["status"] = "pendente"
        # aprovado -> copia para a pasta de prontos; desaprovado -> tira de la
        if rev["status"] == "aprovado":
            if nome := exportar(d.get("canal", ""), c):
                rev["exportado"] = nome
        elif (antigo := rev.pop("exportado", None)):
            _apagar_exportado(antigo)
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(arq)
        return c


def _para_ia(dados: Path, ident: str) -> tuple[dict, dict, dict]:
    """(corte, canal, cfg) prontos para virar prompt."""
    arq, lista, idx = _localizar(dados, ident)
    d = json.loads(arq.read_text(encoding="utf-8"))
    c = d[lista][idx]
    cfg = config.carregar()
    canal = cfg["canais"].get(ident.split("/")[0], {})
    if lista == "compilacoes":   # a compilação não tem palavras próprias: junta as das partes
        por_id = {x.get("id"): x for x in d.get("candidatos", [])}
        partes = [por_id[i] for i in c.get("partes", []) if i in por_id]
        c = {**c, "palavras": [p for x in partes for p in x.get("palavras", [])],
             "inicio": min((x["inicio"] for x in partes), default=c["inicio"]),
             "fim": max((x["fim"] for x in partes), default=c["fim"])}
    return c, canal, cfg


def prompt_legenda(dados: Path, ident: str) -> str:
    """O prompt pronto para colar em qualquer chat, para quem não tem credencial de IA."""
    from . import ia

    return ia.prompt_avulso(*_para_ia(dados, ident))


def gerar_legenda(dados: Path, ident: str) -> dict:
    """Pede o título/descrição/hashtags à IA e já salva no corte."""
    from . import ia

    legenda = ia.legenda_para(*_para_ia(dados, ident))
    atualizar(dados, ident, legenda)
    return {"ok": True, **legenda}


# ------------------------------------------------------------- enquadramento

_oficina: dict = {}


def trecho_bruto(dados: Path, ident: str) -> Path | None:
    """O pedaço de VOD de onde o corte foi renderizado. É o melhor frame para enquadrar:
    é exatamente a cena que o revisor está olhando."""
    arq, lista, idx = _localizar(dados, ident)
    c = json.loads(arq.read_text(encoding="utf-8"))[lista][idx]
    if not c.get("arquivo"):
        return None
    destino = config.absoluto(c["arquivo"])
    bruto = destino.parent.parent.parent / "vods" / "trechos" / f"{destino.stem}_bruto.mp4"
    return bruto if bruto.exists() else None


AMOSTRA = (0.08, 0.5, 0.92)   # começo, meio e fim: é onde dá para ver se a cam andou de lugar


def amostra_do_vod(dados: Path, nome_canal: str, url: str) -> tuple[Path, str, list[Path]]:
    """Três frames de uma live ainda não processada: começo, meio e fim.

    Baixa só 4 segundos em cada ponto (o VOD inteiro são dezenas de GB), para dar para enquadrar
    antes de processar — e para a cam fora do lugar aparecer antes de render nenhum.
    """
    from . import enquadrar, vod as mod_vod

    info = mod_vod.informacoes(url)
    ident, duracao = info["id"], info["duracao"]
    if not duracao:
        raise ValueError("não consegui ler a duração desse VOD")
    pasta = dados / nome_canal / "vods" / "trechos"
    pasta.mkdir(parents=True, exist_ok=True)
    quadros = dados / nome_canal / "_frames"
    quadros.mkdir(parents=True, exist_ok=True)

    frames, primeiro = [], None
    for i, f in enumerate(AMOSTRA, 1):
        t = duracao * f
        trecho = pasta / f"{ident}_amostra{i}.mp4"
        try:
            comeco = mod_vod.baixar_trecho(url, t, t + 4, trecho)
        except (subprocess.CalledProcessError, RuntimeError, OSError) as e:
            raise RuntimeError(f"não deu para baixar a amostra em {t / 3600:.1f}h: {e}") from e
        primeiro = primeiro or trecho
        alvo = quadros / f"frame{i}.png"
        alvo.unlink(missing_ok=True)
        if enquadrar.frame(trecho, alvo, comeco + 1, 1.0):
            frames.append(alvo)
    if not frames:
        raise RuntimeError("não consegui tirar nenhum frame desse VOD")
    return primeiro, ident, frames


def abrir_oficina(dados: Path, nome_canal: str, video: Path, porta: int = 8810,
                  vod: str = "", corte: str = "", frames: list[Path] | None = None) -> str:
    """Sobe (ou troca o vídeo d)a ferramenta de enquadramento, sem travar o painel.

    Com `corte`, o ajuste fica só naquele corte e salvar já manda recompilá-lo — é o que faz o
    botão da Revisão valer alguma coisa. Com `vod`, vale para a live inteira dali em diante.
    """
    from . import enquadrar

    if srv := _oficina.get("srv"):
        srv.shutdown()
        srv.server_close()
    cfg = config.carregar()
    canal = config.canal(cfg, nome_canal)
    destino = enquadrar.arquivo(dados, nome_canal, vod=vod, corte=corte)
    alvo = "este corte" if corte else (f"a live {vod}" if vod else "o canal")

    def depois(_):
        if not corte:
            return None
        return trabalho.comecar_funcao("recompilando o corte com o enquadramento novo",
                                       nome_canal, lambda log: str(rerenderizar(dados, corte)["arquivo"]))

    srv = enquadrar.criar(video, nome_canal, canal, dados, porta, destino=destino, alvo=alvo,
                          ao_salvar=depois, frames=frames)
    _oficina["srv"] = srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://localhost:{porta}"


def rerenderizar(dados: Path, ident: str) -> dict:
    """Gera de novo o mp4 desse corte com o enquadramento atual, reaproveitando o trecho já baixado."""
    from . import enquadrar, legendas, render

    arq, lista, idx = _localizar(dados, ident)
    d = json.loads(arq.read_text(encoding="utf-8"))
    c = d[lista][idx]
    if lista == "compilacoes":
        raise ValueError("compilação é feita das partes: re-renderize os cortes que a compõem")
    if not c.get("arquivo"):
        raise ValueError("esse corte não tem vídeo renderizado")
    destino = config.absoluto(c["arquivo"])
    fonte = trecho_bruto(dados, ident)
    if fonte is None:
        raise ValueError("o trecho bruto desse corte não está mais em disco: reprocesse a live")
    cfg = config.carregar()
    nome_canal = d.get("canal", ident.split("/")[0])
    # o id do corte traz o arquivo de áudio (v123_audio); o enquadramento é do VOD (v123)
    canal = enquadrar.aplicar(config.canal(cfg, nome_canal), dados, nome_canal,
                              vod=ident.split("/")[1].removesuffix("_audio"), corte=ident)
    # o trecho de HLS costuma guardar o tempo do VOD (começa em 17679s, por exemplo), e aí o
    # início do corte é o deslocamento dentro dele. Mas nem todo trecho vem assim: alguns começam
    # em zero. Pedir 17679s de um arquivo de 56s faz o ffmpeg devolver um mp4 vazio e sair com
    # sucesso — silêncio que já custou um corte quebrado. Quando a conta não cabe no arquivo,
    # o trecho é o próprio corte.
    comeco, final = enquadrar.intervalo(fonte)
    duracao = final - comeco
    ini, fim = c["inicio"] - comeco, c["fim"] - comeco
    if not (-0.5 <= ini < fim <= duracao + 1):
        ini, fim = 0.0, min(duracao, c["fim"] - c["inicio"])
    ass = None
    if c.get("palavras"):
        ass = legendas.gerar_ass(c["palavras"], c["inicio"], c["fim"], destino.with_suffix(".ass"),
                                 render.posicao_legenda(canal))
    render.renderizar(fonte, ini, fim, destino, canal, ass)
    # o ffmpeg sai com sucesso mesmo quando não escreveu quadro nenhum; sem esta conferência
    # o painel diz "pronto" e troca um corte bom por um arquivo vazio
    if destino.stat().st_size < 100_000:
        raise RuntimeError(f"a recompilação saiu vazia ({destino.stat().st_size} bytes): "
                           f"o trecho bruto não cobre {ini:.0f}s–{fim:.0f}s")
    _fichas.clear()
    rev = c.get("revisao") or {}
    if rev.get("status") == "aprovado":   # o que já foi para prontos tem que acompanhar
        exportar(d.get("canal", ""), c)
    return {"arquivo": config.relativo(destino)}


def caminho_video(dados: Path, ident: str) -> Path:
    arq, lista, idx = _localizar(dados, ident)
    c = json.loads(arq.read_text(encoding="utf-8"))[lista][idx]
    p = config.absoluto(c["arquivo"]).resolve()
    if dados.resolve() not in p.parents:
        raise ValueError("fora da pasta de dados")
    return p


def publicar(dados: Path, pedido: dict) -> list[dict]:
    """Aprova o corte (salvando título/descrição/hashtags) e agenda nas contas escolhidas."""
    cfg = config.carregar()
    ident = pedido["corte_id"]
    if not str(pedido.get("titulo", "")).strip():
        raise ValueError("escreva um título antes de publicar")
    if not pedido.get("contas"):
        raise ValueError("escolha pelo menos uma conta")
    if pedido.get("modo") not in ("proximo", "agora", "data"):
        raise ValueError("modo de agendamento inválido")
    if pedido["modo"] == "data" and not pedido.get("data"):
        raise ValueError("escolha a data e hora")
    arq, lista, idx = _localizar(dados, ident)
    atual = json.loads(arq.read_text(encoding="utf-8"))[lista][idx]
    duracao = atual.get("duracao") or (atual["fim"] - atual["inicio"])
    escolhidas = []
    for cid in pedido["contas"]:
        conta = contas.obter(cid)
        if conta is None:
            raise ValueError("conta não encontrada")
        if not contas.compativel(conta, duracao):
            raise ValueError(f"{conta['nome']} não aceita vídeos de {duracao:.0f}s")
        escolhidas.append(conta)
    opcoes = {}
    if any(ct["plataforma"] == "tiktok" for ct in escolhidas):
        opcoes["tiktok"] = opcoes_tiktok(pedido.get("tiktok") or {}, escolhidas)

    c = atualizar(dados, ident, {"status": "aprovado", "titulo": pedido["titulo"],
                                 "descricao": pedido.get("descricao", ""), "hashtags": pedido.get("hashtags", [])})
    rev = c["revisao"]
    canal = cfg["canais"].get(ident.split("/")[0], {})
    corte = {"id": ident, "arquivo": c["arquivo"], "titulo": rev["titulo"], "descricao": rev.get("descricao", ""),
             "hashtags": rev.get("hashtags", []), "credito": canal.get("credito", ""), "duracao": round(duracao, 1)}
    privacidade = pedido.get("privacidade") if pedido.get("privacidade") in ("public", "unlisted", "private") else None
    return fila.agendar(corte, pedido["contas"], pedido["modo"], cfg, pedido.get("data"), privacidade, opcoes)


def opcoes_tiktok(tk: dict, escolhidas: list[dict]) -> dict:
    """Valida as escolhas do TikTok (as regras de postagem direta vêm das diretrizes do TikTok)."""
    from . import pub_tiktok

    modo = tk.get("modo")
    if modo not in pub_tiktok.MODOS:
        raise ValueError("escolha como enviar ao TikTok: rascunho ou direto")
    for ct in escolhidas:
        if ct["plataforma"] == "tiktok" and modo not in ct.get("modos", pub_tiktok.MODOS):
            raise ValueError(f"{ct['nome']} não autorizou o modo {modo}; vincule a conta de novo")
    if modo == "rascunho":
        return {"modo": "rascunho"}
    priv = tk.get("privacidade")
    if priv not in pub_tiktok.PRIVACIDADES:
        raise ValueError("escolha quem pode ver o vídeo no TikTok")
    if tk.get("comercial") and not (tk.get("marca_propria") or tk.get("conteudo_marca")):
        raise ValueError("indique se o conteúdo comercial promove você, uma marca parceira ou ambos")
    if tk.get("comercial") and tk.get("conteudo_marca") and priv == "SELF_ONLY":
        raise ValueError("conteúdo de marca não pode ser privado (“Só eu”) no TikTok")
    comercial = bool(tk.get("comercial"))
    return {"modo": "direto", "privacidade": priv, "comentarios": bool(tk.get("comentarios")),
            "dueto": bool(tk.get("dueto")), "costura": bool(tk.get("costura")),
            "marca_propria": comercial and bool(tk.get("marca_propria")),
            "conteudo_marca": comercial and bool(tk.get("conteudo_marca"))}


def estado() -> dict:
    from . import ia, pub_tiktok, pub_youtube

    cfg = config.carregar()
    return {
        "canais": {n: {"destino": c.get("canal_destino", n), "credito": c.get("credito", "")} for n, c in cfg["canais"].items()},
        "contas": contas.listar(),
        "plataformas": {k: v["nome"] for k, v in contas.PLATAFORMAS.items()},
        "duracao_max": {k: v["duracao_max"] for k, v in contas.PLATAFORMAS.items()},
        "ia_disponivel": ia.credenciais_disponiveis(),
        "youtube_configurado": pub_youtube.configurado(cfg),
        "youtube_credencial": cfg["publicacao"]["youtube"]["client_secret"],
        "tiktok_configurado": pub_tiktok.configurado(cfg),
        "tiktok_credencial": config.relativo(pub_tiktok.arquivo_credencial(cfg)),
        "tiktok_modo": pub_tiktok.modo_padrao(cfg),
        "privacidades_tiktok": pub_tiktok.PRIVACIDADES,
        "horarios": cfg["publicacao"]["horarios"], "fuso": cfg["publicacao"]["fuso"],
        "max_por_dia": cfg["publicacao"]["max_por_dia_por_conta"],
        "privacidade_youtube": cfg["publicacao"]["youtube"].get("privacidade", "public"),
    }


# ------------------------------------------------------------------ servidor

def servir(dados: Path, porta: int = 8800, trabalhador: bool = True) -> None:
    from . import pub_tiktok, pub_youtube

    pagina = Path(__file__).parent / "painel.html"
    estilo = Path(__file__).parent / "estilo.css"
    hosts_ok = {f"localhost:{porta}", f"127.0.0.1:{porta}"}
    origens_ok = {f"http://{h}" for h in hosts_ok}

    class H(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            corpo = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def _html(self, texto: str, status=200):
            corpo = texto.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")  # depois de atualizar o código, a página nova aparece já
            self.end_headers()
            self.wfile.write(corpo)

        def _redirecionar(self, url: str):
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in hosts_ok  # bloqueia DNS rebinding

        def _mensagem(self, titulo: str, texto: str, status=200):
            self._html(f"<!doctype html><meta charset=utf-8><title>{html_mod.escape(titulo)}</title>"
                       f"<body style='font:16px system-ui;max-width:640px;margin:40px auto;padding:0 16px'>"
                       f"<h1 style='font-size:20px'>{html_mod.escape(titulo)}</h1><p>{texto}</p>"
                       f"<p><a href='/#contas'>Voltar ao painel</a></p>", status)

        def do_GET(self):
            if not self._host_ok():
                return self.send_error(403)
            url = urlparse(self.path)
            try:
                if url.path in ("/", "/index.html"):
                    self._html(pagina.read_text(encoding="utf-8"))
                elif url.path == "/estilo.css":
                    corpo = estilo.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/css; charset=utf-8")
                    self.send_header("Content-Length", str(len(corpo)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(corpo)
                elif url.path == "/api/cortes":
                    self._json(listar(dados))
                elif url.path == "/api/estado":
                    self._json(estado())
                elif url.path == "/api/vods":
                    q = parse_qs(url.query)
                    nome = q.get("canal", [""])[0]
                    if not SEGURO.match(nome or ""):
                        raise ValueError("canal inválido")
                    try:
                        self._json({"vods": trabalho.vods(config.carregar(), nome,
                                                          atualizar=q.get("atualizar", [""])[0] == "1")})
                    except RuntimeError as e:
                        self._json({"erro": str(e)}, 502)
                elif url.path == "/api/trabalho":
                    self._json(trabalho.estado())
                elif url.path == "/api/fila":
                    self._json(sorted(fila.listar(), key=lambda i: i["agendado_para"], reverse=True))
                elif url.path.startswith("/api/prompt/"):
                    self._json({"ok": True,
                                "prompt": prompt_legenda(dados, unquote(url.path[len("/api/prompt/"):]))})
                elif url.path.startswith("/capa/"):
                    q = parse_qs(url.query)
                    quadro = capa_bytes(caminho_video(dados, unquote(url.path[len("/capa/"):])),
                                        float(q.get("t", ["0"])[0]))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(quadro)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(quadro)
                elif url.path.startswith("/video/"):
                    self._video(caminho_video(dados, unquote(url.path[len("/video/"):])))
                elif url.path == "/oauth/youtube/iniciar":
                    cfg = config.carregar()
                    if not pub_youtube.configurado(cfg):
                        return self._mensagem("Falta a credencial do YouTube",
                                              "Siga o passo a passo do README para criar a credencial no Google Cloud "
                                              f"e salve o arquivo em <code>{html_mod.escape(cfg['publicacao']['youtube']['client_secret'])}</code>.", 400)
                    self._redirecionar(pub_youtube.iniciar_vinculo(cfg, porta))
                elif url.path == "/oauth/youtube/callback":
                    q = parse_qs(url.query)
                    if "error" in q:
                        return self._mensagem("Vínculo cancelado", html_mod.escape(q["error"][0]))
                    conta = pub_youtube.concluir_vinculo(q.get("state", [""])[0], q.get("code", [""])[0])
                    self._mensagem("Canal vinculado", f"<b>{html_mod.escape(conta['nome'])}</b> foi vinculado. "
                                   "Agora escolha, na aba Contas, para quais streamers ele é conta padrão.")
                elif url.path == "/oauth/tiktok/iniciar":
                    cfg = config.carregar()
                    if not pub_tiktok.configurado(cfg):
                        return self._mensagem("Falta a credencial do TikTok",
                                              "Siga o passo a passo do README para criar o app no TikTok for Developers "
                                              f"e salve a chave em <code>{html_mod.escape(config.relativo(pub_tiktok.arquivo_credencial(cfg)))}</code>.", 400)
                    self._redirecionar(pub_tiktok.iniciar_vinculo(cfg, porta))
                elif url.path == "/oauth/tiktok/callback":
                    q = parse_qs(url.query)
                    if "error" in q:
                        return self._mensagem("Vínculo cancelado", html_mod.escape(
                            (q.get("error_description") or q["error"])[0]))
                    conta = pub_tiktok.concluir_vinculo(q.get("state", [""])[0], q.get("code", [""])[0], config.carregar())
                    self._mensagem("Conta vinculada", f"<b>{html_mod.escape(conta['nome'])}</b> foi vinculada ao painel. "
                                   "Agora escolha, na aba Contas, para quais streamers ela é conta padrão.")
                elif m := re.fullmatch(r"/api/tiktok/([\w-]+)/criador", url.path):
                    conta = contas.obter(m.group(1))
                    if conta is None or conta["plataforma"] != "tiktok":
                        return self._json({"ok": False, "erro": "conta não encontrada"}, 404)
                    try:
                        self._json({"ok": True, "criador": pub_tiktok.info_criador(conta, config.carregar())})
                    except Exception as e:  # noqa: BLE001 - mostra o motivo na janela de publicar
                        if isinstance(e, fila.ErroConta):
                            contas.atualizar(conta["id"], precisa_reconectar=True)
                        self._json({"ok": False, "erro": str(e)})
                else:
                    self.send_error(404)
            except (ValueError, KeyError, IndexError, FileNotFoundError, RuntimeError,
                    subprocess.SubprocessError, fila.ErroConta, fila.ErroCota, fila.ErroDefinitivo) as e:
                if url.path.startswith("/oauth/"):
                    self._mensagem("Não deu certo", html_mod.escape(str(e)), 400)
                else:
                    self.send_error(404)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass

        def do_POST(self):
            # Só aceita JSON vindo do próprio painel: outro site não consegue enviar
            # application/json para cá sem o navegador bloquear (CORS), e o Origin é conferido.
            origem = self.headers.get("Origin")
            if (not self._host_ok() or (origem and origem not in origens_ok)
                    or not self.headers.get("Content-Type", "").startswith("application/json")):
                return self.send_error(403)
            caminho = unquote(urlparse(self.path).path)
            try:
                tamanho = int(self.headers.get("Content-Length", 0))
                corpo = json.loads(self.rfile.read(tamanho) or b"{}")
                if caminho.startswith("/api/cortes/"):
                    atualizar(dados, caminho[len("/api/cortes/"):], corpo)
                    self._json({"ok": True})
                elif caminho == "/api/publicar":
                    itens = publicar(dados, corpo)
                    self._json({"ok": True, "itens": itens})
                elif caminho.startswith("/api/rerender/"):
                    ident = caminho[len("/api/rerender/"):]
                    bruto = trecho_bruto(dados, ident)
                    if bruto is None:
                        raise ValueError("o trecho bruto desse corte não está mais em disco")
                    self._json({"ok": True, "atual": trabalho.comecar_funcao(
                        "re-renderizando o corte", ident.split("/")[0],
                        lambda log: str(rerenderizar(dados, ident)["arquivo"]))})
                elif caminho == "/api/enquadrar":
                    nome = str(corpo.get("canal") or "")
                    if not SEGURO.match(nome):
                        raise ValueError("canal inválido")
                    ident, vod, frames = str(corpo.get("corte_id") or ""), "", None
                    if ident:
                        video = trecho_bruto(dados, ident)
                        if video is None:
                            raise ValueError("o trecho bruto desse corte não está mais em disco")
                        vod = ident.split("/")[1].removesuffix("_audio")
                    elif url_vod := str(corpo.get("url") or ""):
                        video, vod, frames = amostra_do_vod(dados, nome, url_vod)
                    else:
                        trechos = sorted((dados / nome / "vods" / "trechos").glob("*_bruto.mp4"),
                                         key=lambda p: p.stat().st_mtime, reverse=True)
                        if not trechos:
                            raise ValueError(f"nenhum trecho de {nome} baixado ainda: processe um VOD primeiro")
                        video = trechos[0]
                    self._json({"ok": True, "video": video.name,
                                "url": abrir_oficina(dados, nome, video, vod=vod, corte=ident, frames=frames)})
                elif caminho.startswith("/api/legenda/"):
                    self._json(gerar_legenda(dados, caminho[len("/api/legenda/"):]))
                elif caminho == "/api/canais":
                    nome, c = config.adicionar_canal(str(corpo.get("url") or ""),
                                                     str(corpo.get("destino") or ""))
                    self._json({"ok": True, "canal": nome,
                                "destino": c.get("canal_destino", nome), "credito": c.get("credito", "")})
                elif caminho == "/api/processar":
                    nome = str(corpo.get("canal") or "")
                    if not SEGURO.match(nome):
                        raise ValueError("canal inválido")
                    self._json({"ok": True, "atual": trabalho.comecar(
                        nome, str(corpo.get("url") or ""), str(corpo.get("titulo") or ""),
                        list(corpo.get("opcoes") or []))})
                elif caminho == "/api/contas/simulacao":
                    nome = str(corpo.get("nome") or "").strip()[:60] or "Conta de teste"
                    self._json({"ok": True, "conta": contas.adicionar("simulacao", nome)})
                elif m := re.fullmatch(r"/api/contas/([\w-]+)/remover", caminho):
                    contas.remover(m.group(1))
                    self._json({"ok": True})
                elif m := re.fullmatch(r"/api/contas/([\w-]+)", caminho):
                    self._json({"ok": True, "conta": contas.atualizar(m.group(1), canais=corpo.get("canais", []))})
                elif m := re.fullmatch(r"/api/fila/([\w-]+)/(cancelar|tentar|agora)", caminho):
                    self._json({"ok": True, "item": fila.acao(m.group(1), m.group(2))})
                else:
                    self.send_error(404)
            except (ValueError, KeyError, IndexError, FileNotFoundError, StopIteration, RuntimeError) as e:
                self._json({"ok": False, "erro": str(e) or "pedido inválido"}, 400)

        def _video(self, p: Path):
            """Serve o mp4 com suporte a Range (necessário para o player avançar/voltar)."""
            total = p.stat().st_size
            ini, fim = 0, total - 1
            faixa = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if faixa and (faixa.group(1) or faixa.group(2)):
                if faixa.group(1):
                    ini = int(faixa.group(1))
                    fim = int(faixa.group(2)) if faixa.group(2) else total - 1
                else:
                    ini = max(0, total - int(faixa.group(2)))
                fim = min(fim, total - 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {ini}-{fim}/{total}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(fim - ini + 1))
            self.end_headers()
            with open(p, "rb") as f:
                f.seek(ini)
                falta = fim - ini + 1
                while falta > 0:
                    bloco = f.read(min(1 << 20, falta))
                    if not bloco:
                        break
                    self.wfile.write(bloco)
                    falta -= len(bloco)

        def log_message(self, *_):
            pass

    if trabalhador:
        fila.iniciar_trabalhador()
        print("Fila de publicação: ativa (publica nos horários agendados enquanto o painel estiver aberto)")
    print(f"Painel em http://localhost:{porta}  (Ctrl+C para parar)")
    ThreadingHTTPServer(("127.0.0.1", porta), H).serve_forever()


def principal(porta: int = 8800) -> None:
    servir(config.RAIZ / config.carregar()["pasta_dados"], porta)
