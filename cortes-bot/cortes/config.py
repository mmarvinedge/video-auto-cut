import json
import re
from pathlib import Path

import imageio_ffmpeg
import yaml

RAIZ = Path(__file__).resolve().parent.parent

PLATAFORMAS = {"twitch.tv": "twitch", "www.twitch.tv": "twitch", "kick.com": "kick", "www.kick.com": "kick"}
LOGIN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{2,30}$")


def ler_endereco(texto: str) -> tuple[str, str]:
    """"https://twitch.tv/alanzoka" -> ("twitch", "alanzoka"). Levanta ValueError se não der."""
    t = (texto or "").strip().removeprefix("http://").removeprefix("https://").strip("/")
    host, _, resto = t.partition("/")
    plataforma = PLATAFORMAS.get(host.lower())
    if not plataforma:
        raise ValueError("endereço precisa ser de twitch.tv ou kick.com, ex.: https://www.twitch.tv/alanzoka")
    login = resto.split("/")[0].split("?")[0]
    if not LOGIN.match(login):
        raise ValueError(f"não achei o nome do streamer em “{texto}”")
    return plataforma, login


def adicionar_canal(endereco: str, destino: str = "", caminho: str | Path = RAIZ / "config.yaml") -> tuple[str, dict]:
    """Acrescenta um streamer ao fim da seção `canais:` do config.yaml, preservando os comentários."""
    plataforma, login = ler_endereco(endereco)
    nome = login.lower()
    cfg = carregar(caminho)
    if nome in (cfg.get("canais") or {}):
        raise ValueError(f"{login} já está na lista de streamers")

    destino = (destino or "").strip()[:80] or f"Cortes do {login}"
    url = f"https://{'www.twitch.tv' if plataforma == 'twitch' else 'kick.com'}/{login}"
    bloco = (f"\n  {nome}:\n"
             f"    plataforma: {plataforma}\n"
             f"    login: {login}\n"
             f"    url: {url}\n"
             f"    canal_destino: {json.dumps(destino, ensure_ascii=False)}\n"
             f"    credito: {'twitch.tv' if plataforma == 'twitch' else 'kick.com'}/{login}\n"
             f"    facecam: null   # ajuste pelo botão “Ajustar enquadramento” depois de baixar um trecho\n")

    linhas = Path(caminho).read_text(encoding="utf-8").splitlines(keepends=True)
    inicio = next(i for i, l in enumerate(linhas) if l.startswith("canais:"))
    fim = next((i for i in range(inicio + 1, len(linhas)) if re.match(r"^[^\s#]", linhas[i])), len(linhas))
    while fim > inicio + 1 and not linhas[fim - 1].strip():
        fim -= 1
    Path(caminho).write_text("".join(linhas[:fim]) + bloco + "".join(linhas[fim:]), encoding="utf-8")
    return nome, canal(carregar(caminho), nome)


def carregar(caminho: str | Path = RAIZ / "config.yaml") -> dict:
    with open(caminho, encoding="utf-8") as f:
        return yaml.safe_load(f)


def canal(cfg: dict, nome: str) -> dict:
    try:
        c = dict(cfg["canais"][nome])
    except KeyError:
        raise SystemExit(f"Canal '{nome}' não está no config.yaml. Opções: {', '.join(cfg['canais'])}")
    # o enquadramento escolhido no `python -m cortes enquadrar` manda no config.yaml:
    # assim o arquivo escrito à mão, com os comentários, nunca precisa ser reescrito
    arq = RAIZ / cfg["pasta_dados"] / nome / "enquadramento.json"
    if arq.exists():
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return c
        if d.get("cam"):
            c["facecam"] = d["cam"]
        if d.get("conteudo"):
            c["conteudo"] = d["conteudo"]
    return c


def pasta_canal(cfg: dict, nome: str) -> Path:
    p = RAIZ / cfg["pasta_dados"] / nome
    for sub in ("vods", "chat", "candidatos", "cortes"):
        (p / sub).mkdir(parents=True, exist_ok=True)
    return p


def pasta_prontos(cfg: dict) -> Path | None:
    """Pasta onde o painel copia os cortes aprovados (None desliga a cópia)."""
    valor = cfg.get("pasta_prontos")
    return (RAIZ / valor).resolve() if valor else None


def relativo(p: str | Path) -> str:
    """Caminho para guardar nos .json: relativo à pasta do projeto, para sobreviver se ela mudar de lugar."""
    p = Path(p).resolve()
    try:
        return p.relative_to(RAIZ.resolve()).as_posix()
    except ValueError:
        return str(p)


def absoluto(s: str | Path) -> Path:
    """Inverso de relativo(): caminhos relativos são lidos a partir da pasta do projeto."""
    p = Path(s)
    return p if p.is_absolute() else RAIZ / p


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()
