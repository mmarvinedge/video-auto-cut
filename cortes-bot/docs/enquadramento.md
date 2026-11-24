# Enquadramento

Ferramenta para marcar, sobre frames da live, dois retângulos:

- **cam** (`facecam`): onde está a câmera do streamer;
- **conteúdo** (`conteudo`): a parte do jogo que vai para baixo da faixa preta.

A página (`cortes/enquadrar.html`, porta **8810**) mostra os retângulos arrastáveis e uma prévia 1080x1920 ao vivo
(a faixa preta engrossa ou afina enquanto você arrasta). As medidas são em pixels do vídeo **1920x1080**.

## Como abrir

| De onde | Vale para | Frames de |
|---|---|---|
| `python -m cortes enquadrar <canal> <video>` | o canal | o vídeo dado |
| Lives › **Ajustar enquadramento** | o canal | o trecho baixado mais recente |
| Lives › **Enquadrar** num VOD | aquela live | 3 amostras de 4 s (começo, meio e fim), baixadas na hora (`painel.amostra_do_vod`) |
| Revisão › **Ajustar enquadramento…** num corte | só aquele corte, e salvar já manda re-renderizá-lo | o trecho bruto do corte |

No painel, `painel.abrir_oficina` sobe o servidor do enquadramento numa thread, trocando o anterior se houver, e a
página o abre num `<dialog>` com `<iframe>`.

## Onde fica salvo (`enquadrar.arquivo`)

```
dados/<canal>/enquadramento.json                       canal
dados/<canal>/enquadramento/<vod>.json                 uma live
dados/<canal>/enquadramento/corte_<id com _>.json      um corte
```

`enquadrar.resolver` junta os três, do mais geral para o mais específico (o corte ganha). Já
`enquadrar.aplicar(canal, dados, nome, vod, corte)` devolve uma cópia do canal com `facecam`/`conteudo`
substituídos. O `config.yaml` nunca é reescrito. O `facecam` dele é só o valor inicial.

**Por que três níveis**: o streamer muda a cam de lugar entre lives e às vezes no meio de uma. O ajuste de um
corte fica preso a ele de propósito, porque espalhar o conserto para os vizinhos estragaria os que estavam certos.

## Armadilhas

- Trechos de HLS nem sempre aceitam busca rápida (`-ss` antes do `-i`): `enquadrar._tirar` tenta a busca rápida e,
  se falhar, a lenta.
- Os frames são gravados em PNG, não em JPEG: o encoder mjpeg recusa o YUV "non full-range" que a Twitch entrega.
- `enquadrar.intervalo(video)` devolve o começo e o fim reais do arquivo, que nem sempre começa em 0.
