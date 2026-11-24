"""Batidas e drop da música, só com numpy (sem librosa).

- `preparar`: converte a música para wav e, se pedido, deixa no estilo "slowed + reverb" dos edits.
- `analisar`: andamento (BPM), o tempo de cada batida e o drop (onde a música "entra" de verdade).

O rastreador de batidas é o de programação dinâmica do Ellis (2007), o mesmo que a librosa usa:
1. envelope de ataques = fluxo espectral positivo (quanto o espectro cresce de um quadro para o outro);
2. andamento = pico da autocorrelação do envelope, puxado para perto de 120 BPM;
3. batidas = o caminho que passa pelos ataques mais fortes sem fugir muito do andamento.
"""
import subprocess
from pathlib import Path

import numpy as np

from . import config

SR = 22050
HOP = 512
N_FFT = 2048
FPS = SR / HOP          # quadros do envelope por segundo (~43)
LATENCIA = (N_FFT / 2) / SR - HOP / SR / 2 + 0.027


def preparar(origem: Path, destino: Path, slowed: float = 1.0, reverb: bool = False) -> Path:
    """Grava a música em wav 44,1 kHz. `slowed` < 1 baixa velocidade e tom juntos (o "slowed"
    do TikTok é exatamente isso: tocar o disco mais devagar), e o reverb é um eco curto em camadas."""
    filtros = ["aresample=44100"]
    if slowed and abs(slowed - 1.0) > 1e-3:
        filtros += [f"asetrate={44100 * slowed:.0f}", "aresample=44100"]
    if reverb:
        filtros.append("aecho=0.8:0.85:45|83|127:0.30|0.22|0.15")
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-i", str(origem), "-vn", "-ac", "2",
                    "-af", ",".join(filtros), "-c:a", "pcm_s16le", str(destino)], check=True)
    return destino


def carregar(arq: Path, sr: int = SR) -> np.ndarray:
    cmd = [config.ffmpeg(), "-v", "error", "-i", str(arq), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)


def envelope(y: np.ndarray) -> np.ndarray:
    """Força dos ataques por quadro: soma do crescimento do log-espectro, normalizada."""
    if len(y) < N_FFT:
        return np.zeros(1)
    quadros = np.lib.stride_tricks.sliding_window_view(y, N_FFT)[::HOP] * np.hanning(N_FFT)
    mag = np.log1p(100 * np.abs(np.fft.rfft(quadros, axis=1)))
    fluxo = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    fluxo = np.concatenate([[0.0], fluxo])
    # tira a tendência lenta (crescendo, mixagem): sobram só os golpes
    media = np.convolve(fluxo, np.ones(16) / 16, mode="same")
    fluxo = np.maximum(0.0, fluxo - media)
    return fluxo / (fluxo.std() + 1e-9)


def andamento(env: np.ndarray, bpm_min: float = 60, bpm_max: float = 200, preferido: float = 120) -> float:
    """BPM pelo pico da autocorrelação, ponderado para não cair na metade/dobro sem motivo."""
    n = len(env)
    env = env - env.mean()
    ac = np.correlate(env, env, mode="full")[n - 1:]
    lags = np.arange(len(ac), dtype=float)
    ok = (lags >= FPS * 60 / bpm_max) & (lags <= FPS * 60 / bpm_min)
    if not ok.any():
        return preferido
    bpm = 60 * FPS / np.maximum(lags, 1)
    peso = np.exp(-0.5 * (np.log2(bpm / preferido) / 1.0) ** 2)
    pont = np.where(ok, ac * peso, -np.inf)
    lag = int(np.argmax(pont))
    # refina com interpolação parabólica (o lag inteiro erra alguns BPM, que somam numa música inteira)
    if 0 < lag < len(ac) - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        if den < 0:
            lag = lag + 0.5 * (a - c) / den
    return 60 * FPS / lag


def rastrear(env: np.ndarray, bpm: float, rigidez: float = 100.0) -> np.ndarray:
    """Índices (quadros) das batidas pelo caminho de maior pontuação."""
    periodo = 60 * FPS / bpm
    n = len(env)
    nota = env.astype(float).copy()
    anterior = np.full(n, -1)
    j_min, j_max = int(round(periodo / 2)), int(round(periodo * 2))
    desloc = np.arange(j_min, j_max + 1)
    custo = -rigidez * np.log(desloc / periodo) ** 2
    for i in range(j_min, n):
        cand = i - desloc
        validos = cand >= 0
        if not validos.any():
            continue
        tot = nota[cand[validos]] + custo[validos]
        k = int(np.argmax(tot))
        if tot[k] > 0:
            nota[i] += tot[k]
            anterior[i] = cand[validos][k]
    # termina na batida forte mais tarde (as últimas podem ser só cauda de reverb)
    fim_regiao = nota[max(0, n - int(2 * periodo)):]
    i = n - len(fim_regiao) + int(np.argmax(fim_regiao))
    caminho = []
    while i >= 0:
        caminho.append(i)
        i = anterior[i]
    return np.array(caminho[::-1])


def energia_por_batida(y: np.ndarray, batidas: np.ndarray) -> np.ndarray:
    """Volume (RMS) entre uma batida e a seguinte."""
    amostras = np.append((batidas * SR).astype(int), len(y))
    return np.array([np.sqrt(np.mean(y[a:b] ** 2)) if b > a else 0.0
                     for a, b in zip(amostras[:-1], amostras[1:])])


def achar_drop(energia: np.ndarray, batidas: np.ndarray, antes: float, depois: float, janela: int = 8) -> int:
    """Índice da batida em que a música mais "sobe": média das `janela` batidas seguintes menos a
    das anteriores. Só vale batida com `antes` segundos de música antes (onde o gancho toca baixinho)
    e `depois` segundos depois (a parte da música no edit)."""
    if len(batidas) == 0:
        raise ValueError("nenhuma batida")
    db = 20 * np.log10(energia + 1e-6)
    melhor, idx = -np.inf, None
    for i in range(len(batidas)):
        if batidas[i] < antes or batidas[i] + depois > batidas[-1] + 0.5:
            continue
        frente = db[i:i + janela]
        tras = db[max(0, i - janela):i]
        if len(frente) < 2:
            continue
        subida = frente.mean() - (tras.mean() if len(tras) else frente.mean() - 6)
        # empate: prefere o começo de compasso (múltiplo de 4 batidas a partir do drop vale menos
        # que acertar a subida; aqui só desempata) e o trecho mais alto
        pont = subida + 0.15 * frente.mean() / 10
        if pont > melhor:
            melhor, idx = pont, i
    if idx is None:   # música curta demais para as restrições: pega o trecho mais alto que couber
        idx = int(np.argmax([energia[i:i + janela].mean() for i in range(len(batidas))]))
    return idx


def analisar(wav: Path) -> dict:
    y = carregar(wav)
    env = envelope(y)
    bpm = andamento(env)
    quadros = rastrear(env, bpm)
    batidas = quadros / FPS
    # o quadro i do fluxo começa no ataque menos ~meia janela; a constante foi medida em cliques
    # e bumbos sintéticos (erro de -27 ms com só a meia janela, igual nos dois)
    batidas = np.round(batidas + LATENCIA, 3)
    batidas = batidas[(batidas >= 0) & (batidas <= len(y) / SR)]
    return {"bpm": round(float(bpm), 1), "duracao": round(len(y) / SR, 2),
            "batidas": batidas.tolist(), "energia": energia_por_batida(y, batidas).round(5).tolist()}


def cortes_na_batida(batidas: list[float], drop: float, duracao: float, corte_min: float,
                     corte_max: float) -> list[float]:
    """Pontos de corte a partir do drop, a cada k batidas, com k escolhido para cada plano durar
    entre corte_min e corte_max. Devolve os tempos na música, do drop até o fim da parte musical."""
    b = np.array([t for t in batidas if t >= drop - 1e-3])
    if len(b) < 2:
        return [drop, drop + duracao]
    periodo = float(np.median(np.diff(b)))
    alvo = (corte_min + corte_max) / 2
    k = min((1, 2, 4, 8), key=lambda k: (not corte_min <= k * periodo <= corte_max, abs(k * periodo - alvo)))
    pontos = list(b[::k])
    while pontos[-1] < drop + duracao - 1e-3:     # a música acabou antes: segue no mesmo passo
        pontos.append(pontos[-1] + k * periodo)
    # fecha no ponto mais perto da duração pedida, nunca cortando uma batida no meio
    fim = min(range(1, len(pontos)), key=lambda i: abs(pontos[i] - drop - duracao))
    return [round(float(p), 3) for p in pontos[:fim + 1]]
