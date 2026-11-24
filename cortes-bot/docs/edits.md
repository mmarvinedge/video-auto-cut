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

1. **Filme** e **Música**: cole o caminho ou clique em **Procurar…**. O seletor navega pelas pastas do computador,
   mostra só vídeos (filme) ou áudios e vídeos (música) e lembra a última pasta usada.
2. **Tema** (opcional): uma dica para a IA, como "o romance do Peter e da Gwen".
3. **Trecho do filme** (opcional): início e fim, em `h:mm:ss` ou segundos. Analisar só uma parte é mais rápido e deixa
   os planos mais coerentes com o gancho.
4. **Ajustes finos** (recolhidos): formato (4:5 ou 9:16), velocidade da música (original até 0,8×), duração da parte da
   música, drop e gancho à mão. Em branco valem os padrões do `edit:` do `config.yaml`, que aparecem nos campos.
5. Opções: **sem IA**, **só planejar** (grava o `plano.json` sem renderizar) e **copiar para a pasta de prontos**.
6. **Criar edit**: o andamento aparece na caixa do trabalho (um trabalho por vez, compartilhado com a aba Lives). Ao
   terminar, o edit entra na lista.

Cada edit da lista mostra o vídeo, o gancho, o título, a descrição e as hashtags (editáveis: salvam no `plano.json` e
no `edit.txt`), o motivo da IA e os botões **Renderizar de novo** (depois de editar o `plano.json` à mão) e **Copiar
para prontos**.

O edit roda num processo filho do painel e só usa a IA se a `ANTHROPIC_API_KEY` estiver no ambiente **do painel**.
Como ele sobe sozinho com o Windows, grave a chave como variável de usuário (`setx ANTHROPIC_API_KEY "..."`) e rode
`iniciar_painel.pyw --reiniciar`. Sem a chave, o formulário mostra um aviso.

## Pelo comando

| Opção | Faz |
|---|---|
| `--tema "..."` | dica para a IA |
| `--trecho 1:10:00-1:40:00` | analisa só essa parte do filme |
| `--gancho 1:23:10-1:23:19` | fala de gancho escolhida à mão (tempo do filme) |
| `--drop 41.2` | segundo da música, já tratada, onde os cortes começam |
| `--proporcao 4:5\|9:16`, `--slowed 0.85`, `--duracao 15` | sobrepõem a seção `edit:` do config só neste edit |
| `--sem-ia`, `--so-planejar`, `--prontos` | como no painel |

`python -m cortes edit-render <plano.json> [--prontos]` renderiza de novo um plano existente.

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
| `cenas.py` | `detectar` (cortes de câmera com `select=gt(scene,0.3)`); `miniaturas` (uma por plano, já no recorte vertical, mais o brilho médio); `folhas` (grades 6x5 numeradas para a IA); `candidatas` |
| `ia_edit.py` | uma chamada ao Claude com a transcrição (`[segundo] frase`) e as folhas como imagens; devolve `PlanoIA` (gancho, planos em ordem, título, hashtags, motivo) |
| `edit.py` | `planejar`, `montar_cortes`, `renderizar`, `copiar_para_prontos` e a configuração (`PADRAO` + seção `edit:` do config) |
| `legendas.py` | `gerar_ass_edit`: duas camadas do mesmo texto (embaixo, borda grossa desfocada na cor; em cima, letra clara) |

### Batidas sem librosa

Feito só com numpy (Ellis 2007, o mesmo método da librosa): envelope de ataques pelo fluxo espectral, andamento pela
autocorrelação (puxado para perto de 120 BPM) e batidas por programação dinâmica. `LATENCIA` foi calibrada com cliques
e bumbos sintéticos (erro abaixo de 5 ms). O drop é a batida em que a média de volume das 8 seguintes mais sobe em
relação às 8 anteriores, com música suficiente antes (para o gancho) e depois (para a parte da música).

### Como o plano é montado (`edit.planejar`)

1. Música → `musica.wav` tratado → batidas.
2. Filme → cenas e transcrição (Whisper em blocos de 600 s), **em cache** por trecho.
3. Miniaturas dos planos longos o bastante (o pior caso é o corte mais longo a 0,5x), com o brilho gravado no cache.
4. Gancho: manual (`--gancho`) > IA > heurística (o trecho de fala mais denso). `_encaixar_gancho` ajusta o gancho às
   palavras sem cortar nenhuma no meio. A duração é arredondada para quadros inteiros (30 fps).
5. Drop: manual (`--drop`) ou `achar_drop`. Pontos de corte: a cada k batidas a partir do drop, com k escolhido para
   cada plano durar entre `corte_min` e `corte_max`.
6. Planos: os da IA, depois os da heurística como reserva. `montar_cortes` casa cada intervalo com um plano: se o
   plano for curto para a câmera lenta pedida, fica mais lento (até 0,5x); se nem assim couber, passa para o próximo.
7. Efeitos por corte (`_efeito`): o primeiro, no drop, leva zoom de impacto, tremida e flash; os demais alternam
   impacto e aproximação lenta, com tremida a cada 4 e flash a cada 8.

### `plano.json`

```json
{"filme": "D:/filmes/X.mkv", "musica": "dados/edits/X/Musica/musica.wav", "bpm": 85.2,
 "drop": 23.65, "musica_inicio": 18.85,
 "gancho": {"inicio": 4990.1, "fim": 4994.9, "palavras": [{"w": "Você", "s": 4990.2, "e": 4990.5}]},
 "cortes": [{"cena": 412, "fonte": 3021.4, "dur": 1.416, "vel": 0.85, "saida": 4.8,
             "zoom": "soco|empurra", "tremer": true, "flash": true}],
 "duracao": 20.3, "titulo": "...", "descricao": "...", "hashtags": ["edit", "..."],
 "ia": {...}, "estilo": {"proporcao": "4:5", "volume_gancho": 0.18, "legenda_cor": "FF1E3C", "legenda_y": 1130, "cor": {...}}}
```

- `fonte`: segundo do filme onde o plano começa; `dur`: duração **na saída**; `vel`: velocidade (o trecho usado do
  filme tem `dur * vel` segundos); `saida`: onde o corte entra no edit.
- `musica_inicio = drop - duração do gancho`: o drop cai exatamente no fim do gancho. Se der negativo, a música entra
  com atraso (`adelay`).

### Render (`edit.renderizar`)

Um único comando do ffmpeg, com uma entrada por plano (`-ss` antes do `-i`, porque `trim` num filme de 2 h decodificaria
desde o começo). Cada plano passa por:

`setpts` (câmera lenta) → `fps=30` → recorte central na proporção → `scale` para o **dobro** → `zoompan`
(zoom, tremida; no dobro, o zoom lento não treme) → `trim=end_frame` (quadros exatos, para não acumular erro).

Depois vêm `concat`, cor (`eq`, `colorbalance`, `vignette`, `noise`), `pad` para 1920 e `subtitles`. No áudio: a fala do
gancho com fade e `apad`, mais a música com o volume subindo no drop (`volume=...:eval=frame`), `amix` e `alimiter`.
A saída é limitada a 16 Mbps, porque o grão animado com CRF baixo passava de 30 Mbps.

## Pastas

```
dados/edits/<filme>/
├── cenas_<ini>_<fim>.json          planos do filme (com brilho), em cache
├── transcricao_<ini>_<fim>.json    palavras do Whisper, em cache
├── miniaturas/<id>.jpg             uma por plano
└── <musica>[_2, _3…]/              um edit por pasta (um edit novo nunca sobrescreve o anterior)
    ├── musica.wav, folhas/folha_NN.jpg, plano.json, gancho.ass
    └── edit.mp4, edit.txt
```

`--prontos` (ou o botão do painel) copia `edit.mp4` e `edit.txt` para `prontos/` como `edit_<filme>_<musica>.*`. Sem
isso, nada vai para lá. `dados/edits/pastas.json` guarda a última pasta do filme e da música, para o seletor do painel.

## Limitações conhecidas

- O Whisper está fixo em português (`transcrever.Transcritor`), o que exige áudio dublado.
- O recorte é sempre central, sem acompanhar o rosto: numa cena com duas pessoas, uma pode ficar de fora.
- A detecção de cenas perde cortes entre planos de brilho e cor parecidos (limiar 0,3) e dissolvências lentas.
- A câmera lenta duplica quadros (`fps`), sem interpolação.
- Filme e música comercial levam Content ID quase sempre.
