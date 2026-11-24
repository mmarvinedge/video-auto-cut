# video-auto-cut

Bot local (Windows) que transforma lives da Twitch/Kick em cortes verticais e filmes em edits, com um painel
web para revisar e publicar. O código fica em `cortes-bot/` e é todo em português (nomes, mensagens, comentários).

## Antes de mexer: leia a documentação

`cortes-bot/docs/README.md` é o índice, com um arquivo por funcionalidade (arquitetura, cortes de live, painel,
enquadramento, publicação, edits). Comece por ele em vez de varrer o código: cada doc diz o fluxo, onde os dados
ficam, como estender e as armadilhas conhecidas.

## Ambiente

- Python do projeto: `D:\video-auto-cut\.venv\Scripts\python.exe`. O `python` do PATH não tem as dependências.
- Comandos de dentro de `cortes-bot`: `..\.venv\Scripts\python -m cortes <comando>`.
- Painel: http://localhost:8800 (a configuração `painel` do `.claude/launch.json` serve para o preview).
- Testes: `..\.venv\Scripts\python tests\teste_<nome>.py` (sem pytest, sem rede, sem contas reais).

## Regras

- `config.yaml` é escrito à mão e comentado: nunca o regrave inteiro (veja `docs/arquitetura.md › Configuração`).
- `dados/`, `segredos/` e `dados/_publicacao/` ficam fora do git e guardam tokens: não leia nem exponha os tokens.
- Testes que renderizam não podem gravar em `prontos/` nem em `dados/` do usuário: use uma pasta temporária.
- Mudou uma funcionalidade, uma rota, um comando ou um formato de arquivo? Atualize o `.md` dela em `cortes-bot/docs/`
  na mesma mudança.
