"""Transcrição com faster-whisper (GPU NVIDIA quando disponível, senão CPU).

Devolve palavras com tempo absoluto no VOD: [{"w": "Caralho,", "s": 4221.3, "e": 4221.8}, ...]
"""
import os
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

    def transcrever(self, midia: Path, inicio: float, fim: float) -> list[dict]:
        cmd = [config.ffmpeg(), "-v", "error", "-ss", f"{max(0, inicio):.2f}", "-to", f"{fim:.2f}", "-i", str(midia),
               "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
        audio = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)
        if len(audio) < 16000:
            return []
        segs, _ = self.modelo.transcribe(
            audio, language="pt", word_timestamps=True, vad_filter=True,
            condition_on_previous_text=False, beam_size=5,
        )
        base = max(0, inicio)
        return [
            {"w": w.word.strip(), "s": round(base + w.start, 2), "e": round(base + w.end, 2)}
            for s in segs for w in (s.words or []) if w.word.strip()
        ]
