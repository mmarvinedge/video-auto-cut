"""Lista e baixa VODs com yt-dlp (Twitch e Kick)."""
import json
import subprocess
import sys
from pathlib import Path

from . import config, hls


def _url_videos(canal: dict) -> str:
    if canal["plataforma"] == "twitch":
        return f"https://www.twitch.tv/{canal['login']}/videos?filter=archives&sort=time"
    return f"https://kick.com/{canal['login']}/videos"


def listar(canal: dict, n: int = 5) -> list[dict]:
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-items", f"1:{n}", "-J", _url_videos(canal)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    # No Kick o yt-dlp devolve a url com um "#__youtubedl_smuggle=..." (dado interno dele, que só
    # repete a disponibilidade). Ele baixa igual sem isso, e com isso a url não passa na validação
    # do painel: todo VOD do Kick era recusado como "endereço inválido".
    return [{"id": e.get("id"), "titulo": e.get("title"), "duracao": e.get("duration"),
             "url": limpar_url(e.get("url") or "")} for e in json.loads(out).get("entries", [])]


def limpar_url(url: str) -> str:
    return url.split("#", 1)[0]


def baixar(url: str, pasta: Path, altura_max: int = 1080) -> Path:
    """Baixa o VOD + .info.json (o info traz o horário de início, usado para alinhar o chat)."""
    modelo = str(pasta / "%(id)s.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp", url,
        "-f", f"bv*[height<={altura_max}]+ba/b[height<={altura_max}]/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", config.ffmpeg(),
        "--write-info-json", "--no-part",
        "-o", modelo, "--print", "after_move:filepath",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip().splitlines()
    return Path(out[-1])


_infos: dict[tuple[str, str], dict] = {}


def _info(url: str, formato: str) -> dict:
    """Dados do VOD no formato pedido, guardados por (url, formato).

    Resolver isso é um `yt-dlp -J` inteiro, uns segundos. Como o `baixar_trecho` é chamado
    uma vez por corte, sem a memória uma live de 10 cortes pagava 10 vezes pelo mesmo dado."""
    if (d := _infos.get((url, formato))) is not None:
        return d
    cmd = [sys.executable, "-m", "yt_dlp", url, "-f", formato, "-J"]
    d = json.loads(subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    _infos[(url, formato)] = d
    return d


def informacoes(url: str, altura_max: int = 1080) -> dict:
    """{"id", "duracao"} do VOD, da mesma memória que o `baixar_trecho` usa."""
    d = _info(url, f"b[height<={altura_max}]/b")
    return {"id": d.get("id") or "", "duracao": float(d.get("duration") or 0.0)}


def baixar_audio(url: str, pasta: Path) -> Path:
    """Baixa só o áudio do VOD (~15x menor que 720p) em paralelo. Basta para a detecção."""
    info = _info(url, "Audio_Only/ba/worst")
    destino = pasta / f"{info['id']}_audio.mp4"
    destino.with_suffix(".info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    hls.baixar(info["url"], destino)
    return destino


def baixar_trecho(url: str, inicio: float, fim: float, destino: Path, altura_max: int = 1080) -> float:
    """Baixa só os pedaços de vídeo que cobrem [inicio, fim].
    Retorna em que segundo do VOD o arquivo baixado começa (para o corte acertar o tempo)."""
    info = _info(url, f"b[height<={altura_max}]/b")
    return hls.baixar(info["url"], destino, inicio, fim, progresso=False, memoria=True)


def inicio_do_trecho(url: str, inicio: float, fim: float, altura_max: int = 1080) -> float:
    """Em que segundo do VOD começa o arquivo que o `baixar_trecho` gravou para [inicio, fim],
    sem baixar nada de novo: é o início do primeiro pedaço do HLS que cobre o intervalo.

    O próprio arquivo não diz isso: o "start" que o ffmpeg lê é o relógio do stream da Twitch,
    que anda à frente do tempo do VOD (no bisteconee, ~61 s)."""
    import httpx

    info = _info(url, f"b[height<={altura_max}]/b")
    with httpx.Client(timeout=30, follow_redirects=True) as cliente:
        pedacos = hls.ler_playlist(info["url"], cliente, memoria=True)
    cobrem = [p for p in pedacos if p.inicio + p.duracao > inicio and p.inicio < fim]
    if not cobrem:
        raise ValueError("o VOD não tem pedaços nesse intervalo")
    return cobrem[0].inicio


def inicio_do_vod(video: Path) -> float | None:
    """Epoch (UTC) do início da live, lido do .info.json do yt-dlp."""
    info = video.with_suffix(".info.json")
    if not info.exists():
        return None
    d = json.loads(info.read_text(encoding="utf-8"))
    return d.get("timestamp") or d.get("release_timestamp")


def url_do_vod(video: Path) -> str | None:
    info = video.with_suffix(".info.json")
    if not info.exists():
        return None
    d = json.loads(info.read_text(encoding="utf-8"))
    return d.get("webpage_url")
