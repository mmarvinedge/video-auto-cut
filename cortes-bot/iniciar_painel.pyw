"""Sobe o painel sem janela nenhuma: é o que o Windows roda ao iniciar a sessão.

O que o terminal mostraria vai para dados/painel.log.

Por que não só `pythonw -m cortes painel`: sem console, cada ffmpeg ou yt-dlp que o painel chama
abriria uma janela preta piscando na tela. Aqui todo subprocesso nasce com CREATE_NO_WINDOW, e os
`python -m cortes ...` dos trabalhos (processar uma live) rodam no python.exe com o console
escondido, que os filhos dele herdam.

Instalar ou tirar da inicialização do Windows:  python iniciar_painel.pyw --instalar | --remover
Depois de um `git pull` (o painel escondido continua com o código velho):  --reiniciar
Só desligar:  --parar
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ATALHO = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/Painel de cortes.lnk"
LOG = RAIZ / "dados" / "painel.log"


def instalar() -> None:
    """Atalho na pasta Inicializar do usuário: aparece (e pode ser desligado) em
    Configurações > Aplicativos > Inicialização, sem precisar de administrador."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{ATALHO}'); "
          f"$s.TargetPath = '{pythonw}'; $s.Arguments = '\"{Path(__file__).resolve()}\"'; "
          f"$s.WorkingDirectory = '{RAIZ}'; $s.Description = 'Painel de cortes (localhost:8800)'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print(f"Pronto: o painel sobe sozinho ao entrar no Windows.\nAtalho: {ATALHO}\nLog: {LOG}")


def parar() -> int:
    """Encerra o painel escondido (o que este arquivo subiu). Devolve quantos processos parou."""
    ps = ("$p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
          "Where-Object { $_.CommandLine -like '*iniciar_painel.pyw*' -and $_.ProcessId -ne " + str(os.getpid()) + " }; "
          "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
          "@($p).Count")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return int((r.stdout.strip() or "0").splitlines()[-1])


def reiniciar() -> None:
    n = parar()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pythonw), str(Path(__file__).resolve())], cwd=RAIZ, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    print(f"Painel reiniciado ({n} processo(s) antigo(s) encerrado(s)). Em instantes: http://localhost:8800")


def subir() -> None:
    os.chdir(RAIZ)
    sys.path.insert(0, str(RAIZ))
    LOG.parent.mkdir(exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 5_000_000:   # não cresce para sempre
        LOG.replace(LOG.with_suffix(".log.1"))
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} painel subindo sem janela =====")

    if os.name == "nt":
        console = Path(sys.executable).with_name("python.exe")
        if console.exists():
            sys.executable = str(console)   # os trabalhos (`python -m cortes ...`) usam este
        popen_original = subprocess.Popen.__init__

        def sem_janela(self, *a, creationflags=0, **k):
            popen_original(self, *a, creationflags=creationflags | subprocess.CREATE_NO_WINDOW, **k)

        subprocess.Popen.__init__ = sem_janela

    from cortes.__main__ import main
    sys.argv = ["cortes", "painel"]
    main()


if __name__ == "__main__":
    if "--instalar" in sys.argv:
        instalar()
    elif "--remover" in sys.argv:
        ATALHO.unlink(missing_ok=True)
        print("Removido da inicialização do Windows (o painel que já está aberto continua; use --parar).")
    elif "--parar" in sys.argv:
        print(f"{parar()} processo(s) do painel encerrado(s).")
    elif "--reiniciar" in sys.argv:
        reiniciar()
    else:
        subir()
