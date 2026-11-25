# Edits de filme

Um filme e uma música, ambos arquivos locais, viram um edit vertical no estilo dos canais de "edit" do TikTok:

1. **Gancho** (4–12 s): uma fala marcante do filme, com o áudio original e uma legenda em neon (maiúsculas
   espaçadas, brilho vermelho). A música toca baixinho por baixo.
2. **Música** (cerca de 15 s): a música sobe no **drop** e os planos trocam **na batida**, em câmera lenta, com zoom,
   tremida e flash.

Visual: recorte 4:5 com tarjas pretas (ou 9:16 tela cheia), cor escurecida e fria, vinheta e grão.

Dá para usar de dois jeitos: pela aba **Edits** do painel ou pelo comando
`python -m cortes edit <filme> <musica> [opções]`.

## Pelo painel (aba Edits)

1. **Filme** e **Música**, cada um **do computador** ou **do YouTube**:
   - do computador: cole o caminho ou clique em **Procurar…**. O seletor navega pelas pastas, mostra só vídeos
     (filme) ou áudios e vídeos (música) e lembra a última pasta usada;
   - do YouTube: cole o endereço e escolha a qualidade do download (veja abaixo). O edit baixa antes de começar, no
     mesmo trabalho.
2. **Tema** (opcional): o pedido para a IA, como "o romance do Peter e da Gwen". Além do clima, a IA lê nele:
   - a **duração** ("edit de 1 minuto");
   - um **gancho longo** ("o gancho é a conversa antes do estalo", até `gancho_longo` = 40 s);
   - o **momento do drop** ("drop na hora que ele estala os dedos");
   - uma **fala de gatilho** no drop ("drop no 'A mim, meus X-Men'"): por padrão ela fecha o gancho, limpa, e o drop
     entra quando ela acaba; no modo "durante", o drop entra com ela e a música fica abafada até ela acabar;
   - o **ritmo** ("transições rápidas" = um corte por batida; "lento" = planos longos);
   - uma **abertura** antes do gancho ("introduza antes do gancho para gerar expectativa"): falas do filme, com
     som e legenda, sem música, como o começo de um trailer.

   Um campo preenchido à mão em Ajustes finos vale mais que o tema, e o tema vale mais que o config.
3. **Trecho do filme** (opcional): início e fim, em `h:mm:ss` ou segundos. Analisar só uma parte é mais rápido e deixa
   os planos mais coerentes com o gancho. Ao lado, **Idioma da fala** (português, inglês, espanhol ou detectar
   sozinho): o idioma em que o Whisper transcreve o filme para achar o gancho.
4. **Ajustes finos** (recolhidos): formato (4:5 ou 9:16), velocidade da música (original até 0,8×), transições
   (variadas, só zoom e flash, só zoom ou corte seco), música antes do drop (baixinha debaixo da fala ou muda até o
   drop), volume da música (mais alta, normal, mais baixa, bem baixa), ritmo dos cortes, abertura antes do gancho (sem ou com falas do filme), duração da parte da música, drop
   (segundo da música), drop no filme (o momento do filme que cai no drop), drop e a fala do gatilho (depois ou durante), fim da fala do gatilho e
   gancho à mão. Em branco valem os padrões do `edit:` do `config.yaml`, que aparecem nos campos.
5. Opções: **sem IA**, **só planejar** (grava o `plano.json` sem renderizar) e **copiar para a pasta de prontos**.
6. **Criar edit**: o andamento aparece na caixa do trabalho (um trabalho por vez, compartilhado com a aba Lives). Ao
   terminar, o edit entra na lista.

Cada edit da lista mostra o vídeo, o gancho, o título, a descrição e as hashtags (editáveis: salvam no `plano.json` e
no `edit.txt`), o motivo da IA e os botões **Ajustar o edit**, **Renderizar de novo** (depois de editar o
`plano.json` à mão) e **Copiar para prontos**.

### Ajustar o edit (depois de pronto)

O botão **Ajustar o edit** abre uma tela com três abas. Na aba **Drop e gancho**:

- **O filme quadro a quadro**, já no recorte do edit: barra de posição, ±1 quadro e ±1 s (também ← → e Shift+← →),
  e o tempo digitado (`h:mm:ss.cc`). O navegador não toca mkv/HEVC de filme, então cada quadro vem do ffmpeg
  (`/quadro-edit`, ~0,1 s).
- **As falas perto do momento** (da transcrição em cache), com a fala atual destacada; clicar numa vai até ela.
- **As marcas**: gancho começa / termina (ou "sem gancho"), **drop no filme** (o gatilho: qualquer momento, com ou
  sem fala) e **fala do gatilho termina** (opcional), mais o modo da fala: depois (padrão) ou durante.
- **A música**: a onda inteira e um trecho de 30 s em volta do drop, com as batidas; clicar escolhe a batida do drop
  (ou "Drop automático"). "Ouvir o drop" toca 3 s antes e 3 s depois. **Volume da música** (30% a 150% do nível
  padrão) vai para `estilo.volume_musica`: confira na prévia e ajuste de novo se a música abafar as falas. O
  "Ouvir o drop" toca a música crua, sem esse nivelamento: o volume certo é o da prévia.
- **Aplicar e gerar prévia**: refaz o plano sem IA nem Whisper (`edit.replanejar`, menos de 1 s) e renderiza a prévia
  em 540 px com codificação rápida (`edit-render --previa` → `previa.mp4`; ~8 s para 28 s de edit), que abre 4 s
  antes do drop. **Desfazer** volta o plano anterior; **Renderizar final** faz o `edit.mp4`.

Na aba **Cortes**, cada corte da música aparece com o quadro do meio do trecho, o tempo no edit, a duração, o plano
e a velocidade, e cada mudança grava na hora (`POST /api/edits/<id>/corte` → `edit.editar_corte`):

- **Transição** de entrada (a do corte 1 é a do drop).
- **◀ 0,25s / 0,25s ▶**: o trecho começa antes ou depois no mesmo plano (preso às bordas do plano).
- **Trocar plano**: uma grade com as miniaturas dos planos do filme (borda dourada = já está no edit; os curtos
  demais para o corte ficam desligados). O corte pega o meio do plano novo; se faltar filme, puxa o início para
  trás e, no limite, fica mais lento (até 0,5×).
- **Dividir**: parte o corte na batida mais perto do meio (precisa de duas batidas); a segunda metade continua o
  mesmo plano, entra com zoom, e aí se troca o plano dela.
- **×**: exclui o corte; o de antes fica com a vez dele (no primeiro, o de depois), esticando o trecho ou ficando
  mais lento se precisar.

A duração total e o lugar das batidas nunca mudam: as `saida` são recalculadas pelas durações. A **fusão** é recusada
se o corte de antes não tiver filme sobrando depois do trecho (ela o estica 8 quadros). O plano ganha
`cortes_editados: true`; como ajustar o drop e o gancho monta os cortes de novo, a tela pede confirmação antes. Depois,
**Gerar prévia** e **Renderizar final**, como na outra aba, e **Desfazer** volta a última mudança.

Na aba **Geral** ficam os ajustes que mudam o edit inteiro: **ritmo dos cortes**, **parte da música** (5 a 60 s),
**transições** (variadas, só zoom e flash, só zoom, nenhuma; uma combinação vinda do config aparece como "Do edit"),
**abertura antes do gancho** (sem ou com falas: as que a IA escolheu ou, sem elas, as 3 últimas frases antes do
gancho) e **música antes do drop** (baixinha ou muda). **Aplicar e gerar prévia** manda tudo junto com as marcas da
aba Drop e gancho: o `edit.replanejar` monta os cortes de novo com os planos que a IA já escolheu, sem chamar a IA.
Os valores vêm do plano do edit (`ritmo`, `config.transicoes`, `abertura_falas`, `estilo.musica_no_gancho`), e o
que não vier no pedido fica como está.

`edit.replanejar` reaproveita tudo o que custou caro: as batidas (`batidas.json`, gravado no planejamento), os
planos e as falas do filme (caminhos em `plano.analise`; planos antigos procuram os `planos_*`/`falas_*` mais novos
da pasta do filme) e as escolhas da IA (`plano.ia`: planos, abertura, título). O que o editor marcou vale mais que o
tema: a IA não decide de novo drop, fala, ritmo nem duração. O que a aba Geral não mudar (ritmo, duração da música,
transições, abertura, música no gancho) continua como antes, assim como o título, a descrição e as hashtags. O plano anterior fica em `plano.anterior.json`
(desfazer troca os dois). Com um trabalho rodando, o ajuste é recusado (o trabalho pode estar renderizando este
edit).

O edit roda num processo filho do painel e só usa a IA se a `ANTHROPIC_API_KEY` estiver no ambiente **do painel**.
Como ele sobe sozinho com o Windows, grave a chave como variável de usuário (`setx ANTHROPIC_API_KEY "..."`) e rode
`iniciar_painel.pyw --reiniciar`. Sem a chave, o formulário mostra um aviso. Se o painel for aberto por um programa
que não tem a chave no ambiente (um terminal aberto antes do `setx`, uma ferramenta), o `iniciar_painel.pyw` a lê das
variáveis do usuário no registro (`_variaveis_do_usuario`) e anota no `dados/painel.log`; sem ela em lugar nenhum, o
log mostra `AVISO: sem ANTHROPIC_API_KEY`. (Um painel aberto assim, sem a chave, fez três edits saírem sem IA, com o
gancho fora do tema e cartelas no lugar de planos.)

### Filme e música do YouTube

Em "Do YouTube", o campo recebe o endereço de um vídeo (`youtube.com/watch?v=`, `youtu.be/`, `/shorts/`, `/live/` ou
`music.youtube.com`) e a qualidade:

- **Filme**: 1080p (padrão), 720p, 480p ou "melhor que houver", em mp4. Até 1080p o download prefere H.264 + AAC
  na mesma resolução (AV1/Opus dentro de mp4 não abre em vários players do Windows); "melhor" pega a maior
  resolução, que acima de 1080p costuma ser só VP9/AV1.
- **Música**: só o áudio, em mp3 "melhor" (VBR máximo, padrão), 192 ou 128 kbps.

O painel manda o endereço no lugar do arquivo (`edit <url> <url> --qualidade-filme 720 --qualidade-musica 192`), e
o comando baixa antes de analisar (`youtube.resolver`), com o andamento na mesma barra. Os detalhes:

- Os arquivos ficam em `dados/edits/_youtube/`, como `<título> [<id>].mp4|mp3`, com a qualidade no nome quando não
  é a padrão (`[720p]`, `[melhor]`, `[192k]`). Pedir de novo o mesmo vídeo na mesma qualidade reaproveita o
  arquivo. O seletor de arquivos tem o atalho **Baixados do YouTube**.
- Playlists são recusadas: só um vídeo por vez.
- O YouTube passou a exigir um interpretador de JavaScript para liberar todos os formatos. Com o **Deno** (ou o Node)
  no PATH, o yt-dlp usa sozinho. Sem ele, o download funciona, mas pode vir numa qualidade menor, e o log avisa.
- Os Termos do YouTube só permitem baixar o que o próprio YouTube oferece para download ou o que você tem direito de
  usar (vídeos seus, licença Creative Commons, autorização do dono).

## Pelo comando

| Opção | Faz |
|---|---|
| `--tema "..."` | dica para a IA |
| `--trecho 1:10:00-1:40:00` | analisa só essa parte do filme |
| `--gancho 1:23:10-1:23:19` | fala de gancho escolhida à mão (tempo do filme) |
| `--drop 41.2` | segundo da música, já tratada, onde os cortes começam |
| `--volume-musica 0.7` | volume da música sobre o nível padrão (`edit.volume_musica`; 1 = padrão) |
| `--musica-no-gancho sim\|nao` | `nao`: a música fica muda durante o gancho e entra no drop, no volume cheio (`edit.musica_no_gancho`) |
| `--drop-filme 3:56` | momento do filme que cai no drop: o primeiro plano da música começa ali e o gancho termina ali |
| `--fala-drop 3:58` | com `--drop-filme`: onde termina a fala do gatilho ("A mim, meus X-Men") |
| `--drop-fala depois\|durante` | `depois` (padrão): a fala fecha o gancho, limpa, e o drop entra quando ela acaba; `durante`: o drop entra com ela, com a música abafada até ela acabar (`edit.drop_fala`) |
| `--ritmo rapido\|normal\|lento` | tamanho dos cortes: rápido = 0,25–0,75 s (uma batida), lento = 1,4–3,2 s, normal = `corte_min`–`corte_max` |
| `--abertura sim\|nao` | falas do filme antes do gancho, sem música (`edit.abertura`) |
| `--proporcao 4:5\|9:16`, `--slowed 0.85`, `--duracao 15` | sobrepõem a seção `edit:` do config só neste edit |
| `--idioma pt\|en\|es\|...\|auto` | idioma da fala do filme para o Whisper (`edit.idioma`, padrão `pt`) |
| `--transicoes variadas\|nenhuma\|zoom,flash,...` | quais transições usar entre os planos (veja [Transições](#transições)) |
| `--sem-ia`, `--so-planejar`, `--prontos` | como no painel |

`python -m cortes edit-render <plano.json> [--prontos] [--previa]` renderiza de novo um plano existente (`--previa`: em 540 px e rápido, em `previa.mp4`).

`python -m cortes edit <filme> <musica>` aceita um endereço do YouTube no lugar de cada arquivo, com
`--qualidade-filme 1080|720|480|melhor` e `--qualidade-musica melhor|192|128`.

`python -m cortes baixar-youtube <url> [--audio] [--qualidade q]` só baixa (código em `cortes/youtube.py`) e termina
com a linha `Arquivo: <caminho>`, que o `trabalho.comecar_comando` guarda em `resultado`.

## Arquitetura em duas etapas

```
planejar(filme, musica)  ──►  plano.json  ──►  renderizar(plano.json)  ──►  edit.mp4 + edit.txt
     (análise + escolhas)     (a timeline,        (só ffmpeg)
                               editável à mão)
```

O `plano.json` separa o que custa caro (detectar cenas, Whisper, IA) do render. Para trocar um plano, mexer no gancho
ou no drop, edite o JSON e rode `python -m cortes edit-render <plano.json>`.

## Módulos

| Módulo | Faz |
|---|---|
| `batidas.py` | `preparar` (wav, slowed com `asetrate` + reverb com `aecho`); `analisar` (BPM, batidas, energia por batida); `achar_drop`; `cortes_na_batida` |
| `cenas.py` | `tarja` (área sem as faixas pretas do cinemascope); `detectar` (cortes de câmera pela nota de cena de cada quadro, em `_escolher_cortes`); `miniaturas` (uma por plano, já no recorte vertical, mais o brilho médio); `folhas` (grades 6x5 numeradas para a IA); `candidatas` |
| `transcrever.py` | `Transcritor.transcrever(..., idioma, vad)`: o edit usa `vad=False` e descarta os segmentos inventados (`_inventado`) |
| `ia_edit.py` | uma chamada ao Claude com a transcrição (`[segundo] frase`), a lista dos planos com o tempo de cada um e as folhas como imagens; devolve `PlanoIA` (gancho, planos em ordem, `duracao_musica` e `drop_no_filme` quando o tema pede, título, hashtags, motivo) |
| `edit.py` | `planejar`, `montar_cortes`, `renderizar`, `copiar_para_prontos` e a configuração (`PADRAO` + seção `edit:` do config) |
| `legendas.py` | `gerar_ass_edit`: duas camadas do mesmo texto (embaixo, borda grossa desfocada na cor; em cima, letra clara) |

### Batidas sem librosa

Feito só com numpy (Ellis 2007, o mesmo método da librosa): envelope de ataques pelo fluxo espectral, andamento pela
autocorrelação (puxado para perto de 120 BPM) e batidas por programação dinâmica. `LATENCIA` foi calibrada com cliques
e bumbos sintéticos (erro abaixo de 5 ms). O drop é a batida em que a média de volume das 8 seguintes mais sobe em
relação às 8 anteriores, com música suficiente antes (para o gancho) e depois (para a parte da música).

### Como o plano é montado (`edit.planejar`)

1. Música → `musica.wav` tratado → batidas.
2. Filme (`analisar_filme`) → tarja, cenas e transcrição (Whisper em blocos de 600 s), **em cache** por trecho:
   - **Tarja** (`cenas.tarja`): clipe de filme no YouTube vem 2,39:1 dentro de um 16:9. O `cropdetect` mede 12 pontos
     e fica com a mediana de cada borda (uma cena escura parece ter tarja maior; a tela final do clipe, nenhuma). A
     área vai para o `plano.json` (`tarja`) e todo recorte (detecção, miniaturas, render) começa por ela. Sem isso o
     edit saía com as faixas pretas dentro da imagem.
   - **Cortes de câmera** (`cenas.detectar`): a nota de cena (0–1) de cada quadro, sem a tarja. Nota ≥ 0,3 é corte.
     Em cena escura o corte dá 0,1–0,2 (em Ultimato, o limiar fixo de 0,3 achou 2 cortes em 3 minutos), então também
     conta um pico ≥ 0,1 que seja o maior em 0,2 s e 3x acima do 80º percentil de 1 s em volta. Movimento de câmera
     dá nota alta por vários quadros seguidos e não passa. Em luta, cerca de um terço dos cortes fracos é movimento
     rápido ou explosão; isso só divide um plano em dois, o que não aparece no edit.
   - **Falas** (`transcrever`, `vad=False`): o filtro de voz (Silero) não reconhece diálogo misturado com trilha e
     efeitos. No "I am Iron Man" ele não achou nada nem no limiar 0,05, e a transcrição vazia deixava o edit sem
     gancho e a IA sem o que ler (o título saía do nome do arquivo). Sem o filtro, o Whisper ouve tudo; os segmentos
     inventados saem por `_inventado`: as regras do Whisper (pouca chance de fala com pouca confiança; texto
     repetitivo), frases fantasmas ("Thank you.", "inscreva-se", "Amara.org") e descrições de som em maiúsculas ou
     entre colchetes. Custa ~25 s por 10 min de filme na GPU, uma vez (fica em cache).
3. Miniaturas dos planos longos o bastante (o pior caso é o corte mais longo a 0,5x), com o brilho gravado no cache.
4. Gancho: manual (`--gancho`) > IA > heurística (o trecho de fala mais denso). `_encaixar_gancho` ajusta o gancho às
   palavras sem cortar nenhuma no meio. A duração é arredondada para quadros inteiros (30 fps). Se a IA devolve um
   gancho sem fala (ela responde 0–0 quando a transcrição vem vazia), vale a heurística. **Sem fala nenhuma não há
   gancho**: o `plano.json` fica com `gancho.inicio == gancho.fim` e o edit abre direto no drop, com a música cheia.
   Com tema, o gancho pode ir até `gancho_longo` (40 s): o prompt diz à IA que só passe de `gancho_max` quando o
   tema pedir a conversa ou a cena inteira.
5. Duração da música: `--duracao` (ou o campo) > `duracao_musica` da IA (só quando o tema pede; 5 a 60 s, já
   descontado o gancho) > config. Com tema e sem duração à mão, a IA recebe planos para até 60 s.
6. Drop: manual (`--drop`) ou `achar_drop`. Pontos de corte: a cada k batidas a partir do drop, com k escolhido para
   cada plano durar entre `corte_min` e `corte_max`.
7. **Drop no filme** (`--drop-filme` > `drop_no_filme` da IA): o primeiro corte começa exatamente nesse segundo do
   filme (mesmo passando do fim do plano, pela continuidade) e entra no zoom, não no flash, porque o momento já é o
   impacto. Se o filme ali é só clarão ou tela escura (`cenas.imagem_util`: o estalo de Ultimato é 3 s de branco),
   esse pedaço não entra: a música abre com o primeiro plano da IA, também com zoom, e o branco não aparece. O gancho termina ali (`_gancho_ate`): estica até ele se a fala acabou antes, corta as palavras que viriam
   depois. A IA recebe o tempo de cada plano, porque um momento como o estalo pode parecer um plano em branco na
   miniatura.
   - **Fala do gatilho** (`--fala-drop` > `fala_drop_fim` da IA, até 8 s depois do drop) e quando o drop cai em
     relação a ela (`--drop-fala` > `drop_na_fala` da IA, só se o tema disser > `edit.drop_fala`):
     - `depois` (padrão): a fala entra no fim do gancho, limpa, sem música, e o drop vai para 0,25 s depois dela
       (`_gancho_ate` estica o gancho e pega as palavras do caminho). Com o drop junto da frase, a música por cima
       deixava o "A mim, meus X-Men" quase inaudível.
     - `durante`: o primeiro corte junta batidas até cobrir a frase e roda na velocidade 1, para o som bater com a
       boca; o `plano.json` ganha `fala_drop` (início, fim e palavras), que o render toca por cima da música, com
       legenda, e a música fica em `ABAFA` (30%) até a frase acabar, subindo em 0,4 s.
     Se o momento do drop é um clarão e não entra, a fala do modo `durante` também não.
   - **Ritmo** (`--ritmo` > `ritmo` da IA > `edit.ritmo`): troca `corte_min`/`corte_max` por `RITMOS`. Com tema, a
     IA recebe planos para o pior caso (ritmo rápido, até 60 s, no máximo 80).
   - **Abertura** (`--abertura sim|nao` > `abertura` da IA > `edit.abertura`): 2 a 4 **falas do filme** antes do
     gancho, cada uma com o som e a legenda originais, emendadas em corte seco, **sem música**: como o começo de um
     trailer ("A hora chegou." / "Agrupem-se."), para criar expectativa. A IA devolve o início e o fim de cada fala;
     `_abertura_falas` ajusta cada uma às palavras (como o gancho, até 8 s), descarta a que encosta no gancho e para
     em 15 s no total. Pedida à mão sem a IA, entram as 3 últimas frases antes do gancho. O que a abertura mostrou
     não volta depois do drop. Com abertura, a música só entra no drop.
     (Uma primeira versão fazia a abertura com planos cortados na batida da música; isso enchia o começo de
     música, o contrário de criar expectativa, e saiu. O `plano.json` dela tinha `abertura`, que o render ignora.)
8. Planos: os da IA (sem repetidos), depois os da heurística como reserva. `montar_cortes` casa cada intervalo com
   um plano: se o plano for curto para a câmera lenta pedida, fica mais lento (até 0,5x); se nem assim couber, passa
   para o próximo. Cada uso guarda o pedaço do plano que foi usado: um plano longo volta para o fim da fila e, se usado
   de novo, pega outro pedaço, nunca a mesma imagem. O trecho do gancho conta como usado, então o plano do gancho só
   aparece depois do drop com um pedaço que o gancho não mostrou.
9. Efeitos por corte (`_efeito`): o primeiro, no drop, leva zoom de impacto e tremida; os demais alternam impacto e
   aproximação lenta, com tremida a cada 4.
10. Transição de entrada de cada corte (`_transicao`), entre as permitidas em `edit.transicoes`: o drop entra no
   **flash**; a **fusão** vai a cada 3 cortes, só nos de 1 s ou mais e só se o plano anterior tiver filme sobrando
   depois do trecho usado (a fusão o estica 8 quadros); **flash** a cada 8; o resto alterna zoom, chicote, zoom, giro.

### `plano.json`

```json
{"filme": "D:/filmes/X.mkv", "musica": "dados/edits/X/Musica/musica.wav", "bpm": 85.2,
 "drop": 23.65, "musica_inicio": 18.85, "tarja": [1920, 804, 0, 138],
 "gancho": {"inicio": 4990.1, "fim": 4994.9, "palavras": [{"w": "Você", "s": 4990.2, "e": 4990.5}]},
 "cortes": [{"cena": 412, "fonte": 3021.4, "dur": 1.416, "vel": 0.85, "saida": 4.8,
             "zoom": "soco|empurra", "tremer": true, "transicao": "zoom|flash|chicote|giro|fusao|corte"}],
 "duracao": 20.3, "titulo": "...", "descricao": "...", "hashtags": ["edit", "..."],
 "ia": {...}, "estilo": {"proporcao": "4:5", "volume_gancho": 0.18, "legenda_cor": "FF1E3C", "legenda_y": 1130, "cor": {...}}}
```

- `drop_filme`: o segundo do filme que caiu no drop, ou `null`. `gatilho`: o que foi pedido (`momento`, `fala_fim`,
  `modo`), antes do modo "depois" mover o drop para o fim da fala; é o que a tela de ajuste mostra.
- `tema`, `config` (a seção `edit:` usada) e `analise` (os caches de planos e falas): para o ajuste refazer o plano.
- `cortes_editados`: algum corte foi mudado à mão na aba Cortes (ajustar o drop refaz os cortes e tira a marca).
- `ritmo`: o ritmo usado. `abertura_falas`: as falas antes do gancho (`inicio`, `fim`, `palavras`, como o gancho);
  `abertura_dur`: quanto elas duram juntas. Com abertura, o gancho começa em `abertura_dur` e o `saida` dos cortes da
  música já soma abertura + gancho.
- `fala_drop`: `{"inicio", "fim", "palavras"}` da fala que toca por cima do drop, ou `null`.
- `tarja`: área com imagem `[largura, altura, x, y]` (sem as faixas pretas), ou `null`. Planos antigos não têm.
- `fonte`: segundo do filme onde o plano começa; `dur`: duração **na saída**; `vel`: velocidade (o trecho usado do
  filme tem `dur * vel` segundos); `saida`: onde o corte entra no edit.
- `transicao`: como se entra naquele corte (mexe no fim do plano anterior e no começo deste). Pode ser trocada à mão
  antes do `edit-render`. Planos antigos, sem o campo, usam `flash: true` → flash e o resto → corte seco.
- `musica_inicio = drop - duração do gancho`: o drop cai exatamente no fim do gancho. Sem gancho (`inicio == fim`),
  o render não usa a entrada do gancho nem a fala, e o primeiro corte entra pela transição dele (o flash). Se der negativo, a música entra
  com atraso (`adelay`).

### Render (`edit.renderizar`)

Um único comando do ffmpeg, com uma entrada por plano (`-ss` antes do `-i`, porque `trim` num filme de 2 h decodificaria
desde o começo). Cada plano passa por:

`setpts` (câmera lenta) → `fps=30` → recorte central na proporção → `scale` para o **dobro** → `rotate` (só no giro)
→ `zoompan` (zoom, tremida e o movimento das transições; no dobro, o zoom lento não treme) → `trim=end_frame` (quadros
exatos, para não acumular erro) → borrão das transições → `fade` branco (flash).

O grafo de filtros vai para o ffmpeg num arquivo (`edit.filtro.txt`, apagado no fim) com `-/filter_complex`
(o `-filter_complex_script` não existe mais no ffmpeg 9). Com as transições, cada plano soma uns 1.000 caracteres ao
grafo, e com 40 cortes ou mais a linha de comando passava do limite de 32.767 caracteres do Windows (`WinError 206`).

Depois os planos são emendados um a um: `concat` nos cortes e `xfade` na fusão. Por fim, cor (`eq`, `colorbalance`, `vignette`, `noise`), `pad` para 1920 e `subtitles`. No áudio: a fala do
gancho com fade e `apad`, mais a música com o volume subindo no drop (`volume=...:eval=frame`), `amix` e `alimiter`.
Com `estilo.musica_no_gancho: false`, a música começa no próprio drop (`-ss drop`) com `adelay` do tamanho do gancho
e 15 ms de entrada: o gancho fica só com o som do filme e o drop entra de uma vez. Planos sem a chave tocam a música
baixinha, como antes.

A linha do tempo do render é uma lista de trechos (falas da abertura, gancho, cortes da música), cada um com a sua
entrada. Fala e gancho são trechos do filme com som, na velocidade 1; corte é um plano mudo, com câmera lenta. No
áudio entram, conforme o plano: o som de cada fala da abertura e do gancho (cada um com `adelay` até o seu lugar), a
música (do drop em diante, quando há abertura) e a fala do drop (`-ss fala_drop.inicio`, `volume=1.3`, `adelay` até o
drop). A legenda é uma só (`gancho.ass`), com as palavras da abertura, do gancho e da fala do drop no tempo do vídeo.

Emendas do som: a imagem das falas corta seco, mas o som de cada trecho segue `CAUDA` (0,3 s) por baixo do seguinte,
sumindo, enquanto o seguinte entra em 80 ms. Antes cada fala sumia 0,25 s antes do corte e o som caía a -40 dB em cada
emenda. Quando a fala do drop continua o gancho no filme (o mesmo segundo), não há cauda nem fade entre os dois.
`_encaixar_gancho` também completa a frase: se a palavra seguinte vem colada (menos de 0,35 s) e a frase não terminou
(sem `.`, `!` ou `?`), ela entra ("E lutem" vira "E lutem juntos.").

Volume da música: `_ganho_musica` mede o RMS da música depois do drop e a leva a `MUSICA_DB` (-15 dB), uns 5 dB
acima do diálogo de filme (~-20 dB), vezes `estilo.volume_musica`. Música de edit vem masterizada a -5/-8 dB e
engolia a fala; planos antigos também passam a ser nivelados ao renderizar de novo.
A saída é limitada a 16 Mbps, porque o grão animado com CRF baixo passava de 30 Mbps. O vídeo termina escurecendo
(0,4 s).

### Transições

Tiradas de edits de referência (zoom com borrão na troca é o mais comum; flash, giro e fusão aparecem nos momentos
fortes ou lentos). Cada uma mexe nos **últimos 4 quadros** do plano que sai (o "rabo") e no **começo** do que entra
(a "cabeça", 0,22 a 0,3 s). Os números ficam nas tabelas `CABECA` e `RABO` de `edit.py`.

| Transição | Plano que sai | Plano que entra |
|---|---|---|
| `zoom` | acelera para dentro (+28%) com borrão | chega apertado (+30%) e desfocado e solta |
| `flash` | aproxima e estoura no branco nos 3 últimos quadros | sai do branco em 0,25 s |
| `chicote` | a câmera corre para o lado, com borrão horizontal (`dblur`) | continua o movimento e para |
| `giro` | gira 8° e aproxima | chega girado 12°, apertado e desfocado, e se endireita |
| `fusao` | fica 8 quadros mais longo e se mistura (`xfade`) | aparece por baixo, a partir da batida |
| `corte` | — | corte seco (o soco de zoom do plano continua) |

Como funciona:

- O borrão é o mesmo filtro (`gblur`, ou `dblur` no chicote) repetido com força diferente em cada quadro, ligado por
  `enable='eq(n,K)'`.
- O chicote anda dentro da folga que o zoom extra abre (90% dela). O `zoompan` prende o recorte dentro da imagem.
- O giro roda a imagem antes do `zoompan`, com cantos pretos. O zoom extra é maior que o necessário para escondê-los
  (`cos θ + max(L/A, A/L)·sen θ`, que dá 1,36 a 12° no 9:16).
- O `xfade` da fusão usa `offset` meio quadro antes da batida. O xfade só começa no primeiro quadro com tempo maior
  ou igual ao offset, e com o offset exato o arredondamento atrasava todos os cortes seguintes em um quadro. O
  `teste_edit.py` confere que os cortes secos depois de uma fusão caem no quadro da batida.

## Pastas

```
dados/edits/_youtube/               o que foi baixado do YouTube (<título> [<id>][ [qualidade]].mp4|mp3)
dados/edits/<filme>/
├── tarja_<ini>_<fim>.json          área sem as faixas pretas ([] = sem tarja)
├── planos_<ini>_<fim>.json         planos do filme (com brilho), em cache
├── falas_<ini>_<fim>_<idioma>.json palavras do Whisper, em cache
├── miniaturas_<ini>_<fim>/<id>.jpg uma por plano (os números mudam de um trecho para outro)
└── <musica>[_2, _3…]/              um edit por pasta (um edit novo nunca sobrescreve o anterior)

    ├── musica.wav, batidas.json, folhas/folha_NN.jpg, plano.json, gancho.ass
    ├── plano.anterior.json, previa.mp4     do ajuste no painel
    └── edit.mp4, edit.txt
```

Os `cenas_*.json`, `transcricao_*.json` e `miniaturas/` de antes ficam esquecidos: vinham do detector que perdia
cortes e do Whisper com filtro de voz. Podem ser apagados.

`--prontos` (ou o botão do painel) copia `edit.mp4` e `edit.txt` para `prontos/` como `edit_<filme>_<musica>.*`. Sem
isso, nada vai para lá. `dados/edits/pastas.json` guarda a última pasta do filme e da música, para o seletor do painel.

## Limitações conhecidas

- O idioma da transcrição é o `edit.idioma` (ou `--idioma`), passado ao Whisper; `auto` deixa ele detectar pelos
  primeiros 30 s com voz de cada bloco de 600 s. Com fala clara, o `large-v3-turbo` costuma transcrever no idioma
  original mesmo com o idioma errado; o ajuste importa mais em áudio difícil. As lives continuam em português.
- Sem o filtro de voz, sobra alguma frase inventada que as regras não pegam, e gritos em outro idioma viram texto
  sem sentido (na luta de Gulmira, o árabe). A IA costuma ignorar isso ao escolher o gancho.
- O recorte é sempre central, sem acompanhar o rosto: numa cena com duas pessoas, uma pode ficar de fora.
- A detecção de cenas ainda perde dissolvências lentas e marca alguns cortes falsos em ação muito rápida.
- A câmera lenta duplica quadros (`fps`), sem interpolação.
- Filme e música comercial levam Content ID quase sempre.
