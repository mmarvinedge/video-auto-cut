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


GRAVE = (30, 130)       # Hz: baixo e bumbo. O drop é o grave voltando; o volume total quase não muda
DROP_FORTE = 0.7        # uma volta de grave com 70% da maior já conta: vale a primeira
DROP_CLARO_DB = 6.0     # o grave sobe menos que isso: a música não tem drop audível


def grave_por_batida(y: np.ndarray, batidas: np.ndarray) -> np.ndarray:
    """Energia do grave (GRAVE, em Hz) entre uma batida e a seguinte."""
    amostras = np.append((np.asarray(batidas) * SR).astype(int), len(y))
    saida = []
    for a, b in zip(amostras[:-1], amostras[1:]):
        trecho = y[a:b]
        if len(trecho) < 64:
            saida.append(0.0)
            continue
        esp = np.abs(np.fft.rfft(trecho * np.hanning(len(trecho)))) ** 2
        f = np.fft.rfftfreq(len(trecho), 1 / SR)
        saida.append(float(np.sqrt(esp[(f >= GRAVE[0]) & (f < GRAVE[1])].sum() / len(trecho))))
    return np.array(saida)


def subida_db(energia: np.ndarray, i: int, janela: int = 8) -> float:
    """Quantos dB a música sobe na batida i: média das `janela` seguintes menos a das anteriores."""
    db = 20 * np.log10(np.asarray(energia) + 1e-6)
    frente, tras = db[i:i + janela], db[max(0, i - janela):i]
    if len(frente) < 2:
        return 0.0
    return float(frente.mean() - (tras.mean() if len(tras) else frente.mean() - 6))


def achar_drop(energia: np.ndarray, batidas: np.ndarray, antes: float, depois: float, janela: int = 8) -> int:
    """Índice da batida do drop. `energia`: por batida, de preferência a do grave (`grave_por_batida`):
    música masterizada hoje tem o volume total quase constante, e o drop é o baixo e o bumbo voltando
    (num Skrillex o grave salta 30 dB no drop e o volume total, 5). Só vale batida com `antes`
    segundos de música antes (onde o gancho toca) e `depois` segundos depois.

    1. A subida em cada batida: média das `janela` seguintes menos a das anteriores, em dB.
    2. Vale a PRIMEIRA volta forte (pelo menos DROP_FORTE da maior): refrão e drop se repetem, e
       antes valia a maior por décimos de dB (numa mixagem de 5 min o drop caiu aos 4 min).
    3. Perto dessa região (as batidas seguidas acima do limite, 3 antes e 8 depois), a primeira
       batida em que o grave já está no nível cheio de depois e fica nele: nas 4 batidas dali, a
       mediana a até 6 dB e nenhuma a mais de 12 dB abaixo da mediana das 16 batidas seguintes à
       região (o grave do funk oscila de uma batida para outra). A subida média cresce umas batidas
       antes do salto, uma pancada solta de grave (preenchimento) também sobe, e o grave pode voltar
       em dois degraus: no funk medido, ele volta pela metade aos 56,8 s, dá uma pancada aos 59,95 s
       e só fica cheio aos 61,2 s, que é o drop que se ouve."""
    if len(batidas) == 0:
        raise ValueError("nenhuma batida")
    db = 20 * np.log10(np.asarray(energia) + 1e-6)
    validas = [i for i in range(len(batidas))
               if batidas[i] >= antes and batidas[i] + depois <= batidas[-1] + 0.5 and len(db[i:i + janela]) >= 2]
    if not validas:   # música curta demais para as restrições: pega o trecho mais alto que couber
        return int(np.argmax([np.mean(energia[i:i + janela]) for i in range(len(batidas))]))
    sub = {i: subida_db(energia, i, janela) + 0.15 * db[i:i + janela].mean() / 10 for i in validas}
    maior = max(sub.values())
    if maior <= 0:
        return max(sub, key=sub.get)
    limite = DROP_FORTE * maior
    primeira = min(i for i in validas if sub[i] >= limite)
    regiao = [primeira]
    while regiao[-1] + 1 in sub and sub[regiao[-1] + 1] >= limite:
        regiao.append(regiao[-1] + 1)
    perto = [i for i in range(regiao[0] - 3, regiao[-1] + 9) if i in sub]
    cheio = float(np.median(db[regiao[-1]:regiao[-1] + 16]))
    for i in perto:
        q = db[i:i + 4]
        if len(q) == 4 and np.median(q) >= cheio - 6 and q.min() >= cheio - 12:
            return i
    return max(regiao, key=sub.get)


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
            "batidas": batidas.tolist(), "energia": energia_por_batida(y, batidas).round(5).tolist(),
            "grave": grave_por_batida(y, batidas).round(6).tolist()}


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
