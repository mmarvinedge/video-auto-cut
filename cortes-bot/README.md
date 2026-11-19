# Bot de cortes — fase 1 (MVP local)

Um canal de destino por streamer: **alanzoka** (Twitch), **paulinholokobr** e **coringa** (Kick).
Configuração em `config.yaml`.

## Instalação

Na pasta `D:\video-auto-cut` (o ambiente fica em `D:\video-auto-cut\.venv`):

```bash
python -m venv .venv
.venv\Scripts\pip install -r cortes-bot\requirements.txt
```

Os comandos abaixo rodam de dentro de `cortes-bot`, com o Python do ambiente:
`..\.venv\Scripts\python -m cortes ...`

Use um caminho curto para o ambiente: o Windows quebra a instalação do pip em caminhos com mais de 260 caracteres.
O ffmpeg vem junto pelo pacote `imageio-ffmpeg`, sem instalar nada no sistema.

## Fluxo

1. **Gravar o chat durante a live** (deixe rodando):
   - Twitch: `python -m cortes chat-twitch` (IRC oficial, anônimo, só leitura)
   - Kick: `python -m cortes kick-assinar` uma vez, e depois `python -m cortes kick-webhook`
     (API oficial: precisa de um app em kick.com/settings/developer + um túnel público até a porta 8787)
2. **Depois da live**, listar os VODs e baixar **só o áudio** (cerca de 600 MB para 7h de live, em cerca de 1 min):
   `python -m cortes vods alanzoka` → `python -m cortes baixar-audio alanzoka <url>`
3. **Processar**: `python -m cortes processar alanzoka dados/alanzoka/vods/<id>_audio.mp4`
   - Detecta até 30 momentos pelo áudio (+ chat, se gravado)
   - **Whisper** transcreve cada um na GPU, dá nota à fala (reações, risadas, exclamações, ritmo),
     ajusta início e fim para não cortar frases no meio e escolhe os 10 melhores
   - Baixa em 1080p **só os trechos** escolhidos e queima **legendas palavra por palavra**
     (na emenda câmera/jogo); a transcrição fica salva no .json para gerar títulos depois
   - `--sem-whisper` pula a transcrição (mais rápido, sem legendas)
   - **IA (Claude)**: lê as transcrições de todos os candidatos juntos, reprova o que não funciona
     sozinho (pedido de like, conversa morta, música de pausa), apara a enrolação do começo/fim e
     escreve título, descrição e hashtags. Uma chamada por live (`--sem-ia` desliga).
     Precisa da variável `ANTHROPIC_API_KEY` (chave em platform.claude.com); sem ela, o bot pula esta etapa.
   - **Duas versões por live** (`--sem-tiktok` gera só a primeira):

     | Versão | Duração | Pasta | Para |
     |---|---|---|---|
     | Curtos | 20–60s, 1 momento | `cortes/curtos/` | YouTube Shorts, Reels |
     | TikTok longo | 65–120s, atividade sustentada | `cortes/tiktok/*_longo_*` | TikTok (monetiza só > 1 min) |
     | TikTok compilação | 65–120s, 2–4 curtos do mesmo tema | `cortes/tiktok/*_compilacao_*` | TikTok |

     Com IA, ela agrupa as compilações por tema e dá título; sem IA, sai uma compilação
     "melhores momentos" com os curtos de maior nota, na ordem da live. Ajustes na seção `tiktok:` do config.
4. **Revisar**: `python -m cortes painel` e abra http://localhost:8800 (filtro por formato)
   - Assista a cada corte, ajuste título/descrição/hashtags e aprove ou rejeite
   - Fica salvo no `.json` da live (campo `revisao`), pronto para a fase de publicação
   - Descarta sozinho as telas de pausa ("volto já" com música), detectando imagem parada
   - Gera `dados/<canal>/candidatos/<id>.json` e os cortes verticais em `dados/<canal>/cortes/`
   - `--sem-render` só lista os momentos, sem baixar nem gerar vídeo (bom para calibrar)
   - Ainda dá para baixar o VOD inteiro com `baixar` (cerca de 20 GB em 1080p) e processar o .mp4 completo

O replay do chat de VODs antigos da Twitch não está disponível (a biblioteca `chat-downloader` trava).
Por isso o chat precisa ser gravado **durante** a live com `chat-twitch`.

5. **Publicar**: ainda no painel, clique em **Aprovar…** num corte. Na janela, escolha as contas
   (as contas padrão do streamer já vêm marcadas) e quando publicar:
   - **Próximo horário livre**: usa `publicacao.horarios` do config (até 4 por dia por conta, um por horário),
     respeitando a cota diária do YouTube
   - **Agora** ou **numa data/hora** específica
   - A aba **Fila** mostra cada envio (agendado → enviando → publicado/erro) com o link do vídeo;
     dá para publicar agora, cancelar ou reagendar
   - **O painel precisa estar aberto** (`python -m cortes painel`) no horário agendado: é ele que publica.
     Se o PC estiver desligado, o que venceu sai assim que o painel abrir de novo.
     Para ele abrir sozinho, sem janela, sempre que você entrar no Windows (veja abaixo)

### Painel sempre aberto, sem janela

```
python iniciar_painel.pyw --instalar     # põe na inicialização do Windows (sem administrador)
python iniciar_painel.pyw --reiniciar    # depois de um git pull: o painel escondido roda o código antigo
python iniciar_painel.pyw --parar        # desliga o painel escondido
python iniciar_painel.pyw --remover      # tira da inicialização
```

Ele sobe pelo `pythonw`, então nenhuma janela aparece, nem a dos ffmpeg/yt-dlp que ele chama. O que o
terminal mostraria vai para `dados/painel.log`. Também dá para desligar em *Configurações >
Aplicativos > Inicialização* ("Painel de cortes"). Se quiser rodar no terminal para ver a saída,
pare o escondido antes, senão a porta 8800 já está ocupada.
   - Cota do YouTube (ou limite diário do TikTok) esgotada → reagenda sozinho para o dia seguinte;
     acesso expirado → a conta fica marcada para "vincular de novo" na aba Contas
   - Com conta do TikTok marcada, a janela pede o modo (rascunho ou direto; veja abaixo)

## Vincular o YouTube (uma vez)

O painel publica pela API oficial do YouTube. Para isso o Google exige uma credencial sua:

1. Entre em https://console.cloud.google.com e crie um projeto (ex.: `cortes-bot`).
2. **APIs e serviços → Biblioteca**: procure **YouTube Data API v3** e clique em **Ativar**.
3. **Google Auth Platform / Tela de permissão OAuth**: tipo **Externo**; preencha nome do app e e-mail.
   Em **Público-alvo**, adicione os e-mails das contas Google dos seus canais como usuários de teste.
   - Em modo **Teste**, o Google expira o acesso a cada **7 dias** (você teria de vincular de novo toda semana).
     Para evitar, mude o status para **Em produção**: sem verificação, o Google só mostra um aviso de
     "app não verificado" no login, o que é suficiente para uso próprio.
4. **Credenciais → Criar credenciais → ID do cliente OAuth → Aplicativo da Web**.
   Em **URIs de redirecionamento autorizados**, coloque exatamente:
   `http://localhost:8800/oauth/youtube/callback`
5. Baixe o JSON e salve como `segredos/youtube_client_secret.json` (dentro desta pasta).
6. Abra o painel → aba **Contas** → **Vincular canal do YouTube**, faça login no Google e escolha o canal.
   Se aparecer "o Google não verificou este app", clique em **Avançado → Acessar** (é o seu próprio app).
   Repita para cada canal; depois marque de quais streamers cada canal é a conta padrão.

Limites do YouTube enquanto o projeto não passa pela auditoria do Google:
- **Os vídeos enviados pela API ficam privados.** Torne-os públicos no YouTube Studio, ou peça a
  auditoria no formulário "YouTube API Services – Audit and Quota Extension".
- **Cota: ~6 envios por dia somando todos os canais do projeto** (10.000 unidades; cada envio gasta 1.600).
  A mesma auditoria serve para pedir mais cota. O agendador já respeita esse limite (`publicacao.youtube.envios_por_dia`).

Os acessos ficam só no seu PC, em `dados/_publicacao/tokens/`. **Nunca compartilhe essa pasta nem `segredos/`.**

## Vincular o TikTok (uma vez)

O painel publica pela Content Posting API oficial do TikTok. Para isso, você cria um app de desenvolvedor:

1. Entre em https://developers.tiktok.com com uma conta do TikTok, vá em **Manage apps** e crie um app.
2. Use o **Sandbox** do app (fica no topo da página do app): ele funciona sem passar pela revisão do TikTok.
   Em **Sandbox settings → Target users**, adicione as contas do TikTok em que você vai publicar.
3. Em **Products**, adicione:
   - **Login Kit**, plataforma **Desktop**, com o Redirect URI exatamente
     `http://localhost:8800/oauth/tiktok/callback`
   - **Content Posting API**, e ative **Direct Post** (só necessário para o modo "direto")
4. Em **Scopes**, confira se estão `user.info.basic`, `video.upload` e `video.publish`.
5. Copie o **Client key** e o **Client secret** (os do Sandbox) para o arquivo
   `segredos/tiktok_app.json`, neste formato:
   ```json
   {"client_key": "cole aqui", "client_secret": "cole aqui"}
   ```
6. Abra o painel → aba **Contas** → **Vincular conta do TikTok**, faça login e autorize.
   Para vincular outra conta, saia da anterior no tiktok.com (ou use uma janela anônima) e repita.
   Depois marque de quais streamers cada conta é a padrão.

Ao aprovar um corte com uma conta do TikTok marcada, você escolhe o **modo**:

| Modo | Como funciona | Limites |
|---|---|---|
| **Rascunho** (padrão) | O vídeo chega na caixa de entrada do app do TikTok. Você abre a notificação, escolhe som/capa, cola a legenda (botão **Copiar legenda** na aba Fila) e publica | Pode ser público já. Até 5 rascunhos pendentes por conta a cada 24h |
| **Direto** | Publica no perfil já com legenda, privacidade e interações que você escolher na janela | Enquanto o app não passar pela auditoria do TikTok: **só em conta privada** e o vídeo sai como **"Só eu"**; até 5 contas por dia |

Para postar direto em público, envie o app para revisão e peça a auditoria da Content Posting API no
portal (a janela de publicar já segue as regras de interface que o TikTok exige). Mesmo auditado, o
TikTok limita cada conta a ~15 posts por dia via API.

O acesso vale 180 dias e é renovado sozinho; se vencer ou for revogado, a conta aparece com
"vincular de novo" na aba Contas.

## Antes de usar de verdade

- **Facecam**: meça a posição da câmera de cada streamer (num print do VOD em 1920x1080) e preencha
  `facecam: {x, y, w, h}` no config. Sem isso, o corte usa o layout de fundo desfocado.
- **Calibração**: rode com `--sem-render` num VOD real, confira os horários e ajuste
  `nota_minima`, `atraso_chat` e os pesos.
- **Permissão** dos streamers para cortar e monetizar.

### Vídeo de demonstração para a revisão do app no TikTok

Para enviar o app para revisão, o TikTok pede um vídeo do fluxo completo e um texto explicando
cada escopo. O vídeo sai de um roteiro que usa o painel de verdade e adiciona legendas em inglês.
O texto (até 1000 caracteres) está pronto em `demo/texto_revisao_tiktok.txt`.

```
pip install playwright
python -m playwright install chromium
python -m cortes painel                  # em outro terminal, na porta 8800
python demo/gravar_demo_tiktok.py
```

Use as chaves do Sandbox e uma conta "target user" deixada **privada**. O roteiro clica sozinho;
você só faz o login no TikTok e clica em *Authorize*. Ele **publica de verdade**: 1 vídeo como
"Só eu" e 1 rascunho. O vídeo fica em `dados/_demo/` (mp4, abaixo de 50 MB). Se a conta já
estiver vinculada e você não quiser mostrar o login, use `--sem-vinculo`.

## Teste

`python tests/teste_sintetico.py` gera uma live falsa de 10 minutos, com momentos conhecidos, e valida a detecção e os cortes 1080x1920.

`python tests/teste_publicacao.py` e `python tests/teste_tiktok.py` testam a fila, o YouTube e o TikTok
com respostas simuladas (não publicam nada nem usam suas contas).

## Próximas fases

2. ~~Whisper, legendas, IA para título/filtro e painel de revisão~~ (feito)
3. Upload pelas APIs oficiais (~~YouTube~~ e ~~TikTok~~ feitos; falta o Instagram)
4. Métricas e relatórios
