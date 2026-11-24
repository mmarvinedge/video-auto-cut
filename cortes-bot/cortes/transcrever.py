"""Transcrição com faster-whisper (GPU NVIDIA quando disponível, senão CPU).

Devolve palavras com tempo absoluto no VOD: [{"w": "Caralho,", "s": 4221.3, "e": 4221.8}, ...]
"""
import os
import re
import site
import subprocess
from pathlib import Path

import numpy as np

from . import config

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# O hf_xet (downloader novo do Hugging Face) exige instruções de CPU que nem todo processador tem:
# num Ryzen 3 3300X o processo morre com "Fatal Error: HW capability found ..." só de importá-lo.
# O download por HTTP comum funciona em qualquer máquina; quem quiser o xet define a variável como 0.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# Frases que o Whisper inventa em silêncio ou em música (vêm das legendas de vídeos da internet).
FANTASMAS = ("thank you", "thanks for watching", "thank you for watching", "please subscribe", "subscribe",
             "obrigado", "obrigada", "inscreva-se", "inscreva-se no canal",
             "اشتركوا في القناة", "you", "bye")


def _inventado(seg) -> bool:
    """Segmento que o Whisper tirou do nada: sem o filtro de voz (VAD) ele "ouve" frases na trilha
    sonora. As regras são as do próprio Whisper (pouca chance de ser fala e pouca confiança;
    texto repetitivo), mais as frases fantasmas conhecidas e as descrições de som ("BIRDS CHILDREN",
    "[Música]", "♪")."""
    bruto = seg.text.strip()
    texto = re.sub(r"[^\w\s'-]", "", bruto).strip().lower()
    if not texto or re.match(r"^[\[(♪*]", bruto):
        return True
    if seg.compression_ratio > 2.4 or (seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0):
        return True
    if texto in FANTASMAS or "amara.org" in bruto.lower():
        return True
    letras = re.sub(r"[^A-Za-z]", "", bruto)
    return len(letras) > 4 and letras.isupper()      # legenda de som, em maiúsculas


def _dlls_cuda() -> None:
    """No Windows, as DLLs do CUDA instaladas via pip (nvidia-cublas/cudnn) precisam ser registradas."""
    for sp in site.getsitepackages():
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
            p = os.path.join(sp, sub)
            if os.path.isdir(p):
                os.add_dll_directory(p)
                os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]


class Transcritor:
    def __init__(self, modelo: str = "large-v3-turbo", dispositivo: str = "auto"):
        _dlls_cuda()
        import ctranslate2
        from faster_whisper import WhisperModel

        if dispositivo == "auto":
            dispositivo = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        tipo = "float16" if dispositivo == "cuda" else "int8"
        self.dispositivo = dispositivo
        self.modelo = WhisperModel(modelo, device=dispositivo, compute_type=tipo)

    def transcrever(self, midia: Path, inicio: float, fim: float, idioma: str | None = "pt",
                    vad: bool = True) -> list[dict]:
        """`idioma`: código do Whisper ("pt", "en", "es"...) ou None/"auto" para ele detectar
        (pelos primeiros 30 s de cada chamada).

        `vad=False` para filme: o filtro de voz (Silero) não reconhece diálogo misturado com
        trilha e efeitos (no "I am Iron Man" de Ultimato ele não achou nada, nem no limiar 0,05).
        Sem ele o Whisper ouve tudo, e os segmentos inventados saem por `_inventado`."""
        cmd = [config.ffmpeg(), "-v", "error", "-ss", f"{max(0, inicio):.2f}", "-to", f"{fim:.2f}", "-i", str(midia),
               "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
        audio = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)
        if len(audio) < 16000:
            return []
        extra = {} if vad else {"hallucination_silence_threshold": 2.0}
        segs, _ = self.modelo.transcribe(
            audio, language=None if idioma in (None, "", "auto") else idioma, word_timestamps=True, vad_filter=vad,
            condition_on_previous_text=False, beam_size=5, **extra,
        )
        base = max(0, inicio)
        return [
            {"w": w.word.strip(), "s": round(base + w.start, 2), "e": round(base + w.end, 2)}
            for s in segs if vad or not _inventado(s) for w in (s.words or []) if w.word.strip()
        ]
