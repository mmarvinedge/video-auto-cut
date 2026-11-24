"""Roda `baixar-audio` + `processar` em segundo plano, para o painel disparar com um clique.

Um trabalho por vez (os dois passos usam GPU e rede pesado; dois juntos só atrasam os dois).
O painel pergunta o estado por `/api/trabalho` e mostra as últimas linhas do log.
"""
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import config, vod

LINHAS = 400          # quanto de log guardamos na memória
_trava = threading.Lock()
_atual: dict | None = None
_log: deque[str] = deque(maxlen=LINHAS)

# cache da lista de VODs: o yt-dlp leva uns segundos por canal
_cache: dict[str, tuple[float, list[dict]]] = {}
VALIDADE = 300.0


def vods(cfg: dict, nome_canal: str, n: int = 8, atualizar: bool = False) -> list[dict]:
    agora = time.time()
    if not atualizar and (c := _cache.get(nome_canal)) and agora - c[0] < VALIDADE:
        return c[1]
    try:
        lista = vod.listar(config.canal(cfg, nome_canal), n)
    except subprocess.CalledProcessError as e:
        # sem rede, canal inexistente ou yt-dlp desatualizado: o painel mostra o recado
        raise RuntimeError((e.stderr or "").strip().splitlines()[-1] if e.stderr
                           else "o yt-dlp não conseguiu ler a página do canal.") from e
    _cache[nome_canal] = (agora, lista)
    return lista


def estado() -> dict:
    with _trava:
        a = dict(_atual) if _atual else None
        return {"atual": a, "log": list(_log)}


def _escrever(linha: str) -> None:
    with _trava:
        _log.append(linha)


def _passo(nome: str) -> None:
    with _trava:
        if _atual is not None:
            _atual["passo"] = nome
            _atual["progresso"] = None
    _escrever(f"=== {nome} ===")


def progresso(fracao: float | None) -> None:
    """Quanto do passo atual já saiu, de 0 a 1 (None = não dá para medir)."""
    with _trava:
        if _atual is not None:
            _atual["progresso"] = None if fracao is None else round(max(0.0, min(1.0, fracao)), 3)


def _rodar(argumentos: list[str]) -> list[str]:
    """Roda `python -m cortes ...` jogando a saída no log. Devolve as linhas do stdout."""
    cmd = [sys.executable, "-u", "-m", "cortes", *argumentos]
    _escrever("$ " + " ".join(argumentos))
    saida: list[str] = []
    # Sem isto, no Windows o filho escreve no pipe em cp1252: "pedaços" chegava como "peda�os", e
    # imprimir um emoji (título de live, título da IA) derrubava o processo com UnicodeEncodeError.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    p = subprocess.Popen(cmd, cwd=str(config.RAIZ), stdout=subprocess.PIPE, env=env,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    for linha in p.stdout:
        linha = linha.rstrip()
        if linha:
            saida.append(linha)
            _escrever(linha)
            # as etapas longas contam em voz alta ("1500/3135 pedaços", "corte 3/10"): vira barra
            if m := re.search(r"\b(\d+)\s*/\s*(\d+)\b", linha):
                feito, total = int(m.group(1)), int(m.group(2))
                progresso(feito / total if 0 < feito <= total else None)
    if p.wait() != 0:
        raise RuntimeError(f"`cortes {argumentos[0]}` falhou (código {p.returncode}). Veja o log.")
    return saida


def _audio_existente(cfg: dict, nome_canal: str, url: str) -> Path | None:
    """Se o áudio desse VOD já foi baixado, reaproveita em vez de baixar de novo."""
    if not (m := re.search(r"/(?:videos?|video)/(\d+)", url)):
        return None
    arq = config.pasta_canal(cfg, nome_canal) / "vods" / f"{m.group(1)}_audio.mp4"
    return arq if arq.exists() else None


def _trabalhar(nome_canal: str, url: str, titulo: str, opcoes: list[str]) -> None:
    global _atual
    try:
        cfg = config.carregar()
        if audio := _audio_existente(cfg, nome_canal, url):
            _passo("áudio já baixado")
            _escrever(str(audio))
        else:
            _passo("baixando o áudio do VOD")
            linhas = _rodar(["baixar-audio", nome_canal, url])
            caminhos = [x for x in linhas if x.endswith("_audio.mp4")]
            if not caminhos:
                raise RuntimeError("não achei o arquivo de áudio na saída do download.")
            audio = Path(caminhos[-1])
        _passo("procurando os momentos e gerando os cortes")
        _rodar(["processar", nome_canal, str(audio), *opcoes])
        _passo("pronto")
        with _trava:
            if _atual:
                _atual["fim"] = time.time()
    except Exception as e:                       # qualquer falha vira recado no painel
        _escrever(f"ERRO: {e}")
        with _trava:
            if _atual:
                _atual.update(erro=str(e), fim=time.time())
    finally:
        with _trava:
            if _atual:
                _atual["rodando"] = False


def comecar(nome_canal: str, url: str, titulo: str = "", opcoes: list[str] | None = None) -> dict:
    """Dispara o trabalho. Levanta RuntimeError se já tiver um rodando."""
    global _atual
    url = vod.limpar_url(url)   # tira o "#__youtubedl_smuggle=..." que o yt-dlp põe nas do Kick
    if not re.fullmatch(r"https://(www\.|m\.)?(twitch\.tv|kick\.com|youtube\.com|youtu\.be)/[\w./?=&-]+", url):
        raise ValueError("endereço de VOD inválido")
    permitidas = {"--sem-render", "--sem-whisper", "--sem-ia", "--sem-tiktok"}
    opcoes = [o for o in (opcoes or []) if o in permitidas]
    with _trava:
        if _atual and _atual.get("rodando"):
            raise RuntimeError(f"já estou processando {_atual['titulo'] or _atual['url']}. Espere terminar.")
        _log.clear()
        _atual = {"canal": nome_canal, "url": url, "titulo": titulo[:160], "opcoes": opcoes,
                  "passo": "começando", "rodando": True, "inicio": time.time(), "fim": None,
                  "erro": None, "progresso": None}
        atual = dict(_atual)
    threading.Thread(target=_trabalhar, args=(nome_canal, url, titulo, opcoes), daemon=True).start()
    return atual


def comecar_funcao(titulo: str, nome_canal: str, fn) -> dict:
    """Mesma vitrine do processamento, para tarefas curtas feitas aqui dentro (re-renderizar
    um corte, por exemplo). `fn` recebe a função de log e devolve uma linha de resumo."""
    global _atual
    with _trava:
        if _atual and _atual.get("rodando"):
            raise RuntimeError("já tem um trabalho rodando. Espere terminar.")
        _log.clear()
        _atual = {"canal": nome_canal, "url": "", "titulo": titulo[:160], "opcoes": [],
                  "passo": "começando", "rodando": True, "inicio": time.time(), "fim": None,
                  "erro": None, "progresso": None}
        atual = dict(_atual)

    def alvo():
        global _atual
        try:
            _passo(titulo)
            if recado := fn(_escrever):
                _escrever(recado)
            _passo("pronto")
        except Exception as e:
            _escrever(f"ERRO: {e}")
            with _trava:
                if _atual:
                    _atual["erro"] = str(e)
        finally:
            with _trava:
                if _atual:
                    _atual.update(rodando=False, fim=time.time())

    threading.Thread(target=alvo, daemon=True).start()
    return atual
