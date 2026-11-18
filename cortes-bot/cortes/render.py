"""Gera o corte vertical 1080x1920 com ffmpeg.

- Com facecam configurada: facecam em cima, uma faixa preta no meio (onde entra a legenda)
  e o jogo embaixo, cortado o minimo possivel - so o bastante para nao sobrar faixa grossa
  demais e para tirar a propria facecam do quadro do jogo.
- Sem facecam: vídeo inteiro centralizado sobre um fundo desfocado do próprio vídeo.
- Crédito do streamer sempre na tela.
"""
import re
import subprocess
from pathlib import Path

from . import config

FONTE = "C\\:/Windows/Fonts/arialbd.ttf"


def _texto_ffmpeg(s: str) -> str:
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


FAIXA = 220          # altura da faixa preta entre a cam e o jogo: e nela que a legenda fica
FONTE_W, FONTE_H = 1920, 1080   # resolucao do VOD de origem
MINIMO_BYTES = 50_000  # um corte de verdade tem megabytes; abaixo disso o ffmpeg nao achou quadro


def _layout(facecam: dict, conteudo: dict | None = None) -> dict:
    """Mede o corte vertical: cam em cima na largura inteira, faixa preta no meio, jogo embaixo.

    Com `conteudo` (retangulo escolhido no `cortes enquadrar`), manda o que o usuario desenhou e
    a faixa e o que sobra. Sem ele, o jogo e cortado so o necessario para encher a altura que
    sobra da FAIXA padrao, fugindo da propria facecam para o rosto nao aparecer duas vezes."""
    h_cam = round(1080 * facecam["h"] / facecam["w"])
    h_cam += h_cam % 2                      # libx264 exige altura par
    if conteudo:
        h_jogo = round(1080 * conteudo["h"] / conteudo["w"])
        h_jogo -= h_jogo % 2
        h_jogo = min(h_jogo, 1920 - h_cam)
        return {"h_cam": h_cam, "h_jogo": h_jogo, "faixa": 1920 - h_cam - h_jogo,
                "largura": conteudo["w"], "altura": conteudo["h"],
                "x": conteudo["x"], "y": conteudo["y"]}
    h_jogo = 1920 - h_cam - FAIXA
    h_jogo -= h_jogo % 2
    largura = min(FONTE_W, round(1080 * FONTE_H / h_jogo))   # largura do recorte no video original
    # o recorte fica o mais centralizado possivel: so sai do centro o necessario para
    # nao pegar a facecam (senao o rosto aparece duas vezes e a cena fica torta)
    centro = (FONTE_W - largura) // 2
    livres = [(ini, fim) for ini, fim in
              ((0, facecam["x"]), (facecam["x"] + facecam["w"], FONTE_W)) if fim - ini >= largura]
    if livres:
        x = min((min(max(centro, ini), fim - largura) for ini, fim in livres), key=lambda v: abs(v - centro))
    else:
        x = centro                           # nao cabe fugindo da cam: centraliza no quadro todo
    return {"h_cam": h_cam, "h_jogo": h_jogo, "faixa": FAIXA,
            "largura": largura, "altura": FONTE_H, "x": x, "y": 0}


def posicao_legenda(canal: dict | None) -> int:
    """Centro vertical da legenda: no meio da faixa preta, ou no terço inferior sem facecam."""
    facecam = (canal or {}).get("facecam")
    if not facecam:
        return 1380
    L = _layout(facecam, (canal or {}).get("conteudo"))
    return L["h_cam"] + L["faixa"] // 2


def _filtro(facecam: dict | None, credito: str, legenda: str | None = None,
            conteudo: dict | None = None) -> str:
    cred = (
        f"drawtext=fontfile='{FONTE}':text='{_texto_ffmpeg(credito)}':fontsize=44:fontcolor=white:"
        "borderw=4:bordercolor=black@0.85:x=(w-text_w)/2:y=h-200"
    )
    if legenda:
        cred = f"subtitles=filename='{legenda}',{cred}"
    if facecam:
        fx, fy, fw, fh = (facecam[k] for k in ("x", "y", "w", "h"))
        L = _layout(facecam, conteudo)
        return (
            f"[0:v]split=2[a][b];"
            f"[a]crop={fw}:{fh}:{fx}:{fy},scale=1080:{L['h_cam']},"
            f"pad=1080:{L['h_cam'] + L['faixa']}:0:0:black[topo];"
            f"[b]crop={L['largura']}:{L['altura']}:{L['x']}:{L['y']},scale=1080:{L['h_jogo']}[jogo];"
            f"[topo][jogo]vstack=inputs=2,setsar=1,{cred}[v]"
        )
    return (
        f"[0:v]split=2[a][b];"
        f"[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.15[fundo];"
        f"[b]scale=1080:-2[frente];"
        f"[fundo][frente]overlay=(W-w)/2:(H-h)/2,setsar=1,{cred}[v]"
    )


def fracao_parada(video: Path, inicio: float, fim: float) -> float:
    """Fração do trecho em que a imagem fica congelada (tela de pausa, 'volto já', cena estática)."""
    cmd = [
        config.ffmpeg(), "-ss", f"{inicio:.2f}", "-to", f"{fim:.2f}", "-i", str(video),
        "-vf", "scale=320:-2,freezedetect=n=0.003:d=1", "-an", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        # sem isso, um ffmpeg quebrado nao casa com o regex e a funcao devolve 0.0:
        # o erro viraria "nao tem tela parada" e o corte ruim passaria batido
        raise RuntimeError(f"freezedetect falhou em {video.name}: {r.stderr.strip()[-300:]}")
    err = r.stderr
    parado = sum(float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", err))
    inicios = re.findall(r"freeze_start: ([0-9.]+)", err)
    if len(inicios) > err.count("freeze_end"):  # congelado até o fim do trecho
        parado += max(0.0, (fim - inicio) - float(inicios[-1]))
    return min(1.0, parado / max(fim - inicio, 1e-6))


def concatenar(partes: list[Path], saida: Path) -> Path:
    """Junta cortes verticais já renderizados (mesmo formato) num único vídeo."""
    saida = saida.resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    entradas = []
    for p in partes:
        entradas += ["-i", str(Path(p).resolve())]
    rotulos = "".join(f"[{i}:v][{i}:a]" for i in range(len(partes)))
    cmd = [
        config.ffmpeg(), "-y", "-v", "error", *entradas,
        "-filter_complex", f"{rotulos}concat=n={len(partes)}:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
        str(saida),
    ]
    subprocess.run(cmd, check=True)
    return saida


def renderizar(video: Path, inicio: float, fim: float, saida: Path, canal: dict, legenda: Path | None = None) -> Path:
    """`legenda`: arquivo .ass opcional (tempos relativos ao início do corte)."""
    saida = saida.resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    # o ffmpeg roda dentro da pasta da legenda: assim o filtro recebe só o nome do arquivo,
    # sem os ":" e "\" dos caminhos do Windows (que quebram a sintaxe dos filtros)
    pasta = legenda.resolve().parent if legenda else None
    cmd = [
        config.ffmpeg(), "-y", "-v", "error",
        "-ss", f"{inicio:.2f}", "-to", f"{fim:.2f}", "-i", str(Path(video).resolve()),
        "-filter_complex", _filtro(canal.get("facecam"), canal.get("credito", ""),
                                   legenda.name if legenda else None, canal.get("conteudo")),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(tmp := saida.with_name(saida.stem + ".tmp" + saida.suffix)),
    ]
    # Grava ao lado e só troca no fim: um re-render que dê errado não pode apagar o corte bom.
    # Um intervalo fora do arquivo de origem não é erro para o ffmpeg: ele sai com sucesso e
    # escreve um mp4 sem quadro nenhum (algumas centenas de bytes).
    try:
        subprocess.run(cmd, check=True, cwd=pasta)
        if tmp.stat().st_size < MINIMO_BYTES:
            raise RuntimeError(f"o render saiu vazio ({tmp.stat().st_size} bytes): o trecho "
                               f"{inicio:.1f}–{fim:.1f}s não está dentro de {Path(video).name}")
        tmp.replace(saida)
    finally:
        tmp.unlink(missing_ok=True)
    return saida
