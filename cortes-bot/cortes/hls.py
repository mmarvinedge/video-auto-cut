"""Baixador HLS paralelo.

VODs da Twitch/Kick vêm em milhares de pedaços de ~10s. Cada pedaço demora ~0,8s só para
começar a chegar, então baixar em sequência leva horas; em paralelo leva ~1 minuto.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx


@dataclass
class Pedaco:
    url: str
    inicio: float
    duracao: float
    init: str | None  # URL do segmento de inicialização (fMP4), se houver


_playlists: dict[str, list["Pedaco"]] = {}


def ler_playlist(url_m3u8: str, cliente: httpx.Client, memoria: bool = False) -> list[Pedaco]:
    """`memoria=True` guarda o resultado: o manifesto de um VOD já encerrado não muda mais,
    e baixá-lo de novo a cada corte são milhares de linhas relidas à toa. Numa live em
    andamento ele mudaria, mas o bot só trabalha com VOD."""
    if memoria and (p := _playlists.get(url_m3u8)) is not None:
        return p
    r = cliente.get(url_m3u8)
    r.raise_for_status()
    pedacos, t, dur, init = [], 0.0, 0.0, None
    for linha in r.text.splitlines():
        linha = linha.strip()
        if linha.startswith("#EXT-X-MAP:"):
            uri = linha.split('URI="', 1)[1].split('"', 1)[0]
            init = urljoin(url_m3u8, uri)
        elif linha.startswith("#EXTINF:"):
            dur = float(linha[8:].split(",", 1)[0])
        elif linha and not linha.startswith("#"):
            pedacos.append(Pedaco(urljoin(url_m3u8, linha), t, dur, init))
            t += dur
    if memoria:
        _playlists[url_m3u8] = pedacos
    return pedacos


def baixar(url_m3u8: str, destino: Path, inicio: float | None = None, fim: float | None = None,
           workers: int = 32, progresso: bool = True, memoria: bool = False) -> float:
    """Baixa os pedaços que cobrem [inicio, fim] (ou tudo) e grava num único arquivo.
    Retorna o instante (s no VOD) em que o arquivo gravado começa."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True, http2=False) as cliente:
        pedacos = ler_playlist(url_m3u8, cliente, memoria)
        if inicio is not None or fim is not None:
            a, b = inicio or 0, fim if fim is not None else float("inf")
            pedacos = [p for p in pedacos if p.inicio + p.duracao > a and p.inicio < b]
        if not pedacos:
            raise ValueError("nenhum pedaço no intervalo pedido")

        def pegar(url: str) -> bytes:
            for tentativa in range(4):
                try:
                    r = cliente.get(url)
                    r.raise_for_status()
                    return r.content
                except httpx.HTTPError:
                    if tentativa == 3:
                        raise
            return b""

        total = len(pedacos)
        with ThreadPoolExecutor(workers) as pool, open(destino, "wb") as out:
            init_atual = None
            for i, dados in enumerate(pool.map(pegar, [p.url for p in pedacos])):
                p = pedacos[i]
                if p.init and p.init != init_atual:
                    out.write(pegar(p.init))
                    init_atual = p.init
                out.write(dados)
                if progresso and (i + 1) % 250 == 0:
                    print(f"  {i + 1}/{total} pedaços", flush=True)
    return pedacos[0].inicio
