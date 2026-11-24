# Publicação

Depois de aprovado na Revisão, um corte pode ser publicado de duas formas:

1. **À mão**: ao aprovar, o painel copia o mp4 e um `.txt` com título, descrição e hashtags para a pasta
   `pasta_prontos` (padrão `D:\video-auto-cut\prontos`). Ao desaprovar, a cópia é apagada (`painel.exportar`,
   `painel._apagar_exportado`). Um re-render de um corte aprovado atualiza a cópia.
2. **Pela fila**: "Aprovar e agendar" cria um item por conta escolhida, publicado no horário pela API oficial de
   cada plataforma.

## Contas (`contas.py`)

```
dados/_publicacao/contas.json        lista de contas, sem segredos (o painel mostra)
dados/_publicacao/tokens/<id>.json   tokens de acesso (nunca saem do PC nem voltam pela API)
```

`contas.PLATAFORMAS`: `youtube` (até 180 s), `tiktok` (até 600 s; o limite real do perfil é conferido na hora) e
`simulacao` (não publica nada, serve para testar a fila). Cada conta tem `canais`, a lista de streamers para os quais
ela é a conta padrão, já marcada na janela de publicar. `precisa_reconectar` fica verdadeiro quando o token deixa de valer.

## Fila

`fila.py` e `dados/_publicacao/fila.json`. Cada item é "publicar o corte X na conta Y no horário Z".

- **Agendamento** (`fila.agendar`): modo `proximo` (próximo horário livre da conta), `agora` ou `data`. O próximo
  horário segue `publicacao.horarios` e `max_por_dia_por_conta` e, no YouTube, a cota do projeto (`envios_por_dia`,
  que zera à meia-noite do horário do Pacífico, como a do Google).
- **Trabalhador** (`fila.iniciar_trabalhador`): uma thread que **só roda com o painel aberto** e confere a fila a cada
  20 s. O que vencer com o PC desligado sai quando o painel abrir.
- **Status**: `agendado` → `enviando` → `publicado` | `erro` | `cancelado`.
- **Erros** (`executar_vencidos`):
  - `ErroCota`: reagenda para o dia seguinte;
  - `ErroConta`: marca a conta para reconectar e o item vira `erro`;
  - `ErroDefinitivo`: vira `erro`, sem nova tentativa;
  - qualquer outro (rede, 5xx): tenta de novo em 15 min, até 3 vezes.
- **Ações** (`fila.acao`): `cancelar`, `tentar` (no próximo horário livre) e `agora`.

Um publicador é `publicar(item, conta, cfg) -> {"url": ..., ...}`, escolhido por `fila._publicador(plataforma)`.

## YouTube (`pub_youtube.py`)

- Credencial OAuth "Aplicativo da Web" do Google Cloud em `segredos/youtube_client_secret.json`, com redirecionamento
  para `http://localhost:8800/oauth/youtube/callback` (o passo a passo está no README do bot).
- Vínculo: `/oauth/youtube/iniciar` → login no Google → callback → `concluir_vinculo` cria a conta. Cada vínculo
  corresponde a **um canal**.
- Envio pela YouTube Data API v3 (`montar_corpo`): título, descrição, `categoria` e `privacidade`. Um projeto sem
  auditoria do Google tem os vídeos forçados para privado.

## TikTok (`pub_tiktok.py`)

- App do TikTok for Developers (Login Kit "Desktop" com PKCE + Content Posting API). A credencial fica em
  `segredos/tiktok_app.json`.
- Dois modos, escolhidos ao aprovar:
  - `rascunho` (escopo `video.upload`): o vídeo vai para a caixa de entrada do app, e você publica por lá. Funciona em
    público mesmo sem auditoria. O TikTok aceita no máximo 5 rascunhos pendentes por conta a cada 24 h;
  - `direto` (escopo `video.publish`): publica com legenda e privacidade. Sem auditoria, só em conta privada e com
    vídeo "Só eu".
- Antes de cada envio direto, a janela busca as opções atuais do perfil (`info_criador`) e aplica as regras do TikTok
  sobre conteúdo comercial (`painel.opcoes_tiktok`).
- A legenda (`montar_legenda`) junta título, descrição, crédito e hashtags. O limite é contado em UTF-16, como o TikTok faz.
- `demo/gravar_demo_tiktok.py` grava o vídeo do fluxo completo que a revisão do app exige.

## Instagram

Ainda não existe (é a próxima fase no README).
