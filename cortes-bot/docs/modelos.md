# Modelos de edit

Um **modelo** é uma receita de estilo para o [edit de filme](edits.md), tirada de um modelo de referência (os
modelos do CapCut, por exemplo). O fluxo do edit não muda: filme + música → gancho com fala → drop → cortes na
batida. O modelo muda **como** isso aparece: formato, transições, ritmo, cor, o fim e, se quiser, um **letreiro**
que troca a legenda das falas por texto palavra por palavra.

Usar: na aba **Edits**, **Ver modelos…** (a galeria com as prévias) e **Usar este**, ou
`python -m cortes edit <filme> <musica> --modelo honorable`. `python -m cortes modelos` lista os que existem.

## O que muda num edit com modelo

A análise e as escolhas são as mesmas de sempre: cortes de câmera, Whisper, a IA escolhendo gancho, planos e
título, batidas e drop da música. O modelo só troca os parâmetros antes do plano e o jeito de renderizar:

| Etapa | Sem modelo | Com o Honorable |
|---|---|---|
| Formato | o do config (4:5 com tarjas) | 9:16 tela cheia |
| Gancho (e falas da abertura) | o filme, com a legenda neon | cartão preto com o letreiro de LED palavra por palavra; nas pausas da fala, o filme |
| Drop | flash | o letreiro enrola (rolo) e o primeiro plano entra no zoom |
| Cortes da música | 0,55 a 1,6 s, zoom/chicote/giro/fusão/flash | 0,4 a 1 s, corte seco, flash a cada 8, moldura piscando de tempos em tempos |
| Cor e fim | fria, escurece em 0,4 s | quente, escurece em 0,9 s |

A IA não sabe do modelo: escolhe o gancho e os planos como faria sem ele. A fala em cima do drop (`fala_drop`)
continua com a legenda neon. Sem fala no filme não há gancho, e o modelo só muda os cortes, a cor e o fim. Ajustar
o edit depois (drop, gancho, cortes, aba Geral) mantém o modelo, porque ele está no `plano.json`.

## Galeria e prévias

O painel mostra os modelos numa galeria (`#dlg-modelos`), com o **edit padrão** primeiro, para comparar. Cada cartão
toca a prévia do modelo e mostra o formato, se usa letreiro, a transição do drop e as transições dos cortes, com
**Usar este** e o link do original.

A prévia (`modelos.previa`, rota `/previa-modelo/<id>.mp4`) é um edit de verdade, feito pelo `_montar_plano` e pelo
`renderizar(previa=True)`, sobre mídia sintética: um "filme" de 16 degradês animados de 4 s, sem som, com luzes
desfocadas passando em duas camadas (sem movimento, a rampa não aparece), e uma batida
a 100 BPM com drop em 20 s, mais uma fala de exemplo com pausas (`FALA_PREVIA`). Nada com direito autoral. Os arquivos
ficam em `dados/modelos/`: `filme_v3.mp4`, `musica.wav` e `cenas.json`, feitos uma vez, e `<id>/plano.json` e
`<id>/previa.mp4`. Uma prévia é refeita quando o `.yaml` ou o código dos efeitos (`modelos.py`, `efeitos.py`,
`edit.py`, `legendas.py`) fica mais novo que ela. A primeira leva uns 25 s, contando a mídia sintética; as outras,
de 5 a 20 s. A galeria pede uma prévia por vez, e o servidor gera uma por vez (`_trava`).

## Onde ficam e quem manda

- Cada modelo é um arquivo `modelos/<id>.yaml` na pasta do cortes-bot (ao lado do `config.yaml`). O `id` é o nome
  do arquivo (minúsculas, números, `_` e `-`).
- `cortes/modelos.py`: `carregar` (confere as chaves), `listar` (para o painel) e `aplicar` (põe o modelo por cima
  da seção `edit:` do config).
- Ordem, do mais fraco para o mais forte: `config.yaml` < **modelo** < o que veio à mão (Ajustes finos do painel,
  opções do comando) < o tema (IA) nas coisas que ele decide < o ajuste depois de pronto. O `cmd_edit` aplica o modelo
  na seção `edit:` antes de misturar as opções da mão.
- O plano guarda o resultado: `plano.json` ganha `modelo` (o id), `config` (a seção `edit:` já com o modelo) e
  `estilo.letreiro` / `estilo.fim_preto`. Renderizar de novo ou ajustar no painel não relê o `.yaml`: um edit feito
  continua igual mesmo se o modelo mudar depois.

## O arquivo

```yaml
nome: Honorable                 # o que aparece no painel
descricao: ...                  # uma ou duas frases, mostradas embaixo do campo
referencia: https://...         # de onde o modelo veio
edit:                           # chaves da seção edit: do config (edit.PADRAO); só as que mudam
  proporcao: "9:16"
  corte_min: 0.4                # o ritmo "normal" usa corte_min..corte_max
  corte_max: 1.0
  transicoes: [corte, flash, moldura]
  transicao_drop: rolo          # como o drop entra (padrão: flash)
  fim_preto: 0.9                # segundos escurecendo no fim (padrão: 0,4)
  cor: {contraste: 1.16, saturacao: 0.95, brilho: -0.02, balanco: quente, vinheta: true, grao: 2}
letreiro:                       # opcional; o que faltar vem de modelos.LETREIRO
  fonte: Impact
  cores: [FFFFFF, E8202A]
```

Uma chave que o edit não conhece, ou uma transição que não existe, faz o `carregar` recusar o modelo (e ele some da
lista do painel). `cor.balanco`: `frio` (o padrão dos edits), `quente` (sombras azuladas, luz alaranjada) ou `neutro`
(`edit.BALANCO`).

## O letreiro

Com `letreiro`, cada fala com som (as da abertura e o gancho) vira um **cartão preto com o texto em LED** por cima
do filme, no lugar da legenda neon:

- **Telas** (`legendas.telas_letreiro`): as palavras em grupos de até `max_palavras` / `max_chars`. Uma pausa maior
  que `pausa` ou um ponto final começa outra tela. A tela fica no ar até `segura` segundos depois da última palavra.
- **Palavra por palavra** (`legendas.gerar_ass_letreiro`): cada palavra aparece no instante em que é dita, `pulo` vezes
  maior, e assenta em 0,1 s. As cores se alternam palavra a palavra (`cores`, em RGB). O texto fica em maiúsculas, sem
  pontuação.
- **Relâmpagos**: um buraco na fala de pelo menos `relampago_min` segundos tira o cartão e mostra o filme (o próprio
  trecho do gancho, com o som batendo com a boca). Buraco menor fica no preto.
- **LED** (`efeitos.letreiro`): o texto sai num `color=black` com `subtitles`, é multiplicado por uma grade de
  pontos (`led_passo` px entre os LEDs, `led_fundo` de brilho entre eles; a máscara é calculada num quadro só e
  repetida com `loop`), ganha aberração cromática (`rgbashift`, `aberracao` px) e um brilho desfocado (`brilho`).
- O cartão entra por `overlay` com `enable` (`efeitos.sem_letreiro`) no trecho da fala. O `.ass` de cada trecho
  (`letreiro_<k>.ass`) é apagado depois do render. A fala em cima do drop (`fala_drop`) continua com a legenda neon.

## A legenda em destaque e o texto do editor

Com `destaque` (o bloco do modelo; o que faltar vem de `modelos.DESTAQUE`), as falas com som (abertura, gancho e a
fala em cima do drop) saem em **duas camadas**, como nos edits de hype (`legendas.gerar_ass_destaque`):

- **Frases** (`legendas.frases_destaque`): as palavras em frases (até `max_palavras`/`max_chars`, quebrando em pausa
  maior que `pausa` ou em ponto final). As **grandes** são as últimas palavras da frase, até `max_grandes` palavras,
  `max_chars_grandes` letras e metade da frase (pelo menos uma): "let's get / STARTED", "to me / MY X-MEN",
  "lend me the strength of / THE ALL FATHERS". As outras são as **pequenas**.
- **As pequenas** (fonte `fonte_pequena`, `tamanho_pequena`) ficam em cima, brancas, em minúsculas, entrando uma a
  uma no instante em que são ditas.
- **As grandes** (fonte `fonte`, `tamanho`) ficam embaixo, em maiúsculas, também entrando quando ditas: chegam `pulo`%
  maiores e assentam em `entrada_ms`, e saem desfocando em `saida_ms`. A altura é `altura` (de 0, o topo da imagem,
  a 1, a base).
- **O degradê**: o libass não pinta degradê, então a linha grande é desenhada `faixas` vezes, cada cópia recortada
  (`\clip`) numa faixa horizontal e pintada com a cor daquele ponto entre o topo e a base das letras. Por baixo, a
  mesma linha na cor do meio, desfocada e meio transparente, faz o brilho. Cada frase usa o par de cores seguinte
  de `cores` (topo, base), como no original: rosa-laranja, vermelho, verde, dourado.

Com `texto_editor: true` (chave de `edit:`), a IA escreve `texto_editor`, de 2 a 5 palavras de impacto ("MARVEL
DECIDED TO COOK"), e o `edit._texto_editor` põe uma em cada corte a partir do drop (depois da fala do drop, se
houver). Cada palavra fica grande, branca e com brilho no meio da imagem (`tamanho_editor`) até a próxima, e a cada
palavra nova o quadro inteiro fica **preto por um quadro** só com ela (o `drawbox` antes das legendas). O plano
guarda as palavras já no tempo do vídeo (`plano.texto_editor`). Sem IA não há texto do editor; a prévia da galeria
usa `TEXTO_PREVIA`. Um modelo pode ligar o texto do editor sem o `destaque`: aí ele usa o estilo padrão do destaque.

## Velocity edit: rampa, borrão, movimento e preparação

Chaves de `edit:` que o `funk_power` liga (todas desligadas no padrão):

- **`rampa`** (0 a 0,95): cada corte da música ganha uma rampa de velocidade, rápido → lento → rápido
  (`edit._curva_rampa`). A velocidade, no tempo de saída, cai em V das pontas até `1 - rampa` delas no meio
  (`RAMPA_FORMA` = 1,2), e o `setpts` recebe o inverso dessa curva como retas por pedaço (24 `if` encadeados).
  O corte continua usando `dur * vel` segundos de filme: com `velocidade: 1.6`, as pontas andam ~3x e o meio
  ~0,3x. O corte de uma fala no drop (modo "durante") fica sem rampa, para o som bater com a boca. O plano
  guarda `rampa` em cada corte.
- **`borrao_movimento`**: o plano vai a 240 fps com mistura de quadros vizinhos (`framerate`), e cada quadro final
  junta 8 (`tmix`). Onde o filme corre, sai rastro; no lento, a mistura troca o tranco de quadro repetido por um
  leve fantasma. Só nos cortes com rampa ou acelerados.
- **`zoom_cortes: false`**: sem o soco de zoom e a tremida nos cortes da música (`zoom: "nenhum"`).
- **`preferir_movimento`**: `cenas.detectar` grava `mov` em cada plano, a nota de cena média dos quadros de dentro
  dele (0 = parado, ~0,05 = ação). `edit._por_movimento` manda para o fim da fila os planos abaixo do 35º percentil,
  sem mudar a ordem do resto. Um cache de planos antigo, sem `mov`, é medido de novo uma vez (a detecção relê o
  trecho do filme; o brilho já medido fica).
- **`preparacao`** (segundos): planos lentos antes do drop, com a música subindo (`_pontos_preparacao`,
  `_acabar_preparacao`). Começa na batida mais perto desse tempo antes do drop e troca de plano na batida do meio:
  os dois primeiros da escolha (a IA põe os melhores na frente) que cabem na câmera lenta e não são cartela, a
  `VEL_PREPARACAO` (0,5x), aproximando devagar. Não os mais longos: num trailer, os mais longos são as cartelas do
  fim (a primeira versão pôs o logo do canal e a tela de data de estreia na preparação); o segundo entra em fusão
  quando dá. Eles ficam em `plano.preparacao` (mesmo formato dos cortes) e `preparacao_dur`, e não voltam
  depois do drop. A música entra no começo da preparação. Ainda não dá para mexer neles na aba Cortes do ajuste.
- **`inicio_preto`** (segundos): o edit começa saindo do preto.
- **`dica_ia`**: uma frase que vai para a IA como "Estilo do edit", para ela escolher gancho e planos com o
  modelo em mente (no Funk Power: planos de ação, gancho curto).

## Transições dos modelos

Além das do [edit](edits.md#transições), duas que mexem no **fim do trecho anterior** (por isso só entram depois de um
corte de pelo menos `DUR_ANTES_ESPECIAL` = 0,55 s, de tempos em tempos: `ESPECIAIS` em `edit.py`; no render, se o
trecho de antes for curto demais, viram a transição de cabeça delas):

| Transição | Plano que sai | Plano que entra |
|---|---|---|
| `rolo` | os últimos 8 quadros enrolam para a esquerda como um rolo de papel (`efeitos.rolo`: `geq` com `asin`, o que passa do eixo dobra para trás, menor e mais escuro); sobra o preto | chega no zoom |
| `moldura` | nos últimos 15 quadros, uma moldura branca pisca com o primeiro quadro do plano seguinte dentro dela: 40%, 60%, 80% e o branco cheio (`efeitos.MOLDURA`) | sai do branco (o flash) |
| `mergulho` | escurece nos últimos `MERGULHO` (6) quadros | `RISCO` (3) quadros de preto com um risco de luz horizontal cruzando o meio (`drawbox` + `gblur` só nesses quadros) e sai do preto em 6 quadros |
| `flash_seco` | — | o primeiro quadro todo branco, sem fade (o estouro do raio) |

`mergulho` e `flash_seco` mexem só no plano que sai e no que entra, como as do edit (não são `ESPECIAIS`). Na escolha
(`edit._transicao`): `flash_seco` a cada 6 cortes (no 3º), `mergulho` a cada 9 (no 6º, depois de um corte de 0,4 s
ou mais). Um modelo com `corte` e `zoom` na lista tem o corte seco como base: corte, zoom, corte.

O `rolo` é a `transicao_drop` do Honorable: o letreiro enrola e o drop entra. No painel, as duas aparecem na aba
Cortes do ajuste ("rolo (o de antes enrola)", "moldura piscando").

## Modelos que existem

| id | De onde | O que faz |
|---|---|---|
| `funk_power` | [FUNK POWER](https://www.capcut.com/template-detail/7699775090845650196) (CapCut, 20 s, 33 clipes) | velocity edit: sai do preto, 6 s de preparação com dois planos lentos, e um corte por batida (0,35 a 0,8 s) em corte seco, cada um com rampa rápido-lento-rápido e borrão de movimento; planos de ação primeiro; música sem slowed; fim seco |
| `peak_days` | ["Peak Days are Coming..."](https://www.youtube.com/shorts/8sbY1Zt0Yr0) (YouTube Shorts, Parthedits8, 30 s, 4:5) | edit de hype: falas na legenda em destaque (pequenas em cima, a palavra-chave grande com degradê e brilho, uma cor por frase); drop no mergulho com o risco de luz; texto do editor da IA, uma palavra por batida com a piscada preta; cortes de 0,3 a 1 s em corte seco e zoom, com flash seco; cor quente, sem grão; música sem slowed |
| `honorable` | [HONORABLE](https://www.capcut.com/template-detail/7671220229229301013) (CapCut, 20 s, 14 clipes) | gancho em letreiro de LED palavra por palavra no preto, com relâmpagos do filme; drop com rolo; planos de 0,4 a 1 s em corte seco, flash e moldura piscando; cor quente; fim escurecendo em 0,9 s |

O comentário no topo de cada `.yaml` diz como o original é montado, medido quadro a quadro.

## Como criar um modelo novo

1. Meça o original: onde caem os cortes e as palavras (no HONORABLE, todos caem a 1 ou 2 quadros de um ataque do
   áudio), quanto duram os planos, que transições aparecem, a cor e o texto.
2. Escreva `modelos/<id>.yaml` com o que der para fazer com o que já existe (chaves de `edit:` e `letreiro:`).
3. O que faltar vira um efeito novo em `cortes/efeitos.py` (um pedaço de filtro do ffmpeg), reaproveitável por
   qualquer modelo: uma transição nova entra em `TRANSICOES` (e, se mexe no trecho de antes, em `ESPECIAIS`,
   `CABECA_DE` e `efeitos.QUADROS`), um estilo de texto novo vira chave do `letreiro`.
4. Teste em `tests/teste_modelos.py` (música e filme sintéticos, numa pasta temporária) e atualize a tabela acima.

## Limitações

- O letreiro e o destaque usam fontes do sistema (`Impact` e `Arial` no Windows). Uma fonte que não existe cai na
  padrão do libass. O original do Peak Days usa uma fonte condensada mais fina (tipo Bebas): a Impact é a mais
  parecida que vem no Windows.
- O degradê do destaque é feito de faixas (8 por padrão): numa letra muito grande dá para ver os degraus.
- O texto do editor depende da IA. No original ele também abre o vídeo ("while everyone was busy / PLAYING GTA 6"),
  sobre planos de outro filme; aqui ele só entra depois do drop.
- O "Peak Days" foi medido no navegador, no vídeo de 360 px que o YouTube entrega: os tempos e as cores são
  confiáveis, os detalhes finos (a espessura do brilho, a fonte) são aproximados.
- O cartão do letreiro é sempre preto. No original, a voz vem da própria música; aqui ela vem da fala do filme.
- A rampa não interpola quadros como o CapCut (que inventa os do meio com IA): o lento fica com um leve fantasma
  da mistura de quadros. Interpolação por fluxo óptico (`minterpolate`) seria mais lisa, mas é muito mais pesada.
- O rolo deixa o preto atrás (no original aparece o plano seguinte) e a moldura usa um quadro parado do plano seguinte.
- Efeitos 3D, partículas e rastreamento de objeto do CapCut ficam de fora ou aproximados.
