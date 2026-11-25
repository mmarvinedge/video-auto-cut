# Painel

Painel web local em **http://localhost:8800**, o lugar onde o usuário trabalha no dia a dia.

- Servidor: `cortes/painel.py`. Usa `http.server` (`ThreadingHTTPServer`) puro, **sem framework**.
- Página: `cortes/painel.html`, um arquivo só, com HTML e JS sem build. Visual em `cortes/estilo.css`, compartilhado
  com o enquadramento (tema "Vice City": roxo, magenta e ciano).
- Os dois arquivos são **lidos do disco a cada acesso**: mudou o HTML ou o CSS, basta recarregar a página. Já o Python
  só muda reiniciando o painel.

Como subir:
- `python -m cortes painel` (com terminal);
- `iniciar_painel.pyw` sobe escondido, sem janela, e a saída vai para `dados/painel.log`. Use `--instalar`/`--remover`
  para pôr ou tirar da inicialização do Windows, `--reiniciar` depois de um `git pull` e `--parar` para desligar.
  Sem a `ANTHROPIC_API_KEY` no ambiente de quem o abriu, ele a lê das variáveis do usuário (veja edits.md);
- no Claude Code: `.claude/launch.json` tem a configuração `painel` para o preview e a `painel-teste`, uma segunda
  cópia na porta **8801** com `trabalhador=False` (sem a fila de publicação). Use a de teste enquanto o painel de
  verdade estiver aberto na 8800, para não ter dois trabalhadores de fila publicando ao mesmo tempo.

## Abas

A aba vem do `#hash` da URL (`abaAtual()`, `mostrarAba()`), e cada uma é uma `<section id="aba-<nome>">`.

| Aba | O que faz | Rotas usadas |
|---|---|---|
| **Lives** | escolhe o streamer, lista os VODs (com a data da live e "já processada"), processa um, ajusta o enquadramento, adiciona streamer | `/api/vods`, `/api/processar`, `/api/trabalho`, `/api/enquadrar`, `/api/canais` |
| **Edits** | formulário do edit de filme (filme e música do computador ou do YouTube, tema, trecho, ajustes finos), seletor de arquivos, andamento e cards dos edits feitos (vídeo, título/descrição/hashtags, ajustar o edit, renderizar de novo, copiar para prontos) | `/api/edit`, `/api/edits`, `/api/arquivos`, `/video-edit/<id>`, `/quadro-edit/<id>`, `/mini-edit/<id>`, `/audio-edit/<id>`, `/api/edits/<id>/linha\|planos\|renderizar\|prontos\|texto\|ajustar\|corte\|desfazer\|previa`, `/api/trabalho` |
| **Revisão** | cards dos cortes: vídeo, capa, título/descrição/hashtags, IA, aprovar/rejeitar, re-render | `/api/cortes`, `/api/cortes/<id>`, `/video/<id>`, `/capa/<id>`, `/api/legenda/<id>`, `/api/prompt/<id>`, `/api/rerender/<id>`, `/api/publicar` |
| **Fila** | publicações agendadas: cancelar, tentar de novo, publicar agora | `/api/fila`, `/api/fila/<id>/<acao>` |
| **Contas** | vincula YouTube/TikTok, contas de simulação, contas padrão por streamer | `/oauth/*`, `/api/contas/*`, `/api/tiktok/<id>/criador` |

`/api/estado` devolve o que a página precisa saber do servidor (canais, contas, se há IA, horários, os padrões do
`edit:` do config) e é
chamado a cada troca de aba, na variável global `E` do JS.

## Rotas

Todas em `servir()`, numa cadeia de `if/elif` em `do_GET` e `do_POST`.

- **GET**: páginas, `/api/...` em JSON, `/video/<id>` (mp4 com suporte a `Range`, necessário para o player
  avançar), `/capa/<id>?t=` (JPEG de um quadro) e `/oauth/<plataforma>/iniciar|callback`.
- **POST**: só JSON (`Content-Type: application/json`). O corpo chega em `corpo`.
- Erros: `ValueError`/`RuntimeError`/`KeyError`… viram `{"ok": false, "erro": "..."}` com status 400. Qualquer outra
  exceção vira 500, e o traceback vai para o terminal ou o log. Rota desconhecida em `/api/` responde que **o painel está
  com código antigo**, porque a página nova pode chamar uma rota que o processo velho ainda não tem.

### Rotas dos edits

A lógica fica em `cortes/painel_edit.py`. O `painel.py` só roteia.

| Rota | Faz |
|---|---|
| `GET /api/edits` | lista os edits (`dados/edits/*/*/plano.json`), do mais recente para o mais antigo |
| `GET /api/arquivos?pasta=&tipo=video\|audio` | conteúdo de uma pasta: subpastas, arquivos de mídia do tipo e atalhos (Início, Vídeos, Músicas, Downloads, Área de trabalho, discos). Sem `pasta`, abre a última usada (`dados/edits/pastas.json`) |
| `GET /video-edit/<filme>/<edit>` | o `edit.mp4`, com `Range`; com `?previa=1`, a `previa.mp4` do ajuste |
| `GET /api/edits/<id>/linha` | o que a tela de ajuste desenha: marcas do plano (gancho, `gatilho`, drop), a música (onda em picos de 50 ms, batidas) e as falas do filme |
| `GET /quadro-edit/<id>?t=&w=` | o quadro do filme no segundo `t`, em jpg, no recorte do edit (sem tarjas), `w` de 120 a 720 px |
| `GET /audio-edit/<id>` | a música tratada do edit (`musica.wav`), com `Range`, para "Ouvir o drop" |
| `GET /api/edits/<id>/planos` | os planos do filme que têm miniatura (`id`, `inicio`, `fim`, `brilho`, `usado`), para trocar o plano de um corte |
| `GET /mini-edit/<id>?cena=` | a miniatura de um plano (do cache `miniaturas_*` do filme) |
| `POST /api/edit` | valida o formulário (`painel_edit.argumentos`: filme e música são um arquivo que existe ou um endereço do YouTube com `<campo>_de: youtube` e `<campo>_qualidade`) e dispara `python -m cortes edit ...` com `trabalho.comecar_comando` |
| `POST /api/edits/<id>/renderizar` | dispara `edit-render` do `plano.json` |
| `POST /api/edits/<id>/prontos` | copia `edit.mp4` e `edit.txt` para `prontos/` |
| `POST /api/edits/<id>/texto` | grava título, descrição e hashtags no `plano.json` e reescreve o `edit.txt` |
| `POST /api/edits/<id>/ajustar` | `{gancho: [ini, fim] \| null, drop_filme, fala_fim, drop_fala, drop_musica, volume_musica, ritmo?, duracao_musica?, transicoes?, abertura?, musica_no_gancho?}`: valida e refaz o plano sem IA (`edit.replanejar`); devolve as marcas novas. Recusado com um trabalho rodando |
| `POST /api/edits/<id>/corte` | `{op: plano\|deslizar\|transicao\|excluir\|dividir, i, cena?, fonte?, transicao?}`: muda um corte (`edit.editar_corte`) e devolve as marcas. Recusado com um trabalho rodando |
| `POST /api/edits/<id>/desfazer` | troca `plano.json` e `plano.anterior.json` |
| `POST /api/edits/<id>/previa` | dispara `edit-render <plano> --previa` (540 px, rápido) |

O seletor de arquivos existe porque o navegador não informa o caminho de um arquivo escolhido num
`<input type=file>` (só o nome), e o comando precisa do caminho completo.

### Segurança

- Escuta só em `127.0.0.1`.
- `_host_ok()` confere o cabeçalho `Host` (contra DNS rebinding). No POST, o `Origin` também tem de ser o próprio painel.
- Exigir JSON no POST impede que outro site envie formulários para cá (o navegador bloqueia por CORS).
- Ids e nomes vindos da página passam por `SEGURO` (`^[\w.-]+$`) ou por `_localizar`, e caminhos de vídeo são
  conferidos para estarem dentro da pasta de dados (`caminho_video`).
- Tokens das contas nunca são devolvidos pela API (`contas.py`).
- `/api/arquivos` lista qualquer pasta do computador. Só é aceitável porque o painel só atende localhost. Não abra o
  painel para a rede.
- O pedido de edit vira argumentos de processo (lista, sem shell), e os valores vão como `--opcao=valor`: um tema que
  comece com `-` não vira opção. O filme e a música precisam existir e ter extensão de vídeo ou áudio. Tempos passam por
  `TEMPO`, e ids de edit por `IDENT` (`<filme>/<edit>`).

## Trabalhos em segundo plano

`cortes/trabalho.py`. **Um trabalho por vez** no painel inteiro: processar uma live, re-renderizar, recompilar
depois de enquadrar. Todos disputam GPU, disco e rede, e dois juntos só atrasam os dois.

| Função | Quando usar |
|---|---|
| `trabalho.comecar(canal, url, titulo, opcoes)` | o fluxo da aba Lives: `baixar-audio` (ou reaproveita o áudio já baixado) e depois `processar` |
| `trabalho.comecar_comando(titulo, passo, argumentos, fim="")` | rodar **qualquer** `python -m cortes <argumentos>` num processo filho |
| `trabalho.comecar_funcao(titulo, canal, fn)` | tarefa curta feita dentro do próprio processo do painel (`fn(log)` devolve um resumo) |

Todas levantam `RuntimeError` se já houver um trabalho rodando. A rota devolve `{"ok": true, "atual": ...}`.

Como o progresso chega à página:
1. `_rodar` roda o comando com `stdout` em pipe e cada linha vai para o log (as últimas 400 ficam na memória);
2. uma linha com `N/M` (ex.: `1500/3135 pedaços`, `120/360s`) vira a barra de progresso. Dentro do processo,
   `trabalho.progresso(fracao)` faz o mesmo (o `render._com_progresso` usa isso);
3. a página chama `/api/trabalho` a cada 2 s (`verTrabalho()` na aba Lives, `verTrabalhoEdit()` na aba Edits) e mostra
   o passo, o tempo, a barra e as últimas 14 linhas do log. As duas abas usam a mesma caixa (`htmlTrabalho(t)`), que
   aponta para onde o resultado ficou pelo `tipo` do trabalho (`edit`/`edit-render` → Edits; o resto → Revisão).

`/api/trabalho` → `{"atual": {"titulo", "passo", "rodando", "inicio", "fim", "erro", "progresso", "tipo"?, "resultado"?, ...extra}, "log": [...]}`.

`comecar_comando(..., extra={...})` junta campos ao estado, e uma linha `Arquivo: <caminho>` na saída do comando vira
`resultado`. É assim que um comando devolve algo para a página sem uma rota própria.

## Como estender

**Nova aba**
1. Link no `<nav>`: `<a href="#x" data-aba="x">X</a>`.
2. `<section id="aba-x" hidden>…</section>` dentro de `<main>`.
3. Acrescente `"x"` nas **duas** listas de `mostrarAba()` e chame a função que desenha a aba.

**Nova rota**
1. `elif url.path == "/api/x":` em `do_GET`, ou `elif caminho == "/api/x":` em `do_POST`.
2. Valide tudo o que vem da página (`SEGURO`, listas permitidas, caminhos dentro de uma pasta conhecida).
3. Responda com `self._json({...})`. Para erro esperado, levante `ValueError` com uma mensagem para o usuário.

**Nova tarefa demorada**: crie o comando na CLI (imprimindo `N/M`) e dispare com `trabalho.comecar_comando`.
O painel não trava e o usuário vê o log.

JS: use `api(url, corpo?)`, que nunca lança e devolve `{ok:false, erro}` em qualquer falha, `$()`/`esc()` para
DOM e escape, e as classes de `estilo.css` (`.escolha`, `.linha`, `.opcoes`, `.card`, `.trabalho`, `.vazio`,
`button.primario`, `dialog .dlg`).

**Cuidado com `.card`**: os ouvintes da aba Revisão ficam no `document` e pegam **qualquer** `closest(".card")`. Um
card de outra aba com a classe `.card` e campos `.titulo` faz o painel tentar salvar aquilo como corte
(`POST /api/cortes/<id>` → 400) e quebra o contador de letras. Por isso os edits usam `.card-edit`, que tem o mesmo
estilo no CSS.
