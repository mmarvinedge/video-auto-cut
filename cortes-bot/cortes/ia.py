"""Avaliação dos candidatos por IA (Claude), em duas versões:

- curtos (20–60s, Shorts/Reels): aprova/reprova, apara as bordas e escreve título/descrição/hashtags;
- TikTok (>60s, exigência da monetização): avalia os trechos longos do mesmo jeito e monta
  compilações de 2–4 cortes curtos do mesmo tema.

Uma única chamada por live com TODOS os candidatos, para a IA comparar os momentos entre si.
Credenciais: variável de ambiente ANTHROPIC_API_KEY (ou `ant auth login`).
Sem credencial, o bot segue sem esta etapa.
"""
import os

from pydantic import BaseModel, Field

MODELO = "claude-opus-5-5"

SISTEMA = """Você é editor de um canal de cortes que publica no YouTube Shorts, Instagram Reels e TikTok.
O canal é dedicado a um único streamer brasileiro e publica trechos verticais das lives dele.

Você recebe momentos candidatos de uma mesma live, cada um com a transcrição (tempos relativos ao
início do trecho) e notas automáticas de áudio/chat/fala. Há dois tipos:

- candidatos CURTOS (id "c…"): para Shorts/Reels, devem ficar entre {curto_min} e {curto_max} segundos;
- candidatos LONGOS (id "l…"): para o TikTok, que só monetiza vídeos com mais de 1 minuto;
  devem ficar entre {longo_min} e {longo_max} segundos.

Para CADA candidato, decida:
- aprovar: true só se o trecho funciona SOZINHO para quem nunca viu a live: reação forte, fala
  engraçada, bug bizarro, jogada marcante ou uma história com começo e fim. Para os longos, exija
  que o trecho prenda do começo ao fim (uma perseguição, uma sequência de azar, uma conversa engraçada
  que se desenvolve); um longo com um único momento bom e o resto morto deve ser reprovado.
  Reprove: pedidos de like/inscrição, leitura de doações, conversa morta, tela de pausa com música
  (letra de música na transcrição), trechos que só fazem sentido com contexto que o corte não mostra.
- nota: 0 a 10, comparando os candidatos do mesmo tipo entre si.
- aparar_inicio / aparar_fim: segundos a remover do começo/fim para cortar enrolação (0 se estiver bom),
  respeitando a duração mínima do tipo.
- titulo: em português do Brasil, até 70 caracteres, chamativo mas fiel ao que acontece (sem mentir,
  sem clickbait enganoso), no tom dos títulos de cortes brasileiros. Não use o nome do canal.
- descricao: 1 ou 2 frases contando o contexto.
- hashtags: 3 a 5, sem o símbolo #, minúsculas, sem espaço.
- motivo: uma frase explicando a decisão (útil para o editor humano revisar).

Depois, monte até {max_comp} COMPILAÇÕES para o TikTok usando só candidatos CURTOS que você aprovou:
cada uma com 2 a 4 cortes que combinem entre si (mesmo tema, mesma situação ou uma progressão,
ex.: "todas as mortes", "os bugs da live", "a saga do carro"), somando entre {longo_min} e {longo_max}
segundos já descontado o que você aparou. Liste os ids na ordem em que devem aparecer. Cada corte
curto pode estar em no máximo uma compilação. Se não houver tema que una os cortes de forma natural,
devolva a lista vazia: uma compilação forçada é pior que nenhuma.

Responda só com o JSON no formato pedido, com uma avaliação para cada id recebido."""


class Avaliacao(BaseModel):
    id: str
    aprovar: bool
    nota: float = Field(ge=0, le=10)
    aparar_inicio: float = Field(ge=0, le=40)
    aparar_fim: float = Field(ge=0, le=40)
    titulo: str
    descricao: str
    hashtags: list[str]
    motivo: str


class Compilacao(BaseModel):
    ids: list[str]
    titulo: str
    descricao: str
    hashtags: list[str]
    motivo: str


class Resultado(BaseModel):
    avaliacoes: list[Avaliacao]
    compilacoes: list[Compilacao]


def credenciais_disponiveis() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))


def _frases(palavras: list[dict], inicio: float, fim: float, pausa: float = 0.6) -> str:
    """Transcrição em linhas '[mm:ss] frase', com tempo relativo ao início do trecho."""
    dentro = [p for p in palavras if p["e"] > inicio and p["s"] < fim]
    linhas, atual = [], []
    for p in dentro:
        if atual and (p["s"] - atual[-1]["e"] > pausa or atual[-1]["w"][-1:] in ".!?"):
            linhas.append(atual)
            atual = []
        atual.append(p)
    if atual:
        linhas.append(atual)
    saida = []
    for ln in linhas:
        t = max(0, ln[0]["s"] - inicio)
        saida.append(f"[{int(t) // 60:02d}:{int(t) % 60:02d}] " + " ".join(p["w"] for p in ln))
    return "\n".join(saida) or "(sem fala)"


def _bloco(ident: str, c: dict) -> str:
    sinais = f"nota de áudio/chat {c.get('nota_sinal', c['nota'])}"
    if c.get("fala"):
        f = c["fala"]
        sinais += f", reações faladas {f['reacoes']}, risadas {f['risadas']}, {f['palavras_por_s']} palavras/s"
    t = int(c["inicio"])
    return (f"<candidato id=\"{ident}\" duracao=\"{c['fim'] - c['inicio']:.0f}s\" "
            f"momento_da_live=\"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}\">\n"
            f"Sinais: {sinais}\nTranscrição:\n{_frases(c.get('palavras', []), c['inicio'], c['fim'])}\n</candidato>")


def avaliar(curtos: list[dict], longos: list[dict], canal: dict, cfg: dict) -> tuple[dict[str, Avaliacao], list[Compilacao]]:
    """Retorna ({id: Avaliacao}, compilações). Cada candidato já tem c["id"] ("c…" curto, "l…" longo).
    Levanta exceção em erro de API."""
    import anthropic

    tk, ct = cfg["tiktok"], cfg["corte"]
    sistema = SISTEMA.format(curto_min=ct["duracao_min"], curto_max=ct["duracao_max"],
                             longo_min=tk["duracao_min"], longo_max=tk["duracao_max"],
                             max_comp=tk["max_compilacoes_por_live"])
    hint = (cfg.get("ia") or {}).get("contexto", "")
    pedido = (
        f"Canal: {canal.get('canal_destino', '')} (streamer: {canal.get('login', '')}).{(' ' + hint) if hint else ''}\n\n"
        f"## {len(curtos)} candidatos CURTOS\n\n" + "\n\n".join(_bloco(c["id"], c) for c in curtos)
        + f"\n\n## {len(longos)} candidatos LONGOS\n\n" + ("\n\n".join(_bloco(c["id"], c) for c in longos) or "(nenhum)")
    )

    cliente = anthropic.Anthropic()
    resp = cliente.beta.messages.parse(
        model=MODELO,
        max_tokens=32000,
        system=sistema,
        messages=[{"role": "user", "content": pedido}],
        output_format=Resultado,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("a IA recusou a avaliação desta live")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError(f"resposta incompleta da IA (stop_reason={resp.stop_reason})")
    validos = {c["id"] for c in curtos + longos}
    avals = {a.id: a for a in resp.parsed_output.avaliacoes if a.id in validos}
    return avals, resp.parsed_output.compilacoes


def aplicar(cands: list[dict], avaliacoes: dict[str, Avaliacao], duracao_min: float) -> None:
    """Grava a avaliação em cada candidato (pelo c["id"]), apara as bordas e reordena pela nota da IA."""
    for c in cands:
        a = avaliacoes.get(c.get("id"))
        if a is None:
            continue
        c["ia"] = a.model_dump()
        ini, fim = c["inicio"] + a.aparar_inicio, c["fim"] - a.aparar_fim
        if fim - ini >= duracao_min:
            c["inicio"], c["fim"] = round(ini, 2), round(fim, 2)
        if not a.aprovar:
            c["descartado"] = f"IA: {a.motivo}"
    cands.sort(key=lambda c: (c.get("ia") is not None and c["ia"]["aprovar"], c.get("ia", {}).get("nota", -1), c["nota"]),
               reverse=True)


def montar_compilacoes(curtos: list[dict], compilacoes: list[Compilacao], cfg: dict) -> list[dict]:
    """Valida as compilações da IA contra as regras (aprovados, sem repetir, duração) e as converte
    para o formato do .json. Compilações que não fecham a conta são descartadas."""
    tk = cfg["tiktok"]
    por_id = {c.get("id"): c for c in curtos}
    usados, saida = set(), []
    for comp in compilacoes:
        partes = [por_id[i] for i in comp.ids if i in por_id and i not in usados
                  and (por_id[i].get("ia") or {}).get("aprovar")]
        total = sum(p["fim"] - p["inicio"] for p in partes)
        if not (2 <= len(partes) <= 4 and tk["duracao_min"] <= total <= tk["duracao_max"]):
            continue
        usados.update(p["id"] for p in partes)
        saida.append({
            "partes": [p["id"] for p in partes], "inicio": partes[0]["inicio"], "duracao": round(total, 1),
            "ia": {"titulo": comp.titulo, "descricao": comp.descricao, "hashtags": comp.hashtags, "motivo": comp.motivo},
        })
        if len(saida) >= tk["max_compilacoes_por_live"]:
            break
    return saida


# ------------------------------------------------------------------ legenda de um corte só

LEGENDA = """Você escreve a legenda de um corte vertical de live para TikTok, Shorts e Reels.

- titulo: até 80 caracteres, em português do Brasil, na voz de quem assistiu. Diga o que acontece
  e qual é a graça, com o detalhe mais específico do trecho — é o específico que prende, não o
  superlativo. Nada de emoji, e nada de clickbait vazio ("você não vai acreditar", "olha o que
  aconteceu"): prometer sem entregar é o que faz o povo deslizar pra cima.
- descricao: uma ou duas frases com energia, na linguagem de quem assiste live. Ela puxa o
  espectador pra dentro — completa o título com o que ele ainda não sabe, dá o contexto que faz
  a cena ter graça, ou provoca uma reação ("quem nunca?", "e ainda culpou o amigo"). Nunca
  repete o título com outras palavras. Pode terminar com uma pergunta curta se couber natural.
- hashtags: 4 a 6, minúsculas, sem o símbolo # e sem espaço dentro de cada uma. Misture: uma ou
  duas bem amplas, que muita gente segue (o jogo, o tipo de conteúdo), e duas ou três específicas
  do que aconteceu no corte ou do streamer. Só hashtag que alguém realmente buscaria ou segue —
  nada inventado na hora, e nada de #fyp, #viral ou #foryou, que não entregam alcance nenhum.

Você recebe a transcrição do trecho. Se ela não disser nada de interessante, diga isso no título
em vez de inventar: é melhor o editor saber que o corte é fraco."""


class Legenda(BaseModel):
    titulo: str
    descricao: str
    hashtags: list[str]


def pedido_legenda(c: dict, canal: dict, cfg: dict) -> str:
    """O pedido em texto. Serve para a chamada à API e para o botão que copia o prompt:
    quem não tem credencial cola isso em qualquer chat e recebe a mesma coisa."""
    texto = _frases(c.get("palavras", []), c["inicio"], c["fim"]) if c.get("palavras") else (c.get("texto") or "")
    hint = (cfg.get("ia") or {}).get("contexto", "")
    return (f"Canal: {canal.get('canal_destino', '')} (streamer: {canal.get('login', '')})."
            f"{(' ' + hint) if hint else ''}\n\nTranscrição do corte:\n{texto or '(sem fala)'}")


def prompt_avulso(c: dict, canal: dict, cfg: dict) -> str:
    """Prompt inteiro — instruções e pedido juntos — para colar num chat qualquer.

    Pede a resposta dentro de um bloco de código: ChatGPT, Gemini e Claude desenham um botão
    de copiar em cima de bloco de código, e no celular isso é um toque em vez de arrastar o
    dedo para selecionar. Pede as hashtags já com # para o texto sair pronto para colar.
    Texto simples e não JSON, que fica legível na tela do chat."""
    return (f"{LEGENDA}\n\n"
            f"Responda com UM bloco de código, e nada fora dele — nem introdução, nem comentário.\n"
            f"Dentro do bloco, exatamente estas três linhas:\n\n"
            f"```\nTítulo: ...\nDescrição: ...\nHashtags: #assim #com #cerquilha\n```\n\n"
            f"---\n\n{pedido_legenda(c, canal, cfg)}")


def legenda_para(c: dict, canal: dict, cfg: dict) -> dict:
    """Título, descrição e hashtags para um corte já escolhido. Levanta RuntimeError em erro."""
    import anthropic

    if not credenciais_disponiveis():
        raise RuntimeError("falta a ANTHROPIC_API_KEY: defina a variável de ambiente e reinicie o painel.")
    pedido = pedido_legenda(c, canal, cfg)
    try:
        resp = anthropic.Anthropic().beta.messages.parse(
            model=MODELO, max_tokens=2000, system=LEGENDA,
            messages=[{"role": "user", "content": pedido}],
            output_format=Legenda, output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except Exception as e:
        raise RuntimeError(f"a IA não respondeu: {e}") from e
    if resp.parsed_output is None:
        raise RuntimeError(f"resposta incompleta da IA (stop_reason={resp.stop_reason})")
    r = resp.parsed_output
    return {"titulo": r.titulo[:100], "descricao": r.descricao,
            "hashtags": [h.strip().lstrip("#") for h in r.hashtags if h.strip()][:10]}
