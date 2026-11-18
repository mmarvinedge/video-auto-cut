"""Escolhe à mão o enquadramento do corte vertical: o retângulo da câmera e o do conteúdo.

Tira alguns frames do VOD, mostra numa página local com os dois retângulos arrastáveis e uma
prévia 1080x1920 ao vivo (a faixa preta engrossa ou afina enquanto você arrasta). O resultado
vai para `dados/<canal>/enquadramento.json`, que o `config.canal()` lê por cima do config.yaml
— assim o arquivo escrito à mão, com os comentários, não é tocado.

    python -m cortes enquadrar <canal> <video.mp4>
"""
import json
import re
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import config

FRACOES = (0.25, 0.5, 0.75)   # onde tirar os frames: a cena muda ao longo da live


def intervalo(video: Path) -> tuple[float, float]:
    """(primeiro, último segundo) do arquivo, na linha do tempo DELE.

    Trechos baixados por HLS guardam o tempo do VOD de origem (começam em 9944s, por exemplo),
    e o `Duration` do ffmpeg nesses casos ja e o instante final, nao o tamanho. Procurar pelo
    meio sem considerar isso faz o ffmpeg buscar antes do começo do arquivo e falhar."""
    err = subprocess.run([config.ffmpeg(), "-i", str(video)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not m:
        raise SystemExit(f"Não consegui ler a duração de {video}")
    fim = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    ini = float(c.group(1)) if (c := re.search(r"Duration:.*?start: ([\d.]+)", err)) else 0.0
    return (ini, fim) if fim > ini else (0.0, fim)


def _tirar(video: Path, destino: Path, t: float, t_rel: float, curto: bool) -> Path | None:
    """Um frame em `t`. Tenta a busca rapida; se o arquivo nao aceitar (trechos de HLS guardam
    o tempo do VOD e tem indice quebrado), decodifica desde o inicio - so quando e curto."""
    ff = config.ffmpeg()
    tentativas = [["-ss", f"{t:.2f}", "-i", str(video)]]
    if curto:
        tentativas.append(["-i", str(video), "-ss", f"{t_rel:.2f}"])
        tentativas.append(["-i", str(video)])
    for args in tentativas:
        # PNG e nao JPEG: o encoder mjpeg recusa o YUV "non full-range" que a Twitch entrega
        subprocess.run([ff, "-y", "-v", "error", *args, "-frames:v", "1", str(destino)],
                       capture_output=True)
        if destino.exists() and destino.stat().st_size > 0:
            return destino
    return None


def frame(video: Path, destino: Path, t: float, t_rel: float = 0.0, curto: bool = True) -> Path | None:
    """Um frame avulso de `video`, para quem monta a própria lista (as amostras do VOD inteiro)."""
    return _tirar(video, destino, t, t_rel, curto)


def extrair_frames(video: Path, destino: Path) -> list[Path]:
    """Um frame por fração da duração, em 1920x1080 (o mesmo referencial dos recortes)."""
    destino.mkdir(parents=True, exist_ok=True)
    ini, fim = intervalo(video)
    curto = (fim - ini) <= 900          # decodificar do zero so vale a pena em trecho curto
    saidas = []
    for i, f in enumerate(FRACOES, 1):
        arq = destino / f"frame{i}.png"
        arq.unlink(missing_ok=True)
        if _tirar(video, arq, ini + (fim - ini) * f, (fim - ini) * f, curto):
            saidas.append(arq)
    if not saidas:
        raise SystemExit(f"Não consegui extrair nenhum frame de {video.name}.")
    return saidas


def _padrao(canal: dict) -> dict:
    """Sugestão inicial: o que já estiver configurado, senão retângulos genéricos."""
    cam = canal.get("facecam") or {"x": 1440, "y": 0, "w": 420, "h": 268}
    cont = canal.get("conteudo") or {"x": 334, "y": 0, "w": 1155, "h": 1080}
    return {"cam": cam, "conteudo": cont}


def arquivo(dados: Path, nome_canal: str, vod: str = "", corte: str = "") -> Path:
    """Onde mora cada enquadramento.

    Por corte e por VOD em `enquadramento/`, porque o streamer muda a cam de lugar entre lives
    (e às vezes no meio de uma). O do canal continua no arquivo antigo, como ponto de partida.
    """
    pasta = dados / nome_canal / "enquadramento"
    if corte:
        return pasta / f"corte_{corte.replace('/', '_')}.json"
    if vod:
        return pasta / f"{vod}.json"
    return dados / nome_canal / "enquadramento.json"


def _ler(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in d.items() if k in ("cam", "conteudo") and v}


def resolver(dados: Path, nome_canal: str, canal: dict, vod: str = "", corte: str = "") -> dict:
    """O enquadramento que vale para este corte: o dele, senão o do VOD, senão o do canal.

    O ajuste de um corte fica preso a ele de propósito: quando a cam anda no meio da live é
    exceção, e espalhar o conserto pelos vizinhos estragaria os que estavam certos.
    """
    valores = {}
    for p in (arquivo(dados, nome_canal), arquivo(dados, nome_canal, vod=vod) if vod else None,
              arquivo(dados, nome_canal, corte=corte) if corte else None):
        if p is not None:
            valores.update(_ler(p))
    return valores


def aplicar(canal: dict, dados: Path, nome_canal: str, vod: str = "", corte: str = "") -> dict:
    """Cópia do canal com o `facecam`/`conteudo` que valem aqui."""
    v = resolver(dados, nome_canal, canal, vod, corte)
    c = dict(canal)
    if v.get("cam"):
        c["facecam"] = v["cam"]
    if v.get("conteudo"):
        c["conteudo"] = v["conteudo"]
    return c


def criar(video: Path, nome_canal: str, canal: dict, dados: Path, porta: int = 8810,
          destino: Path | None = None, alvo: str = "", ao_salvar=None,
          frames: list[Path] | None = None) -> HTTPServer:
    """Monta o servidor sem subir: quem chama decide se bloqueia (CLI) ou roda numa thread (painel).

    `destino` diz de quem é o enquadramento (canal, VOD ou corte); `alvo` é o que a página escreve
    no botão, e `ao_salvar` é chamado depois de gravar — é por onde o painel recompila o corte.
    """
    pagina = Path(__file__).parent / "enquadrar.html"
    frames = frames or extrair_frames(video, dados / nome_canal / "_frames")
    destino = destino or arquivo(dados, nome_canal)
    inicial = {**_padrao(canal), **_ler(destino)}
    hosts_ok = {f"localhost:{porta}", f"127.0.0.1:{porta}"}

    class H(BaseHTTPRequestHandler):
        def _enviar(self, corpo: bytes, tipo: str, status=200):
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.headers.get("Host", "") not in hosts_ok:   # bloqueia DNS rebinding
                return self.send_error(403)
            caminho = urlparse(self.path).path
            if caminho in ("/", "/index.html"):
                self._enviar(pagina.read_bytes(), "text/html; charset=utf-8")
            elif caminho == "/estilo.css":
                self._enviar((Path(__file__).parent / "estilo.css").read_bytes(),
                             "text/css; charset=utf-8")
            elif caminho == "/api/dados":
                self._enviar(json.dumps({
                    "canal": nome_canal, "video": video.name, "alvo": alvo,
                    "frames": [f"/frame/{i}" for i in range(len(frames))], **inicial,
                }, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif caminho.startswith("/frame/"):
                try:
                    self._enviar(frames[int(caminho.rsplit("/", 1)[1])].read_bytes(), "image/png")
                except (ValueError, IndexError):
                    self.send_error(404)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.headers.get("Host", "") not in hosts_ok:
                return self.send_error(403)
            if urlparse(self.path).path != "/api/salvar":
                return self.send_error(404)
            tam = int(self.headers.get("Content-Length") or 0)
            pedido = json.loads(self.rfile.read(tam) or b"{}")
            saida = {
                "cam": {k: int(pedido["cam"][k]) for k in ("x", "y", "w", "h")},
                "conteudo": {k: int(pedido["conteudo"][k]) for k in ("x", "y", "w", "h")},
                "medido_em": video.stem,
            }
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Enquadramento salvo em {destino}")
            print(f"  cam      {saida['cam']}")
            print(f"  conteudo {saida['conteudo']}")
            resposta = {"ok": True, "destino": str(destino)}
            if ao_salvar:
                try:
                    resposta["depois"] = ao_salvar(saida)
                except (ValueError, RuntimeError, OSError) as e:
                    resposta["aviso"] = str(e)
            self._enviar(json.dumps(resposta, ensure_ascii=False).encode(),
                         "application/json; charset=utf-8")

        def log_message(self, *_):
            pass

    return HTTPServer(("127.0.0.1", porta), H)


def servir(video: Path, nome_canal: str, canal: dict, dados: Path, porta: int = 8810) -> None:
    srv = criar(video, nome_canal, canal, dados, porta)
    url = f"http://localhost:{porta}"
    print(f"Enquadramento de '{nome_canal}' em {url}  (Ctrl+C para fechar)")
    webbrowser.open(url)
    srv.serve_forever()
