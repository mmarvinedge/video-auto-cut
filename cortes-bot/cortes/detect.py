"""Detecta momentos fortes de um VOD combinando picos de chat e de áudio.

Cada sinal vira uma série por segundo, normalizada contra o "normal" daquele trecho da live
(mediana móvel + desvio robusto). Assim uma live calma e uma live caótica usam a mesma régua.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import config

TAXA_AUDIO = 8000


def _soma_movel(x: np.ndarray, janela: int) -> np.ndarray:
    return np.convolve(x, np.ones(janela), mode="same")


def _normalizar(x: np.ndarray, baseline: int) -> np.ndarray:
    """z-score robusto em relação à mediana móvel dos últimos/próximos `baseline` segundos."""
    if len(x) == 0:
        return x
    b = min(baseline, len(x))
    if b % 2 == 0:
        b -= 1
    b = max(b, 1)
    pad = np.pad(x, (b // 2, b // 2), mode="edge")
    janelas = np.lib.stride_tricks.sliding_window_view(pad, b)
    passo = 5  # mediana a cada 5s e interpola: rápido mesmo em lives de 8h
    idx = np.arange(0, len(x), passo)
    med = np.median(janelas[idx], axis=1)
    mad = np.median(np.abs(janelas[idx] - med[:, None]), axis=1)
    med = np.interp(np.arange(len(x)), idx, med)
    mad = np.interp(np.arange(len(x)), idx, mad)
    escala = np.maximum(mad * 1.4826, np.percentile(np.abs(x - med), 75) + 1e-6)
    return (x - med) / escala


def serie_chat(mensagens: list[dict], inicio_vod: float, duracao: int, cfg_det: dict) -> np.ndarray:
    pesos = np.zeros(duracao)
    palavras = [p.lower() for p in cfg_det.get("palavras_reacao", [])]
    risada = re.compile(cfg_det.get("regex_risada", r"k{4,}"), re.I)
    atraso = cfg_det.get("atraso_chat", 0)
    for m in mensagens:
        t = int(m["ts"] - inicio_vod - atraso)
        if 0 <= t < duracao:
            texto = m.get("text", "").lower()
            reacao = risada.search(texto) or any(p in texto.split() or p == texto.strip() for p in palavras)
            pesos[t] += 1.75 if reacao else 1.0
    return _soma_movel(pesos, cfg_det["janela"])


BLOCO_S = 600   # quantos segundos de áudio ficam na memória de uma vez


def serie_audio(video: Path, janela: int) -> np.ndarray:
    """Energia (dB RMS) por segundo do áudio, decodificado em mono 8 kHz pelo ffmpeg.

    Lê a saída do ffmpeg em blocos de BLOCO_S segundos em vez de guardar a live inteira:
    uma live de 7h são 201 milhões de amostras, e entre o int16 cru, o float32 e o quadrado
    o pico passava de 1,8 GB. Em blocos, o custo não depende mais do tamanho da live."""
    cmd = [config.ffmpeg(), "-v", "error", "-i", str(video), "-vn", "-ac", "1",
           "-ar", str(TAXA_AUDIO), "-f", "s16le", "-"]
    tamanho = BLOCO_S * TAXA_AUDIO * 2          # s16 = 2 bytes por amostra
    rms, resto = [], b""
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
        while True:
            bloco = p.stdout.read(tamanho)
            if not bloco:
                break
            bloco = resto + bloco
            inteiros = len(bloco) // (TAXA_AUDIO * 2)
            resto = bloco[inteiros * TAXA_AUDIO * 2:]       # sobra do segundo incompleto
            if not inteiros:
                continue
            a = np.frombuffer(bloco, dtype=np.int16, count=inteiros * TAXA_AUDIO)
            a = a.astype(np.float32).reshape(inteiros, TAXA_AUDIO) / 32768
            rms.append(np.sqrt(np.einsum("ij,ij->i", a, a) / TAXA_AUDIO))
        erro = p.stderr.read().decode("utf-8", "replace")
    if p.returncode:
        raise RuntimeError(f"o ffmpeg não conseguiu ler o áudio de {video.name}: {erro.strip()[-300:]}")
    if not rms:
        raise RuntimeError(f"{video.name} não tem áudio legível")
    db = 20 * np.log10(np.concatenate(rms) + 1e-6)
    return _soma_movel(db, janela) / janela


def ler_chat(arquivos: list[Path], inicio: float, fim: float) -> list[dict]:
    msgs = []
    for arq in arquivos:
        with open(arq, encoding="utf-8") as f:
            for linha in f:
                try:
                    m = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if inicio <= m.get("ts", 0) <= fim:
                    msgs.append(m)
    return msgs


def candidatos(nota: np.ndarray, cfg: dict, limite: int | None = None) -> list[dict]:
    """Escolhe os picos (sem sobreposição) e define início/fim de cada corte."""
    c = cfg["corte"]
    minimo = cfg["deteccao"]["nota_minima"]
    janela = cfg["deteccao"]["janela"]
    limite = limite or c["max_cortes_por_vod"]
    usado = np.zeros(len(nota), dtype=bool)
    saida = []
    for pico in np.argsort(nota)[::-1]:
        if nota[pico] < minimo or len(saida) >= limite:
            break
        if usado[pico]:
            continue
        # estende para trás/frente enquanto a nota continuar alta (metade do pico)
        ini, fim = pico, pico
        limiar = nota[pico] / 2
        while ini > 0 and nota[ini - 1] > limiar and pico - ini < c["duracao_max"]:
            ini -= 1
        while fim < len(nota) - 1 and nota[fim + 1] > limiar and fim - pico < c["duracao_max"]:
            fim += 1
        ini = ini - janela // 2 - c["margem_antes"]
        fim = fim + c["margem_depois"]
        if fim - ini < c["duracao_min"]:
            falta = c["duracao_min"] - (fim - ini)
            ini -= falta // 2
            fim += falta - falta // 2
        if fim - ini > c["duracao_max"]:
            ini = max(ini, pico - int(c["duracao_max"] * 0.7))
            fim = ini + c["duracao_max"]
        ini, fim = max(0, int(ini)), min(len(nota), int(fim))
        if usado[ini:fim].any():
            continue
        usado[max(0, ini - 15): fim + 15] = True
        saida.append({"inicio": ini, "fim": fim, "pico": int(pico), "nota": round(float(nota[pico]), 2)})
    return sorted(saida, key=lambda x: x["nota"], reverse=True)


def candidatos_longos(nota: np.ndarray, cfg: dict) -> list[dict]:
    """Trechos de ~90s com atividade SUSTENTADA (média alta), para o formato TikTok (>60s).
    Diferente dos curtos, que procuram picos: aqui um pico isolado no meio de silêncio não basta."""
    t = cfg["tiktok"]
    janela = int(t["janela_longa"])
    if len(nota) < t["duracao_min"]:
        return []
    media = np.convolve(np.clip(nota, -1, None), np.ones(janela) / janela, mode="same")
    usado = np.zeros(len(nota), dtype=bool)
    saida = []
    for centro in np.argsort(media)[::-1]:
        if media[centro] < t["nota_minima_longo"] or len(saida) >= t["candidatos_longos"]:
            break
        ini = int(max(0, min(centro - janela // 2, len(nota) - janela)))
        fim = int(min(len(nota), ini + janela))
        if usado[ini:fim].any():
            continue
        usado[ini:fim] = True
        saida.append({"inicio": ini, "fim": fim, "pico": int(centro), "nota": round(float(media[centro]), 2)})
    return saida


def serie_nota(video: Path, mensagens: list[dict] | None, inicio_vod: float | None, cfg: dict) -> tuple[np.ndarray, dict]:
    """Nota combinada (áudio + chat) por segundo do VOD."""
    d = cfg["deteccao"]
    audio = serie_audio(video, d["janela"])
    duracao = len(audio)
    sinais, pesos = [_normalizar(audio, d["baseline"])], [d["peso_audio"]]
    # só usa o chat se ele cobre de fato este VOD (>= 1 msg/min em média dentro da live);
    # senão um chat vazio ficaria com o maior peso e achataria as notas do áudio
    dentro = [m for m in (mensagens or []) if inicio_vod is not None and 0 <= m["ts"] - inicio_vod < duracao]
    mensagens = dentro
    usou_chat = len(dentro) >= max(30, duracao / 60)
    if usou_chat:
        chat = serie_chat(mensagens, inicio_vod, duracao, d)
        sinais.append(_normalizar(chat, d["baseline"]))
        pesos.append(d["peso_chat"])
    pesos = np.array(pesos) / sum(pesos)
    nota = sum(p * np.clip(s, -3, 10) for p, s in zip(pesos, sinais))
    info = {"duracao": duracao, "usou_chat": usou_chat, "mensagens": len(mensagens or [])}
    return nota, info


def detectar(video: Path, mensagens: list[dict] | None, inicio_vod: float | None, cfg: dict,
             limite: int | None = None) -> tuple[list[dict], dict]:
    nota, info = serie_nota(video, mensagens, inicio_vod, cfg)
    return candidatos(nota, cfg, limite), info
