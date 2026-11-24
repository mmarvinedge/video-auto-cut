# Documentação do cortes-bot

Mapa das funcionalidades, para quem (pessoa ou IA) precisa mexer no projeto sem reler o código
inteiro. Cada arquivo diz **o que a funcionalidade faz, por onde o fluxo passa, onde os dados
ficam, como estender e as armadilhas já conhecidas**.

| Documento | Funcionalidade | Módulos principais |
|---|---|---|
| [arquitetura.md](arquitetura.md) | Visão geral, pastas, `config.yaml`, CLI e convenções do código | `__main__`, `config` |
| [cortes-de-live.md](cortes-de-live.md) | VOD da Twitch/Kick → cortes verticais (curtos, longos para o TikTok, compilações) | `vod`, `hls`, `chat_*`, `detect`, `transcrever`, `fala`, `ia`, `legendas`, `render` |
| [painel.md](painel.md) | Painel web local (porta 8800): abas, rotas da API, trabalhos em segundo plano | `painel`, `painel_edit`, `painel.html`, `estilo.css`, `trabalho` |
| [enquadramento.md](enquadramento.md) | Ferramenta para marcar a facecam e o conteúdo (porta 8810) | `enquadrar`, `enquadrar.html` |
| [publicacao.md](publicacao.md) | Contas, fila agendada, YouTube, TikTok, simulação e a pasta `prontos/` | `contas`, `fila`, `pub_*` |
| [edits.md](edits.md) | Edits de filme: fala de gancho + planos cortados na batida da música | `edit`, `batidas`, `cenas`, `ia_edit`, `painel_edit` |

## Onde procurar

| Quero… | Vá em |
|---|---|
| criar um comando novo de linha de comando | [arquitetura.md › CLI](arquitetura.md#linha-de-comando) |
| disparar algo demorado pelo painel, com barra de progresso | [painel.md › Trabalhos em segundo plano](painel.md#trabalhos-em-segundo-plano) |
| criar uma aba ou rota no painel | [painel.md › Como estender](painel.md#como-estender) |
| mudar como os momentos são escolhidos | [cortes-de-live.md › Detecção](cortes-de-live.md#2-detecção) |
| mudar o visual do corte (layout, legenda) | [cortes-de-live.md › Render](cortes-de-live.md#5-render) |
| entender por que um corte não foi publicado | [publicacao.md › Fila](publicacao.md#fila) |
| mexer no prompt da IA | `cortes/ia.py` (cortes) e `cortes/ia_edit.py` (edits) |
| rodar os testes | [arquitetura.md › Testes](arquitetura.md#testes) |

## Como manter

Mudou o comportamento de uma funcionalidade, criou uma rota, um comando ou um arquivo de dados?
Atualize o `.md` dela na mesma mudança. Funcionalidade nova ganha um arquivo novo e uma linha
nas tabelas acima.
