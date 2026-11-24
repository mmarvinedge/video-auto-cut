"""Baixa um vídeo do YouTube (ou só o áudio dele) para servir de filme ou de música num edit.

  python -m cortes baixar-youtube <url> [--qualidade 1080|720|480|melhor]            vídeo em mp4
  python -m cortes baixar-youtube <url> --audio [--qualidade melhor|192|128]          só o áudio, em mp3
  python -m cortes edit <url do filme> <url da música> ...   o edit baixa antes de começar

Os arquivos ficam em <pasta_dados>/edits/_youtube/, com o id do vídeo no nome (e a qualidade, se não
for a padrão): baixar de novo o mesmo endereço na mesma qualidade reaproveita o arquivo.

O YouTube passou a exigir um interpretador de JavaScript para liberar todos os formatos. Com o
Deno (ou o Node) no PATH o yt-dlp usa sozinho; sem ele o download funciona, mas pode vir numa
qualidade menor.
"""
import glob
import re
import shutil
from pathlib import Path

from . import config

URL = re.compile(r"^https://(www\.|m\.|music\.)?(youtube\.com/(watch\?|shorts/|live/)|youtu\.be/)\S+$")
VIDEO_EXT, AUDIO_EXT = "mp4", "mp3"
QUALIDADES_VIDEO = ("1080", "720", "480", "melhor")   # a primeira é a padrão
QUALIDADES_AUDIO = ("melhor", "192", "128")           # kbps do mp3; melhor = VBR máximo


def validar(url: str) -> str:
    url = (url or "").strip()
    if not URL.match(url):
        raise ValueError("cole um endereço do YouTube, ex.: https://www.youtube.com/watch?v=... ou /shorts/...")
    return url


def qualidade(q: str | None, audio: bool) -> str:
    """A qualidade pedida, validada (vazia = a padrão)."""
    opcoes = QUALIDADES_AUDIO if audio else QUALIDADES_VIDEO
    q = str(q or opcoes[0]).strip().lower().removesuffix("p").removesuffix("k")
    if q not in opcoes:
        raise ValueError(f"qualidade {'do áudio' if audio else 'do vídeo'}: use {', '.join(opcoes)}")
    return q


def _sufixo(q: str, audio: bool) -> str:
    """No nome do arquivo: a padrão não leva nada (os baixados antes continuam valendo)."""
    if q == (QUALIDADES_AUDIO if audio else QUALIDADES_VIDEO)[0]:
        return ""
    return f" [{q}]" if q == "melhor" else f" [{q}{'k' if audio else 'p'}]"


def eh_url(texto: str) -> bool:
    return bool(URL.match((texto or "").strip()))


def resolver(texto: str, audio: bool, q: str | None, cfg: dict, aviso=print) -> Path:
    """O que veio no lugar do filme ou da música: um caminho, ou um endereço do YouTube, que é
    baixado (ou reaproveitado) e vira o caminho do arquivo."""
    texto = (texto or "").strip().strip('"')
    if not eh_url(texto):
        return Path(texto)
    aviso(f"Baixando {'a música' if audio else 'o filme'} do YouTube...")
    return baixar(validar(texto), audio, pasta(cfg), aviso, q)


def pasta(cfg: dict) -> Path:
    return config.RAIZ / cfg["pasta_dados"] / "edits" / "_youtube"


def _js() -> dict:
    """Interpretadores de JavaScript disponíveis, no formato do `js_runtimes` do yt-dlp."""
    return {n: {} for n in ("deno", "node") if shutil.which(n)}


def _ja_baixado(destino: Path, ident: str, ext: str, sufixo: str = "") -> Path | None:
    return next((p for p in destino.glob("*" + glob.escape(f"[{ident}]{sufixo}.{ext}"))), None)


def baixar(url: str, audio: bool, destino: Path, aviso=print, q: str | None = None) -> Path:
    import yt_dlp

    destino.mkdir(parents=True, exist_ok=True)
    ext = AUDIO_EXT if audio else VIDEO_EXT
    q = qualidade(q, audio)
    sufixo = _sufixo(q, audio)
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
        "outtmpl": str(destino / f"%(title).80B [%(id)s]{sufixo}.%(ext)s"),
        "windowsfilenames": True, "noplaylist": True, "ffmpeg_location": config.ffmpeg(),
        "progress_hooks": [andamento], "quiet": True, "no_warnings": True, "noprogress": True,
    }
    if js := _js():
        opcoes["js_runtimes"] = js
    if audio:
        opcoes["format"] = "ba/b"
        opcoes["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_EXT,
                                     "preferredquality": "0" if q == "melhor" else q}]
    elif q == "melhor":
        # a maior resolução que houver (4K costuma ser só VP9/AV1, que não abre em todo player)
        opcoes["format"] = "bv*+ba/b"
        opcoes["format_sort"] = ["res", "acodec:aac"]
        opcoes["merge_output_format"] = VIDEO_EXT
    else:
        opcoes["format"] = f"bv*[height<={q}]+ba/b[height<={q}]/b"
        # na mesma resolução, prefere H.264 + AAC: o YouTube entrega AV1 + Opus por padrão, e
        # AV1/Opus dentro de mp4 não abre em vários players do Windows (o painel abriria, mas o
        # arquivo também vai para fora dele)
        opcoes["format_sort"] = [f"res:{q}", "vcodec:h264", "acodec:aac"]
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
        if (pronto := _ja_baixado(destino, info["id"], ext, sufixo)) is not None:
            aviso("  já estava baixado")
            return pronto
        aviso(f"Baixando o áudio ({'melhor' if q == 'melhor' else q + ' kbps'})..." if audio
              else f"Baixando o vídeo ({'melhor qualidade' if q == 'melhor' else 'até ' + q + 'p'})...")
        ydl.process_ie_result(info, download=True)

    arq = _ja_baixado(destino, info["id"], ext, sufixo)
    if arq is None:
        raise RuntimeError("o yt-dlp terminou, mas o arquivo não apareceu na pasta")
    return arq
