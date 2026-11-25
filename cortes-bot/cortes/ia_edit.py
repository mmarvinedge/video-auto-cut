"""A IA de diretor do edit: escolhe a fala de gancho e os planos que vão na batida.

Uma chamada só, com a transcrição do filme (tempos em segundos) e as folhas de contato
(miniaturas numeradas já no recorte vertical). Ver as duas coisas juntas deixa a IA casar
os planos com o tema da fala: se o gancho é o Peter chamando a Gwen para sair, os planos da
música são dos dois, e não de uma cena de luta qualquer.
"""
import base64
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .ia import MODELO, credenciais_disponiveis  # noqa: F401  (credenciais_disponiveis é usado por quem importa)

SISTEMA = """Você é editor de um canal brasileiro de "edits" de filmes e séries para TikTok, Reels e Shorts.

Um edit tem estas partes, nesta ordem:
0. ABERTURA (opcional, só se o tema pedir algo antes do gancho, como "introduza antes para gerar
   expectativa"): 2 a 4 FALAS curtas do filme, com o som e a legenda originais e SEM música, uma
   depois da outra, como o começo de um trailer: frases que anunciam o que vem ("A hora chegou.",
   "Agrupem-se.", uma ameaça, um chamado). Até 15s no total. A música só começa no drop.
1. GANCHO ({g_min}–{g_max}s; até {g_longo}s se o tema pedir a conversa ou a cena inteira): um diálogo
   do filme, com a fala original e a legenda grande na tela.
   É uma frase marcante e que se entende sozinha: uma cantada, uma declaração, uma ameaça, uma
   resposta seca, um momento icônico. Com começo e fim claros (sem cortar ninguém no meio da frase)
   e de preferência terminando numa fala de impacto, porque é ali que a música entra.
2. MÚSICA: a música entra e os planos trocam na batida. Aqui não tem fala: são planos bonitos e
   expressivos que combinam com o clima do gancho. Prefira closes e planos médios do personagem
   principal do gancho (rosto, olhar, expressão), planos com luz bonita e movimento; evite plano
   aberto sem ninguém, tela escura, letreiro, cena borrada ou personagem cortado pelo recorte
   vertical. Varie: não repita planos quase iguais em sequência. NUNCA escolha o que não é imagem
   do filme: logo de estúdio ou de canal, título do filme, data de estreia ("nos cinemas"),
   classificação indicativa, créditos, cartela com texto (trailers têm muitas, sobretudo no fim).

Você recebe a transcrição (cada linha com o tempo em segundos do filme), a lista dos planos com o
tempo de cada um no filme e folhas de miniaturas. Cada miniatura tem o número do plano no canto e
já mostra o recorte vertical que vai para o edit. A miniatura é um quadro só, do meio do plano: um
plano que parece branco ou escuro pode ser um clarão ou um momento importante (um estalo, uma
explosão); confira pelo tempo na transcrição antes de descartar.

O TEMA do editor, quando houver, manda: siga o que ele pedir de duração, de gancho e de onde cai
o drop, usando os campos abaixo.

Responda com:
- gancho_inicio / gancho_fim: em segundos do filme, como aparecem na transcrição. Comece no
  começo da primeira fala do gancho e termine no fim da última.
- gancho_texto: a fala do gancho, como foi dita.
- planos: os números dos planos da parte da música, NA ORDEM em que devem aparecer, com
  {n_planos} números (os primeiros {n_min} são os que certamente entram; os outros são reserva
  ou servem para um edit mais longo). Só números que aparecem nas folhas. Guarde o plano mais
  forte para o primeiro, que cai em cima do drop da música. Se usar drop_no_filme, a lista começa
  pelo plano que vem DEPOIS do momento do drop (o do drop entra sozinho).
- duracao_musica: segundos da parte da música, só se o tema pedir uma duração (desconte o gancho
  de uma duração total: "edit de 1 minuto" com gancho de 20s = 40). Entre 5 e 60. null se o tema
  não falar de duração.
- ritmo: "rapido" (um corte por batida: cortes rápidos, "transições rápidas", sequência frenética),
  "lento" (planos longos, clima contemplativo) ou "normal". null se o tema não falar de ritmo.
- abertura: as falas da abertura, na ordem em que entram, cada uma com inicio/fim em segundos do
  filme como na transcrição (do começo da primeira palavra ao fim da última); só se o tema pedir
  algo antes do gancho, lista vazia se não pedir. Não use falas de dentro do gancho.
- fala_drop_fim: quando o drop cai numa FALA que precisa ser ouvida em cima do drop (um grito de
  guerra, um chamado: "A mim, meus X-Men!", "Avante, Vingadores!"), o segundo do filme em que essa
  fala termina (pela transcrição). O som do filme continua por cima da música até ali, com
  legenda. null se o drop não cai numa fala.
- texto_editor: só se o "Estilo do edit" pedir texto do editor: 2 a 5 palavras de impacto, em
  MAIÚSCULAS, que entram uma por batida logo depois do drop, por cima dos planos ("MARVEL DECIDED TO
  COOK", "O DOUTOR CHEGOU"). Uma frase curta e forte sobre o filme ou o tema, na língua do tema (ou
  português, sem tema). Uma palavra por item. Lista vazia se o estilo não pedir.
- drop_na_fala: só se o tema disser quando o drop cai em relação à fala do gatilho: "depois"
  ("depois que ele falar", "quando ele terminar") ou "durante" ("junto com a fala", "em cima
  da fala"). null se o tema não disser (vale a configuração do editor). Com fala_drop_fim,
  marque drop_no_filme no começo da fala, nos dois casos.
- drop_no_filme: o segundo do filme que deve cair no drop, quando o tema pede o drop num momento
  (um estalo, um soco, um beijo, uma explosão). O primeiro plano da música começa exatamente ali
  e o gancho termina logo antes. Ache pelo tempo dos planos e da transcrição. null se o tema não
  pedir.
- titulo: em português do Brasil, até 70 caracteres, no tom dos títulos de edit ("Tá ocupado
  sexta à noite? - Spider Man Edit"): a frase do gancho ou o tema, mais o nome do filme/personagem.
- descricao: uma frase curta.
- hashtags: 3 ou 4, minúsculas, sem #: o filme, o personagem, o casal/tema. Nada inventado.
- motivo: duas ou três frases explicando o gancho, o drop e a sequência dos planos (e, se usou, a
  duração e o momento do drop tirados do tema), para o editor humano revisar. Nunca deixe vazio."""


class Trecho(BaseModel):
    inicio: float = Field(ge=0)
    fim: float = Field(ge=0)


class PlanoIA(BaseModel):
    gancho_inicio: float = Field(ge=0)
    gancho_fim: float = Field(ge=0)
    gancho_texto: str
    planos: list[int]
    duracao_musica: float | None = None
    drop_no_filme: float | None = None
    ritmo: Literal["rapido", "normal", "lento"] | None = None
    abertura: list[Trecho] = []
    fala_drop_fim: float | None = None
    drop_na_fala: Literal["durante", "depois"] | None = None
    texto_editor: list[str] = []
    titulo: str
    descricao: str
    hashtags: list[str]
    motivo: str


def transcricao_em_linhas(palavras: list[dict], pausa: float = 0.6) -> str:
    """'[1234.5] frase' por linha, quebrando em pausa ou fim de frase."""
    linhas, atual = [], []
    for p in palavras:
        if atual and (p["s"] - atual[-1]["e"] > pausa or atual[-1]["w"][-1:] in ".!?"):
            linhas.append(atual)
            atual = []
        atual.append(p)
    if atual:
        linhas.append(atual)
    return "\n".join(f"[{ln[0]['s']:.1f}] " + " ".join(p["w"] for p in ln) for ln in linhas) or "(sem fala)"


def planos_em_linhas(cenas_: list[dict]) -> str:
    """'12: 225.2–236.3' por plano: a IA precisa do tempo para casar plano com fala e momento."""
    return "\n".join(f"{c['id']}: {c['inicio']:.1f}–{c['fim']:.1f}" for c in cenas_)


def escolher(palavras: list[dict], folhas: list[Path], faixas: list[tuple[int, int]], n_planos: int,
             n_min: int, cfg_edit: dict, filme: str, tema: str = "", cenas_: list[dict] | None = None) -> PlanoIA:
    """`faixas`: (primeiro, último) número de plano de cada folha, só para a IA se localizar.
    `cenas_`: os planos das folhas, para a lista com o tempo de cada um."""
    import anthropic

    sistema = SISTEMA.format(g_min=cfg_edit["gancho_min"], g_max=cfg_edit["gancho_max"],
                             g_longo=cfg_edit["gancho_longo"], n_planos=n_planos, n_min=n_min)
    conteudo = [{"type": "text", "text":
                 f"Filme: {filme}\n" + (f"Tema pedido pelo editor: {tema}\n" if tema else "")
                 + (f"Estilo do edit (modelo escolhido pelo editor): {cfg_edit['dica_ia']}\n"
                    if cfg_edit.get("dica_ia") else "")
                 + f"\n## Transcrição\n{transcricao_em_linhas(palavras)}\n"
                 + (f"\n## Planos (número: início–fim, em segundos do filme)\n{planos_em_linhas(cenas_)}\n"
                    if cenas_ else "")
                 + "\n## Folhas de miniaturas"}]
    for arq, (a, b) in zip(folhas, faixas):
        conteudo.append({"type": "text", "text": f"Folha {arq.stem} (planos {a} a {b}):"})
        conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(arq.read_bytes()).decode()}})
    resp = anthropic.Anthropic().beta.messages.parse(
        model=MODELO,
        max_tokens=8000,
        system=sistema,
        messages=[{"role": "user", "content": conteudo}],
        output_format=PlanoIA,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("a IA recusou montar este edit")
    if resp.parsed_output is None:
        raise RuntimeError(f"resposta incompleta da IA (stop_reason={resp.stop_reason})")
    return resp.parsed_output
