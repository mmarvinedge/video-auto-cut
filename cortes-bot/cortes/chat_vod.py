"""Baixa o chat de um VOD da Twitch já encerrado, no mesmo formato do chat gravado ao vivo.

O `chat-twitch` só serve para lives acontecendo agora: ele escuta o IRC. Para um VOD antigo
o chat existe como "replay", e o endereço que o próprio site da Twitch usa para pedi-lo é o
gql.twitch.tv — o mesmo caminho dos baixadores de chat conhecidos. Não é API documentada, e
pode mudar sem aviso; por isso toda falha aqui vira mensagem explicando o que não respondeu.

Cada mensagem vira uma linha JSON {"ts": epoch, "user": ..., "text": ...}, com o ts calculado
a partir do início da live mais o deslocamento da mensagem dentro do VOD — é assim que o
`detect.ler_chat` casa o chat com o áudio.
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

GQL = "https://gql.twitch.tv/gql"
# client-id público do site da Twitch (o mesmo que o navegador manda ao abrir um VOD)
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
CONSULTA = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
PAGINA = 0.0


def id_do_vod(url: str) -> str:
    """"https://www.twitch.tv/videos/2932196739" -> "2932196739"."""
    for pedaco in str(url).rstrip("/").split("/"):
        if pedaco.isdigit():
            return pedaco
    raise ValueError(f"não achei o número do VOD em “{url}”")


def _pedir(corpo: list[dict]) -> list[dict]:
    req = urllib.request.Request(GQL, json.dumps(corpo).encode(),
                                 {"Client-ID": CLIENT_ID, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"a Twitch respondeu {e.code} ao pedir o chat do VOD") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(f"não deu para falar com a Twitch: {e}") from e


def _pagina(vod: str, segundo: float) -> dict:
    """Uma página de comentários a partir de `segundo` de VOD.

    O cursor que vem em cada aresta é recusado por este endpoint, então a paginação é por tempo:
    cada página devolve ~60 mensagens e um naco delas vem de antes do ponto pedido, daí a
    deduplicação por id em `baixar`.
    """
    resp = _pedir([{"operationName": "VideoCommentsByOffsetOrCursor",
                    "variables": {"videoID": vod, "contentOffsetSeconds": int(segundo)},
                    "extensions": {"persistedQuery": {"version": 1, "sha256Hash": CONSULTA}}}])
    try:
        comentarios = resp[0]["data"]["video"]["comments"]
    except (KeyError, IndexError, TypeError):
        comentarios = None
    if not comentarios:
        erro = (resp[0].get("errors") or [{}])[0].get("message") if isinstance(resp, list) and resp else None
        raise RuntimeError(f"a Twitch não devolveu o chat desse VOD{': ' + erro if erro else ''}")
    return comentarios


def baixar(url: str, inicio: float, destino: Path, desde: float = 0.0, aviso=print) -> int:
    """Grava o chat do VOD em `destino` (.jsonl). Devolve quantas mensagens foram salvas.

    `inicio` é o epoch do começo da live (o mesmo que `vod.inicio_do_vod` lê do .info.json):
    sem ele as mensagens não teriam hora absoluta para casar com o áudio.
    """
    vod, total, segundo, vistos, avisado = id_do_vod(url), 0, desde, set(), 0.0
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        while True:
            comentarios = _pagina(vod, segundo)
            arestas = comentarios["edges"]
            if not arestas:
                break
            ultimo = arestas[-1]["node"]["contentOffsetSeconds"]
            for borda in arestas:
                no = borda["node"]
                if no["id"] in vistos:
                    continue
                vistos.add(no["id"])
                texto = "".join(p.get("text") or "" for p in no["message"]["fragments"]).strip()
                if not texto:
                    continue
                autor = (no.get("commenter") or {}).get("displayName") or "?"
                f.write(json.dumps({"ts": inicio + no["contentOffsetSeconds"], "user": autor, "text": texto},
                                   ensure_ascii=False) + "\n")
                total += 1

            if not comentarios["pageInfo"].get("hasNextPage"):
                break
            # a página termina no mesmo segundo em que começou (chat muito rápido): anda um segundo
            # para não pedir a mesma página para sempre — as repetidas já são descartadas pelos ids
            segundo = ultimo if ultimo > segundo else segundo + 1
            if segundo - avisado >= 3600:
                avisado = segundo
                aviso(f"  {segundo / 3600:.0f}h de live, {total} mensagens")
            if PAGINA:
                time.sleep(PAGINA)
    return total
