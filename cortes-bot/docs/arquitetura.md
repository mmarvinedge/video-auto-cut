# Arquitetura

O cortes-bot roda no Windows, na máquina do usuário, sem servidor externo. São dois produtos sobre a
mesma base:

- **cortes de live**: um VOD da Twitch/Kick vira cortes verticais 1080x1920, revisados e publicados pelo painel;
- **edits de filme**: um filme e uma música (arquivos locais) viram um edit vertical com gancho e cortes na batida.

```
D:\video-auto-cut\
├── .venv\                     ambiente Python (o README do bot explica como criar)
├── docs\                      páginas públicas de privacidade/termos (exigência do TikTok), NÃO é doc de código
├── prontos\                   vídeos aprovados + legenda .txt, para publicar à mão
└── cortes-bot\
    ├── config.yaml            toda a configuração (comentada)
    ├── iniciar_painel.pyw     sobe o painel escondido ao entrar no Windows
    ├── cortes\                o pacote (python -m cortes ...)
    ├── docs\                  esta documentação
    ├── dados\                 tudo o que é gerado (fora do git)
    ├── segredos\              credenciais OAuth (fora do git)
    ├── demo\                  roteiro do vídeo de demonstração para a revisão do TikTok
    └── tests\                 testes que rodam sem rede e sem contas reais
```

## Ambiente

- Python 3.12 em `D:\video-auto-cut\.venv`. Os comandos rodam de dentro de `cortes-bot`:
  `..\.venv\Scripts\python -m cortes <comando>`. O `python` do PATH **não** tem as dependências.
- ffmpeg: o binário do pacote `imageio-ffmpeg` (`config.ffmpeg()`). Não existe `ffprobe`: duração e
  resolução são lidas do stderr de `ffmpeg -i` (veja `cenas.duracao`, `painel.ficha`).
- GPU NVIDIA (CUDA 12 via pip) para o Whisper; sem ela, cai para CPU.
- IA: `ANTHROPIC_API_KEY` no ambiente. Sem ela, tudo funciona, só que sem a etapa de IA.

## Pastas de dados

`pasta_dados` no config (padrão `dados/`, relativo a `cortes-bot`):

```
dados/
├── <canal>/                       um por streamer do config
│   ├── vods/                      áudio/vídeo do VOD + .info.json do yt-dlp
│   │   └── trechos/               pedaços de vídeo baixados só para renderizar cada corte (*_bruto.mp4)
│   ├── chat/                      chat em .jsonl, uma mensagem por linha
│   ├── candidatos/<vod>.json      resultado do processamento: candidatos, longos, compilações e revisão
│   ├── cortes/curtos|tiktok|partes/  os mp4 renderizados
│   ├── enquadramento.json         enquadramento do canal
│   └── enquadramento/             enquadramento por VOD e por corte
├── edits/<filme>/                 edits de filme (veja edits.md)
├── _publicacao/                   contas.json, fila.json e tokens/ (NUNCA versionar)
└── painel.log                     saída do painel quando ele sobe escondido
```

## Configuração

`config.yaml`, lido por `config.carregar()` **a cada uso** (não há cache): editar o arquivo vale na
próxima ação, sem reiniciar o painel. Seções: `corte`, `tiktok`, `deteccao`, `whisper`, `ia`, `edit`,
`publicacao`, `canais`, `kick_api`.

- O enquadramento escolhido na tela **não** é gravado no config. Ele fica em `dados/<canal>/enquadramento*.json`,
  e `config.canal()`/`enquadrar.aplicar()` o aplicam por cima. Assim o config escrito à mão, com os
  comentários, nunca é reescrito.
- A única escrita no config é `config.adicionar_canal()` (botão "+ Novo streamer"), que **acrescenta
  texto** ao fim da seção `canais:` em vez de regravar o YAML.

## Linha de comando

`cortes/__main__.py`. Cada subcomando é um `cmd_<nome>(cfg, a)` registrado em `main()` com argparse.

| Comando | O que faz |
|---|---|
| `vods <canal>` | lista os últimos VODs |
| `baixar` / `baixar-audio <canal> <url>` | baixa o VOD inteiro ou só o áudio (bem mais leve; basta para processar) |
| `chat-twitch` | grava o chat ao vivo de todos os canais Twitch (IRC anônimo) |
| `chat-vod <canal> <url>` | baixa o chat de um VOD da Twitch já encerrado |
| `kick-assinar` / `kick-webhook` | chat do Kick pela API oficial (webhook) |
| `processar <canal> <video>` | gera os cortes (veja cortes-de-live.md) |
| `painel` | abre o painel em http://localhost:8800 |
| `enquadrar <canal> <video>` | ferramenta de enquadramento avulsa (porta 8810) |
| `edit <filme> <musica>` / `edit-render <plano.json>` | edits de filme (veja edits.md) |

**Para criar um comando**: escreva `cmd_x(cfg, a)`, registre em `main()` e acrescente uma linha na
docstring do topo do arquivo. Imports pesados (Whisper, anthropic, módulos do painel) ficam **dentro**
da função, para os outros comandos não pagarem o tempo de carga. Se o painel for disparar o comando,
imprima o progresso como `N/M` (veja [painel.md](painel.md#trabalhos-em-segundo-plano)).

## Convenções do código

- **Português** em nomes, mensagens e comentários. Os comentários explicam o *porquê* (o problema que
  apareceu), não o quê.
- **Caminhos nos .json**: `config.relativo()` para gravar (relativo a `cortes-bot`) e `config.absoluto()` para ler.
  Assim a pasta pode mudar de lugar.
- **Gravar sem corromper**: escreva em `.tmp` e troque com `replace()`. Vale para os JSON e para os mp4: um
  re-render que falha não pode apagar o corte bom (`render.renderizar`, `edit.renderizar`).
- **Render vazio**: um intervalo fora do arquivo não é erro para o ffmpeg, que sai com sucesso e escreve um mp4
  sem quadros. Confira o tamanho com `render.MINIMO_BYTES`.
- **Filtros do ffmpeg no Windows**: o `subtitles=` não aceita `C:\...`. Rode o ffmpeg com `cwd` na pasta da legenda
  e passe só o nome do arquivo. Dentro de valores entre aspas simples (`z='...'`), a vírgula **não** leva `\`.
- **`-frames:v` vale por saída**: num comando com duas saídas, repita-o em cada uma, senão a segunda decodifica o
  arquivo até o fim (`cenas.miniatura`).
- **Encoding**: processos filhos rodam com `PYTHONIOENCODING=utf-8` (`trabalho._rodar`). Sem isso, acentos viram `�`
  e um emoji derruba o processo.
- **Concorrência**: os JSON compartilhados são gravados sob uma trava (`painel._trava`, `fila._trava`, `contas._trava`).

## Testes

Scripts soltos, sem pytest. Rode de dentro de `cortes-bot`, com o Python do `.venv`:

| Teste | Cobre |
|---|---|
| `tests/teste_sintetico.py` | live falsa de 10 min: detecção, IA simulada, compilações, render 1080x1920 |
| `tests/teste_publicacao.py` | fila, YouTube e simulação, com respostas simuladas |
| `tests/teste_tiktok.py` | vínculo e envio ao TikTok, com respostas simuladas |
| `tests/teste_edit.py` | edits: batidas, drop, cortes de câmera e render, com música e filme sintéticos |
| `tests/teste_leitor_resposta.mjs` | leitor da resposta colada de outro chat (`node tests/teste_leitor_resposta.mjs`) |
