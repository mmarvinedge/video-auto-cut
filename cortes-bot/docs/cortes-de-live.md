# Cortes de live

Um VOD da Twitch ou do Kick vira três tipos de vídeo vertical 1080x1920:

| Formato | Duração | Lista no JSON | Pasta |
|---|---|---|---|
| curto (Shorts/Reels) | 20–60 s (`corte:`) | `candidatos` | `cortes/curtos/` |
| longo (TikTok, que só monetiza acima de 1 min) | 65–120 s (`tiktok:`) | `longos` | `cortes/tiktok/` |
| compilação (2–4 curtos do mesmo tema) | 65–120 s | `compilacoes` | `cortes/tiktok/` |

Comando: `python -m cortes processar <canal> <video>` (`cmd_processar` em `__main__.py`).
Pelo painel: aba **Lives** → **Processar**, que roda `baixar-audio` e depois `processar` (veja painel.md).

A lista de VODs (`vod.listar`, via `trabalho.vods`) mostra quando cada live começou e marca as que já viraram cortes,
para não processar a mesma duas vezes:

- **Data**: o `yt-dlp --flat-playlist` traz o `timestamp` no Kick, mas não na Twitch nem no YouTube. Na Twitch as datas
  vêm numa consulta só ao gql (`vod._datas_twitch`, o mesmo endereço e client-id do chat dos VODs), com um apelido por
  VOD. No YouTube, o `--extractor-args youtubetab:approximate_date` faz o yt-dlp estimar a data pelo "há 2 dias" da
  página (só o dia). Sem resposta, a lista sai sem a data ("data desconhecida"), sem quebrar.
- **Já processada**: existe `dados/<canal>/candidatos/<id do VOD>_audio.json` (ou `<id>.json`). É olhado a cada pedido,
  fora do cache da lista, então uma live processada agora já aparece marcada.

## Fluxo

```
baixar-audio ──► detect (áudio + chat) ──► Whisper nos candidatos ──► IA ──► render de cada corte
  (vod.py/hls.py)   (detect.py)              (transcrever.py, fala.py)  (ia.py)  (baixa o trecho de vídeo,
                                                                                 legendas.py, render.py)
```

### 1. Download (`vod.py`, `hls.py`)

- `vod.baixar_audio` baixa **só o áudio** da live inteira (cerca de 15x menor que o vídeo em 720p), com o
  `hls.py` baixando os pedaços HLS em paralelo (em sequência, levaria horas). O `.info.json` do yt-dlp ao
  lado guarda a URL e o horário de início (`vod.inicio_do_vod`, `vod.url_do_vod`).
- O vídeo é baixado **só nos trechos que viram corte**: `vod.baixar_trecho(url, ini, fim, destino)` grava
  `vods/trechos/<corte>_bruto.mp4` e devolve em que segundo do VOD o arquivo começa. Esse valor fica no
  corte como `trecho_inicio`, porque o re-render precisa dele.
- Armadilha: o `start` do arquivo baixado é o relógio do stream, não o segundo do VOD (no bisteconee ele
  anda ~61 s à frente). Use `trecho_inicio` ou `vod.inicio_do_trecho`.
- URLs do Kick vêm do yt-dlp com `#__youtubedl_smuggle=...`. Passe por `vod.limpar_url` antes de validar.

### 2. Detecção

`detect.serie_nota` monta uma nota por segundo:

- **áudio**: volume em janelas de `deteccao.janela` segundos;
- **chat** (se cobrir o VOD com pelo menos 1 mensagem por minuto): quantidade de mensagens, com peso extra
  para `palavras_reacao` e `regex_risada`, deslocada por `atraso_chat`.

Cada sinal é normalizado contra o "normal" da própria live (mediana móvel de `baseline` segundos + desvio
robusto) e combinado com `peso_chat`/`peso_audio`.

- `detect.candidatos`: picos acima de `nota_minima`, estendidos enquanto a nota fica acima da metade do pico,
  com `margem_antes`/`margem_depois` e sem sobreposição.
- `detect.candidatos_longos`: janelas de `janela_longa` segundos com média alta (atividade **sustentada**).

O chat vem de `dados/<canal>/chat/*.jsonl` (`{"ts", "user", "text"}`), gravado por `chat-twitch` (ao vivo),
`chat-vod` (VOD já encerrado da Twitch, via gql.twitch.tv, que não é documentado) ou `kick-webhook`.

### 3. Fala (`transcrever.py`, `fala.py`)

`Transcritor(modelo, dispositivo)` (faster-whisper, `large-v3-turbo` por padrão) transcreve cada candidato
com 6 s de folga. As palavras ficam no corte como `palavras: [{"w", "s", "e"}]`, em segundos absolutos do VOD.

- `fala.ajustar_bordas`: o corte não começa nem termina no meio de uma frase;
- `fala.nota_fala`: pontua as `reacoes` faladas, exclamações e ritmo;
- a nota final é `zscore(sinal) + peso_fala * zscore(fala)` (`__main__.ouvir`).

### 4. IA (`ia.py`)

**Uma chamada por live** com todos os candidatos, para a IA comparar os momentos entre si (`ia.avaliar`).
Ela aprova ou reprova cada um, dá nota de 0 a 10, apara as bordas, escreve título, descrição e hashtags, e
sugere compilações. `ia.aplicar` grava em `c["ia"]` e reordena; `ia.montar_compilacoes` valida as compilações
(só aprovados, sem repetir, duração certa).

- Modelo em `ia.MODELO`. Saída estruturada com pydantic (`messages.parse`).
- Hashtags: `HASHTAGS_FIXAS` sempre primeiro, até `MAX_HASHTAGS` (`ia.hashtags_finais`).
- Sem credencial ou com erro de API, o processamento **segue sem IA** (`__main__.avaliar_com_ia`), e a
  compilação vira automática (`compilacao_automatica`).
- Legenda avulsa de um corte: `ia.legenda_para` (botão "Gerar com IA") ou `ia.prompt_avulso` (botão
  "Copiar prompt", para colar em qualquer chat).

### 5. Render

`__main__.renderizar_trecho` → `render.renderizar(fonte, ini, fim, destino, canal, legenda)`:

- **com facecam**: a cam em cima na largura inteira, uma faixa preta no meio (onde fica a legenda) e o jogo
  embaixo. O recorte foge da própria cam para o rosto não aparecer duas vezes (`render._layout`);
- **sem facecam**: o vídeo inteiro centralizado sobre um fundo desfocado dele mesmo;
- o crédito do streamer (`credito`) fica sempre na tela;
- `render.fracao_parada` descarta cortes com mais de `max_tela_parada` de imagem congelada (tela de pausa).

Legenda: `legendas.gerar_ass` gera um `.ass` estilo Shorts, com 3 palavras por vez, em maiúsculas e com a
palavra falada em amarelo. Fica no meio da faixa preta (`render.posicao_legenda`).

Compilações: `render.concatenar` junta os mp4 já renderizados das partes.

## Resultado

`dados/<canal>/candidatos/<vod>.json`:

```json
{"video": "dados/alanzoka/vods/v123_audio.mp4", "canal": "alanzoka", "duracao": 21000, "usou_chat": true,
 "candidatos": [{"id": "c0", "inicio": 4210, "fim": 4250, "nota": 3.1, "palavras": [...], "texto": "...",
                 "ia": {...}, "arquivo": "dados/alanzoka/cortes/curtos/v123_01_4210.mp4", "trecho_inicio": 4205.2,
                 "revisao": {"status": "aprovado", "titulo": "...", "hashtags": [...], "capa_t": 3.2, "exportado": "..."}}],
 "longos": [...], "compilacoes": [{"partes": ["c0", "c3"], "arquivo": "...", "ia": {...}}]}
```

`revisao` é escrito pelo painel. O resto vem do processamento. O id que o painel usa para um corte é
`<canal>/<vod>/<lista>/<índice>` (`painel._localizar`).

## Como estender

- **Novo sinal na detecção**: gere uma série por segundo em `detect.py`, normalize com `_normalizar` e some em
  `serie_nota` com um peso novo em `deteccao:`.
- **Novo layout**: `render._filtro` (o filtro do ffmpeg) e `render._layout` (as medidas). O re-render do painel
  usa a mesma função, então não há segundo lugar para mudar.
- **Novo formato de saída**: acrescente uma lista no JSON e registre em `painel.LISTAS` para aparecer na Revisão.
