"""Cenas (planos) de um filme: onde a câmera corta, uma miniatura de cada e as folhas de contato.

As folhas são grades de miniaturas numeradas, já no recorte vertical que vai para o edit: é isso
que a IA olha para escolher os planos bonitos, numa imagem só por folha em vez de uma por plano.
"""
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import config
from .render import FONTE

MINI_W, MINI_H = 192, 240     # miniatura 4:5, o mesmo recorte do edit
COLUNAS, LINHAS = 6, 5


def duracao(video: Path) -> float:
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(video)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise RuntimeError(f"não consegui ler a duração de {video.name}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def tamanho(video: Path) -> tuple[int, int]:
    r = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(video)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    if not m:
        raise RuntimeError(f"{video.name} não tem vídeo")
    return int(m.group(1)), int(m.group(2))


def tarja(video: Path, inicio: float = 0.0, fim: float | None = None, amostras: int = 12) -> tuple | None:
    """Área com imagem (sem as tarjas pretas do cinemascope): (largura, altura, x, y), ou None se
    o vídeo não tem tarja. Clipe de filme no YouTube costuma vir 2,39:1 dentro de um 16:9, e o
    recorte vertical pegava as tarjas junto.

    Mede com o `cropdetect` em alguns pontos e fica com a mediana de cada borda: uma cena escura
    sozinha parece ter tarja maior, e a tela final dos clipes (o cartão do canal, sem tarja) parece
    não ter nenhuma; a mediana ignora os dois."""
    W, H = tamanho(video)
    fim = fim if fim is not None else duracao(video)
    caixas = []
    for t in np.linspace(inicio + (fim - inicio) * 0.05, fim - (fim - inicio) * 0.05, amostras):
        r = subprocess.run([config.ffmpeg(), "-hide_banner", "-ss", f"{t:.2f}", "-i", str(video), "-an", "-sn",
                            "-vf", "cropdetect=limit=24:round=2:reset=0", "-frames:v", "8", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        achados = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        if achados:
            w, h, x, y = map(int, achados[-1])
            if w > W * 0.3 and h > H * 0.3:          # quadro todo preto dá caixa minúscula
                caixas.append((x, y, x + w, y + h))
    if not caixas:
        return None
    x1, y1, x2, y2 = (int(np.median([c[k] for c in caixas])) for k in range(4))
    if (x2 - x1) >= W * 0.98 and (y2 - y1) >= H * 0.98:
        return None
    return (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2, x1, y1


def imagem_util(video: Path, t: float, tarja_: tuple | None = None, dur: float = 0.6) -> bool:
    """Se o filme em `t` mostra alguma coisa: o clarão do estalo, uma explosão que estoura a tela
    ou um fade para o preto não servem para o primeiro plano da música. Olha 4 quadros em `dur`
    segundos: brilho médio entre 6% e 85% e algum contraste (desvio > 4%) em pelo menos metade."""
    corte = f"crop={tarja_[0]}:{tarja_[1]}:{tarja_[2]}:{tarja_[3]}," if tarja_ else ""
    r = subprocess.run([config.ffmpeg(), "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", str(video), "-an", "-sn",
                        "-vf", f"{corte}fps={4 / dur:.3f},scale=64:36,format=gray", "-frames:v", "4",
                        "-f", "rawvideo", "-"], capture_output=True)
    px = np.frombuffer(r.stdout, np.uint8).astype(np.float32) / 255
    if len(px) < 64 * 36:
        return False
    quadros = px[: len(px) // (64 * 36) * 64 * 36].reshape(-1, 64 * 36)
    bons = [(0.06 <= q.mean() <= 0.85) and q.std() > 0.04 for q in quadros]
    return sum(bons) * 2 >= len(bons)


def _escolher_cortes(tempos: np.ndarray, notas: np.ndarray, forte: float = 0.3, fraco: float = 0.1) -> list[float]:
    """Onde a câmera corta, pela nota de cena do ffmpeg (0–1, diferença para o quadro anterior).

    Nota alta (>= `forte`) é corte. Em cena escura ou de planos parecidos o corte dá nota baixa
    (0,1–0,2 em Ultimato), então também conta um pico >= `fraco` que seja o maior em 0,2 s e
    3x acima do normal daquele trecho (o 80º percentil de 1 s em volta): movimento de câmera dá
    nota alta por vários quadros seguidos, corte dá um pico isolado."""
    cortes = []
    for i, s in enumerate(notas):
        if s >= forte:
            cortes.append(float(tempos[i]))
            continue
        if s < fraco:
            continue
        perto = np.abs(tempos - tempos[i]) <= 0.2
        if s < notas[perto].max():
            continue
        volta = (np.abs(tempos - tempos[i]) <= 1.0) & ~perto
        normal = np.percentile(notas[volta], 80) if volta.any() else 0.0
        if s >= 3 * normal:
            cortes.append(float(tempos[i]))
    return cortes


def detectar(video: Path, inicio: float = 0.0, fim: float | None = None, progresso=None,
             tarja_: tuple | None = None) -> list[dict]:
    """Lista de planos [{"id", "inicio", "fim", "mov"}] em tempo absoluto do filme. `mov` é o
    movimento do plano: a nota de cena média dos quadros de dentro dele (sem as pontas), de 0
    (parado) a ~0,1 (ação rápida). Os modelos com rampa de velocidade preferem os que mexem.

    Lê a nota de cena de cada quadro (`select=gte(scene,0)` + `metadata=print`) numa cópia
    pequena da imagem, sem as tarjas (elas pesam na média e baixam a nota dos cortes), e decide
    os cortes em `_escolher_cortes`. Decodificar o filme é o que custa (minutos para um longa),
    então o resultado fica guardado por quem chama."""
    fim = fim if fim is not None else duracao(video)
    corte_tarja = f"crop={tarja_[0]}:{tarja_[1]}:{tarja_[2]}:{tarja_[3]}," if tarja_ else ""
    cmd = [config.ffmpeg(), "-hide_banner", "-nostats", "-v", "error",
           "-ss", f"{inicio:.2f}", "-to", f"{fim:.2f}", "-i", str(video), "-an", "-sn",
           "-vf", f"{corte_tarja}scale=192:-2:flags=fast_bilinear,select='gte(scene,0)',"
                  "metadata=print:key=lavfi.scene_score:file=-", "-f", "null", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    tempos, notas, t = [], [], None
    for linha in p.stdout:
        m = re.search(r"pts_time:([\d.]+)", linha)
        if m:
            t = float(m.group(1))
            if progresso and len(tempos) % 500 == 0:
                progresso(t / max(fim - inicio, 1e-6))
            continue
        m = re.search(r"scene_score=([\d.]+)", linha)
        if m and t is not None:
            tempos.append(inicio + t)
            notas.append(float(m.group(1)))
    p.wait()
    if p.returncode:
        raise RuntimeError(f"a detecção de cenas falhou em {video.name}")
    cortes = _escolher_cortes(np.array(tempos), np.array(notas)) if tempos else []
    bordas = [inicio] + [t for t in cortes if inicio + 0.2 < t < fim - 0.2] + [fim]
    pares = [(a, b) for a, b in zip(bordas, bordas[1:]) if b - a >= 0.2]   # flash de 1–5 quadros
    tempos_, notas_ = np.array(tempos), np.array(notas)

    def movimento(a: float, b: float) -> float:
        dentro = (tempos_ > a + 0.12) & (tempos_ < b - 0.12)
        return round(float(notas_[dentro].mean()), 4) if dentro.any() else 0.0
    return [{"id": i + 1, "inicio": round(a, 3), "fim": round(b, 3), "mov": movimento(a, b)}
            for i, (a, b) in enumerate(pares)]


def _recorte(largura_fonte: int, altura_fonte: int, proporcao: float, tarja_: tuple | None = None) -> str:
    """Filtro de recorte central na proporção pedida (largura/altura), sem esticar. Com `tarja_`,
    tira antes as tarjas pretas e recorta só a área com imagem."""
    antes = ""
    if tarja_:
        largura_fonte, altura_fonte, x, y = tarja_
        antes = f"crop={largura_fonte}:{altura_fonte}:{x}:{y},"
    if largura_fonte / altura_fonte > proporcao:
        return antes + f"crop=ih*{proporcao:.5f}:ih"
    return antes + f"crop=iw:iw/{proporcao:.5f}"


def miniatura(video: Path, cena: dict, destino: Path, proporcao: float = 0.8,
              fonte_wh: tuple[int, int] = (1920, 1080), tarja_: tuple | None = None) -> float:
    """Tira a miniatura do meio do plano, numerada, e devolve (brilho, textura, liso): o brilho
    médio (0–1; planos escuros demais não servem), a textura (mediana da diferença entre pixels
    vizinhos: imagem filmada tem grão, cartela gráfica dá 0) e quanto da imagem tem o mesmo tom
    (fundo liso de cartela, logo, tela de data)."""
    t = (cena["inicio"] + cena["fim"]) / 2
    rec = _recorte(*fonte_wh, proporcao, tarja_)
    rotulo = (f"drawtext=fontfile='{FONTE}':text='{cena['id']}':fontsize=30:fontcolor=white:"
              "box=1:boxcolor=black@0.75:boxborderw=6:x=8:y=8")
    cmd = [config.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
           "-filter_complex", f"[0:v]{rec},scale={MINI_W}:{MINI_H},setsar=1,split[a][b];"
                              f"[a]{rotulo}[m];[b]scale=48:60,format=gray[c]",
           "-map", "[m]", "-q:v", "4", str(destino),
           # o -frames:v vale por saída: sem repetir aqui, esta segunda decodifica o filme até o fim
           "-map", "[c]", "-frames:v", "1", "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode or not destino.exists():
        return 0.0, 0.0, 1.0
    px = np.frombuffer(r.stdout, np.uint8)
    if len(px) != 48 * 60:
        return 0.0, 0.0, 1.0
    img = px.reshape(60, 48).astype(np.float32)
    textura = float(np.median(np.abs(np.diff(img, axis=1))))
    liso = float(np.bincount((px // 8).astype(int)).max() / px.size)
    return float(px.mean() / 255), textura, liso


def miniaturas(video: Path, cenas_: list[dict], pasta: Path, proporcao: float = 0.8,
               tarja_: tuple | None = None) -> None:
    """Preenche c["mini"], c["brilho"], c["textura"] e c["liso"] nas cenas que ainda não têm
    (fica em cache na pasta; caches de antes da textura tiram a miniatura de novo, uma vez)."""
    pasta.mkdir(parents=True, exist_ok=True)
    wh = tamanho(video)
    faltam = [c for c in cenas_ if not (pasta / f"{c['id']:05d}.jpg").exists() or "textura" not in c]

    def um(c):
        arq = pasta / f"{c['id']:05d}.jpg"
        brilho, textura, liso = miniatura(video, c, arq, proporcao, wh, tarja_)
        c.update(brilho=round(brilho, 3), textura=round(textura, 2), liso=round(liso, 2),
                 mini=config.relativo(arq))

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(um, faltam))


def folhas(cenas_: list[dict], destino: Path) -> list[Path]:
    """Junta as miniaturas em grades COLUNAS x LINHAS (uma imagem por grade)."""
    destino.mkdir(parents=True, exist_ok=True)
    for velha in destino.glob("folha_*.jpg"):
        velha.unlink()
    cenas_ = [c for c in cenas_ if c.get("mini") and config.absoluto(c["mini"]).exists()]
    por_folha = COLUNAS * LINHAS
    saida = []
    for n, i in enumerate(range(0, len(cenas_), por_folha), start=1):
        grupo = cenas_[i:i + por_folha]
        lista = destino / f"folha_{n:02d}.txt"
        lista.write_text("".join(f"file '{config.absoluto(c['mini']).as_posix()}'\n" for c in grupo),
                         encoding="utf-8")
        arq = destino / f"folha_{n:02d}.jpg"
        subprocess.run([config.ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
                        # a última folha só com as linhas que tem: grade vazia é imagem paga à toa
                        "-vf", f"tile={COLUNAS}x{-(-len(grupo) // COLUNAS)}:padding=4:color=black",
                        "-frames:v", "1",
                        "-q:v", "3", str(arq)], check=True)
        lista.unlink()
        saida.append(arq)
    return saida


def eh_cartela(c: dict) -> bool:
    """Cartela de título, logo de estúdio ou de canal, tela de data de estreia, créditos: não é
    imagem do filme e não pode entrar no edit. Duas marcas, medidas num trailer real (Vingadores 5):
    - longa e congelada: 8 s ou mais quase sem movimento (a tela de data: 11 s, mov 0,0012; o logo
      do canal: 20 s, mov 0,0003). O `mov` é medido numa cópia pequena, onde o grão some: um close
      parado de verdade também dá ~0,0002, mas plano filmado de 8 s totalmente parado é raro;
    - fundo liso sem textura e parada: imagem filmada tem grão (textura >= 1); gráfico dá 0."""
    dur, mov = c["fim"] - c["inicio"], c.get("mov")
    if mov is not None and dur >= 8 and mov < 0.0015:
        return True
    return (c.get("textura") is not None and c["textura"] < 0.5 and c.get("liso", 0) >= 0.6
            and (mov is None or mov < 0.003))


def candidatas(cenas_: list[dict], dur_min: float, maximo: int, excluir: tuple[float, float] | None = None,
               brilho_min: float = 0.08) -> list[dict]:
    """Planos que servem para a parte da música: longos o bastante para o recorte, não escuros e
    que não são cartela (`eh_cartela`). Se forem muitos, pega espalhado pelo filme todo (a IA vê no
    máximo `maximo`)."""
    ok = [c for c in cenas_ if c["fim"] - c["inicio"] >= dur_min and not eh_cartela(c)
          and not (excluir and c["inicio"] < excluir[1] and c["fim"] > excluir[0])]
    if any("brilho" in c for c in ok):
        ok = [c for c in ok if c.get("brilho", 1) >= brilho_min]
    if len(ok) <= maximo:
        return ok
    idx = np.linspace(0, len(ok) - 1, maximo).round().astype(int)
    return [ok[i] for i in sorted(set(idx))]
