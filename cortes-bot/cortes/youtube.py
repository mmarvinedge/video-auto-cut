"""Baixa um vídeo do YouTube (ou só o áudio dele) para servir de filme ou de música num edit.

  python -m cortes baixar-youtube <url>            vídeo até 1080p, em mp4
  python -m cortes baixar-youtube <url> --audio    só o áudio, em mp3

Os arquivos ficam em <pasta_dados>/edits/_youtube/, com o id do vídeo no nome: baixar de novo o
mesmo endereço reaproveita o arquivo em vez de baixar outra vez.

O YouTube passou a exigir um interpretador de JavaScript para liberar todos os formatos. Com o
Deno (ou o Node) no PATH o yt-dlp usa sozinho; sem ele o download funciona, mas pode vir numa
qualidade menor.
"""
import re
import shutil
from pathlib import Path

from . import config

URL = re.compile(r"^https://(www\.|m\.|music\.)?(youtube\.com/(watch\?|shorts/|live/)|youtu\.be/)\S+$")
VIDEO_EXT, AUDIO_EXT = "mp4", "mp3"


def validar(url: str) -> str:
    url = (url or "").strip()
    if not URL.match(url):
        raise ValueError("cole um endereço do YouTube, ex.: https://www.youtube.com/watch?v=... ou /shorts/...")
    return url


def pasta(cfg: dict) -> Path:
    return config.RAIZ / cfg["pasta_dados"] / "edits" / "_youtube"


def _js() -> dict:
    """Interpretadores de JavaScript disponíveis, no formato do `js_runtimes` do yt-dlp."""
    return {n: {} for n in ("deno", "node") if shutil.which(n)}


def _ja_baixado(destino: Path, ident: str, ext: str) -> Path | None:
    return next((p for p in destino.glob(f"*[[]{ident}[]].{ext}")), None)


def baixar(url: str, audio: bool, destino: Path, aviso=print) -> Path:
    import yt_dlp

    destino.mkdir(parents=True, exist_ok=True)
    ext = AUDIO_EXT if audio else VIDEO_EXT
    passo = {"pct": -100}

    def andamento(d: dict) -> None:
        # uma linha a cada 5%: o painel transforma "N/M" em barra, e uma linha por pedaço
        # baixado enchia o log
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = int(d.get("downloaded_bytes", 0) * 100 / total)
                if pct >= passo["pct"] + 5:
                    passo["pct"] = pct
                    aviso(f"  baixando {pct}/100%")
        elif d.get("status") == "finished":
            passo["pct"] = -100         # o vídeo e o áudio vêm separados: a contagem recomeça

    opcoes = {
        "outtmpl": str(destino / "%(title).80B [%(id)s].%(ext)s"),
        "windowsfilenames": True, "noplaylist": True, "ffmpeg_location": config.ffmpeg(),
        "progress_hooks": [andamento], "quiet": True, "no_warnings": True, "noprogress": True,
    }
    if js := _js():
        opcoes["js_runtimes"] = js
    if audio:
        opcoes["format"] = "ba/b"
        opcoes["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_EXT,
                                     "preferredquality": "0"}]
    else:
        opcoes["format"] = "bv*[height<=1080]+ba/b[height<=1080]/b"
        # na mesma resolução, prefere H.264 + AAC: o YouTube entrega AV1 + Opus por padrão, e
        # AV1/Opus dentro de mp4 não abre em vários players do Windows (o painel abriria, mas o
        # arquivo também vai para fora dele)
        opcoes["format_sort"] = ["res:1080", "vcodec:h264", "acodec:aac"]
        opcoes["merge_output_format"] = VIDEO_EXT

    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            raise ValueError("isso é uma playlist: cole o endereço de um vídeo só")
        minutos = (info.get("duration") or 0) / 60
        aviso(f"Vídeo: {info.get('title')} ({minutos:.0f} min)" if minutos >= 1
              else f"Vídeo: {info.get('title')} ({info.get('duration') or 0:.0f}s)")
        if not js:
            aviso("  (sem Deno/Node instalado o YouTube pode entregar uma qualidade menor)")
        if (pronto := _ja_baixado(destino, info["id"], ext)) is not None:
            aviso("  já estava baixado")
            return pronto
        aviso("Baixando o áudio..." if audio else "Baixando o vídeo...")
        ydl.process_ie_result(info, download=True)

    arq = _ja_baixado(destino, info["id"], ext)
    if arq is None:
        raise RuntimeError("o yt-dlp terminou, mas o arquivo não apareceu na pasta")
    return arq
