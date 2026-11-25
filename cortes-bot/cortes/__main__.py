"""Linha de comando do bot de cortes.

  python -m cortes vods <canal>                       lista os últimos VODs
  python -m cortes baixar <canal> <url_do_vod>        baixa o VOD inteiro (+ info com horário de início)
  python -m cortes baixar-audio <canal> <url_do_vod>  baixa só o áudio (bem mais leve; basta para processar)
  python -m cortes chat-twitch                        grava o chat ao vivo de todos os canais Twitch
  python -m cortes chat-vod <canal> <url_do_vod>      baixa o chat de um VOD da Twitch já encerrado
  python -m cortes kick-assinar                       inscreve os canais Kick no webhook de chat (API oficial)
  python -m cortes kick-webhook                       recebe o chat do Kick via webhook
  python -m cortes processar <canal> <video.mp4>      gera as duas versões: curtos (Shorts/Reels) e TikTok (>1 min)
  python -m cortes painel                             abre o painel de revisão em http://localhost:8800
  python -m cortes enquadrar <canal> <video.mp4>      escolhe na tela o recorte da cam e do conteúdo
  python -m cortes edit <filme> <musica>              edit de filme: gancho com fala + planos na batida
  python -m cortes edit-render <plano.json>           renderiza de novo um edit depois de mexer no plano
  python -m cortes modelos                            lista os modelos de edit (modelos/*.yaml)
  python -m cortes baixar-youtube <url> [--audio] [--qualidade q]   baixa um vídeo (ou o áudio) do YouTube para um edit
"""
import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import chat_twitch, config, detect, legendas, render, vod


def cmd_edit(cfg, a):
    from . import edit, youtube
    # um endereço do YouTube no lugar do arquivo: baixa antes (ou reaproveita o já baixado)
    filme = youtube.resolver(a.filme, False, a.qualidade_filme, cfg).resolve()
    musica = youtube.resolver(a.musica, True, a.qualidade_musica, cfg).resolve()
    for arq in (filme, musica):
        if not arq.exists():
            raise SystemExit(f"Não achei {arq}")
    if a.modelo:            # o modelo fica entre o config e as opções da mão
        from . import modelos
        try:
            cfg["edit"] = modelos.aplicar(cfg.get("edit"), a.modelo)
        except ValueError as erro:
            raise SystemExit(str(erro))
    ajustes = {"proporcao": a.proporcao, "slowed": a.slowed,
               "musica_no_gancho": {"sim": True, "nao": False}.get(a.musica_no_gancho),
               "volume_musica": a.volume_musica,
               "transicoes": edit.ler_transicoes(a.transicoes) if a.transicoes is not None else None,
               "idioma": edit.ler_idioma(a.idioma) if a.idioma else None}
    cfg["edit"] = {**(cfg.get("edit") or {}), **{k: v for k, v in ajustes.items() if v is not None}}
    t0 = time.time()
    plano = edit.planejar(filme, musica, cfg, tema=a.tema or "", trecho=edit.ler_intervalo(a.trecho),
                          gancho=a.gancho, drop=edit.ler_tempo(a.drop) if a.drop else None,
                          usar_ia=not a.sem_ia, duracao=a.duracao,
                          drop_filme=edit.ler_tempo(a.drop_filme) if a.drop_filme else None,
                          ritmo=a.ritmo, abertura={"sim": True, "nao": False}.get(a.abertura),
                          fala_drop=edit.ler_tempo(a.fala_drop) if a.fala_drop else None,
                          drop_fala=a.drop_fala)
    print(f"Plano em {config.relativo(plano)}")
    if a.so_planejar:
        return
    _edit_render(cfg, plano, t0, a.prontos)


def _edit_render(cfg, plano: Path, t0: float, prontos: bool) -> None:
    from . import edit
    print("Renderizando...")
    video = edit.renderizar(plano)
    print(f"Pronto em {time.time() - t0:.0f}s: {config.relativo(video)}")
    if prontos and (copia := edit.copiar_para_prontos(video, cfg)):
        print(f"Cópia em {copia}")


def cmd_baixar_youtube(cfg, a):
    from . import youtube
    arq = youtube.baixar(youtube.validar(a.url), a.audio, youtube.pasta(cfg), q=a.qualidade)
    print(f"Arquivo: {arq}")      # o painel lê esta linha para preencher o campo do edit


def cmd_modelos(cfg, a):
    from . import modelos
    lista = modelos.listar()
    if not lista:
        print(f"Nenhum modelo em {modelos.PASTA}")
    for m in lista:
        print(f"{m['id']:<16} {m['nome']}: {m['descricao']}")


def cmd_edit_render(cfg, a):
    if a.previa:
        from . import edit
        t0 = time.time()
        print("Renderizando a prévia...")
        video = edit.renderizar(Path(a.plano).resolve(), previa=True)
        print(f"Prévia pronta em {time.time() - t0:.0f}s: {config.relativo(video)}")
        return
    _edit_render(cfg, Path(a.plano).resolve(), time.time(), a.prontos)


def cmd_vods(cfg, a):
    for v in vod.listar(config.canal(cfg, a.canal), a.n):
        dur = f"{int(v['duracao'] or 0) // 3600}h{int(v['duracao'] or 0) % 3600 // 60:02d}"
        print(f"{dur:>6}  {v['url']}\n        {v['titulo']}")


def cmd_baixar(cfg, a):
    pasta = config.pasta_canal(cfg, a.canal) / "vods"
    print(f"Baixando para {pasta} ...")
    print(vod.baixar(a.url, pasta))


def cmd_baixar_audio(cfg, a):
    pasta = config.pasta_canal(cfg, a.canal) / "vods"
    print(f"Baixando só o áudio para {pasta} ...")
    print(vod.baixar_audio(a.url, pasta))


def cmd_chat_vod(cfg, a):
    from . import chat_vod

    c = config.canal(cfg, a.canal)
    if c["plataforma"] != "twitch":
        raise SystemExit(f"{a.canal} é da {c['plataforma']}: o chat de VOD só existe para a Twitch")
    pasta = config.pasta_canal(cfg, a.canal)
    ident = chat_vod.id_do_vod(a.url)
    destino = pasta / "chat" / f"vod_{ident}.jsonl"
    if destino.exists() and not a.refazer:
        raise SystemExit(f"{destino} já existe; use --refazer para baixar de novo")

    inicio = a.inicio
    if inicio is None:
        # o yt-dlp salva como v<id>_audio.mp4, com o .info.json ao lado
        baixados = sorted((pasta / "vods").glob(f"*{ident}*.mp4"))
        inicio = next((t for p in baixados if (t := vod.inicio_do_vod(p))), None)
    if inicio is None:
        raise SystemExit("não sei a que horas essa live começou: baixe o áudio antes (o .info.json traz o "
                         "horário) ou passe --inicio com o epoch do começo")

    print(f"Baixando o chat do VOD {ident} para {destino} ...")
    n = chat_vod.baixar(a.url, inicio, destino)
    print(f"{n} mensagens salvas. Agora rode o `processar` de novo: ele lê esse arquivo junto com o áudio.")


def cmd_chat_twitch(cfg, a):
    tarefas = [
        chat_twitch.gravar(c["login"], config.pasta_canal(cfg, nome) / "chat")
        for nome, c in cfg["canais"].items() if c["plataforma"] == "twitch"
    ]

    async def todos():
        await asyncio.gather(*tarefas)

    asyncio.run(todos())


def cmd_kick_assinar(cfg, a):
    from . import chat_kick
    chat_kick.assinar_chat([c["login"] for c in cfg["canais"].values() if c["plataforma"] == "kick"])


def cmd_kick_webhook(cfg, a):
    from . import chat_kick
    mapa = {c["login"]: nome for nome, c in cfg["canais"].items() if c["plataforma"] == "kick"}
    chat_kick.servir_webhook(config.RAIZ / cfg["pasta_dados"], mapa, cfg["kick_api"]["porta_webhook"])


def cmd_enquadrar(cfg, a):
    from . import enquadrar

    enquadrar.servir(Path(a.video), a.canal, config.canal(cfg, a.canal),
                     config.RAIZ / cfg["pasta_dados"], a.porta)


def cmd_painel(cfg, a):
    from . import painel
    if (cfg.get("painel") or {}).get("gravar_chat"):
        gravar_chat_em_segundo_plano(cfg)
    painel.servir(config.RAIZ / cfg["pasta_dados"], a.porta)


def gravar_chat_em_segundo_plano(cfg) -> None:
    """O painel já precisa ficar aberto para a fila publicar; aproveita e grava o chat da Twitch.
    Sem chat a detecção fica só com o áudio e confunde fala alta com momento bom.
    Fora do ar não chega mensagem nenhuma, então não custa deixar ligado."""
    import threading

    tarefas = [(c["login"], config.pasta_canal(cfg, nome) / "chat")
               for nome, c in cfg["canais"].items() if c["plataforma"] == "twitch"]
    if not tarefas:
        return

    def rodar():
        async def todos():
            await asyncio.gather(*(chat_twitch.gravar(login, pasta) for login, pasta in tarefas))
        asyncio.run(todos())

    threading.Thread(target=rodar, name="chat-twitch", daemon=True).start()
    print(f"Gravando o chat da Twitch junto com o painel: {', '.join(l for l, _ in tarefas)}")


# ---------------------------------------------------------------- processar

def ouvir(cands: list[dict], midia: Path, cfg: dict, duracao_max: float, rotulo: str, tr=None):
    """Transcreve cada candidato, ajusta as bordas pela fala e reordena pela nota combinada.
    Devolve o Transcritor para reaproveitar o modelo já carregado."""
    from . import fala, transcrever

    if not cands:
        return tr
    w = cfg["whisper"]
    t0 = time.time()
    tr = tr or transcrever.Transcritor(w["modelo"], w["dispositivo"])
    print(f"Whisper ({tr.dispositivo}): ouvindo {len(cands)} momentos {rotulo}...", flush=True)
    for c in cands:
        c["palavras"] = tr.transcrever(midia, c["inicio"] - 6, c["fim"] + 6)
        c["inicio"], c["fim"] = fala.ajustar_bordas(c["palavras"], c["inicio"], c["fim"], duracao_max=duracao_max)
        c["fala"] = fala.nota_fala(c["palavras"], c["inicio"], c["fim"], w["reacoes"],
                                   w.get("pausas"), w.get("peso_pausa", 2.0))
        c["texto"] = fala.texto(c["palavras"], c["inicio"], c["fim"])
    z_sinal = fala.zscores([c["nota"] for c in cands])
    z_fala = fala.zscores([c["fala"]["bruto"] for c in cands])
    for c, zs, zf in zip(cands, z_sinal, z_fala):
        c["nota_sinal"] = c["nota"]
        c["nota"] = round(zs + w["peso_fala"] * zf, 2)
    cands.sort(key=lambda c: c["nota"], reverse=True)
    print(f"Whisper: {rotulo} prontos em {time.time() - t0:.0f}s", flush=True)
    return tr


def avaliar_com_ia(curtos: list[dict], longos: list[dict], canal: dict, cfg: dict, a):
    """Pede à IA para aprovar/reprovar, aparar, dar títulos e montar compilações.
    Devolve as compilações sugeridas, ou None se a IA não rodou (sem credencial, desligada ou erro)."""
    from . import ia

    if not (cfg.get("ia") or {}).get("ativo") or a.sem_ia:
        return None
    if not ia.credenciais_disponiveis():
        print("IA: sem credencial da API do Claude (defina ANTHROPIC_API_KEY); seguindo sem títulos/filtro.")
        return None
    import anthropic

    t0 = time.time()
    try:
        avals, comps = ia.avaliar(curtos, longos, canal, cfg)
    except anthropic.AuthenticationError:
        print("IA: chave da API inválida; seguindo sem IA.")
        return None
    except anthropic.RateLimitError:
        print("IA: limite de uso da API atingido; seguindo sem IA (rode de novo mais tarde).")
        return None
    except (anthropic.APIStatusError, anthropic.APIConnectionError, RuntimeError) as e:
        print(f"IA: falhou ({e}); seguindo sem IA.")
        return None
    ia.aplicar(curtos, avals, cfg["corte"]["duracao_min"])
    ia.aplicar(longos, avals, cfg["tiktok"]["duracao_min"])
    ok = lambda lst: sum(1 for c in lst if c.get("ia", {}).get("aprovar"))  # noqa: E731
    print(f"IA ({ia.MODELO}): curtos {ok(curtos)}/{len(curtos)} e longos {ok(longos)}/{len(longos)} aprovados, "
          f"{len(comps)} compilações sugeridas, em {time.time() - t0:.0f}s", flush=True)
    return comps


@dataclass
class Contexto:
    video: Path
    pasta: Path
    canal: dict
    url: str | None
    so_audio: bool
    legendas: bool
    limite_parado: float


def renderizar_trecho(c: dict, destino: Path, ctx: Contexto) -> Path | None:
    """Baixa o trecho (se o VOD é só áudio), descarta tela parada, gera a legenda e renderiza."""
    if ctx.so_audio:
        if not ctx.url:
            raise SystemExit("Áudio sem .info.json: não sei de qual VOD baixar o trecho.")
        fonte = ctx.pasta / "vods" / "trechos" / f"{destino.stem}_bruto.mp4"
        comeco = vod.baixar_trecho(ctx.url, c["inicio"], c["fim"], fonte)
        c["trecho_inicio"] = round(comeco, 3)   # o re-render do painel precisa disso para recortar
        ini, fim = c["inicio"] - comeco, c["fim"] - comeco
    else:
        fonte, ini, fim = ctx.video, c["inicio"], c["fim"]
    c["tela_parada"] = round(render.fracao_parada(fonte, ini, fim), 2)
    if c["tela_parada"] > ctx.limite_parado:
        c["descartado"] = "tela parada"
        return None
    ass = None
    if ctx.legendas and c.get("palavras"):
        ass = legendas.gerar_ass(c["palavras"], c["inicio"], c["fim"], destino.with_suffix(".ass"),
                                 render.posicao_legenda(ctx.canal))
    return render.renderizar(fonte, ini, fim, destino, ctx.canal, ass)


def _linha(i: int, c: dict) -> str:
    t = int(c["inicio"])
    s = f"  #{i:02d}  nota {c['nota']:>5}  {t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}  ({c['fim'] - c['inicio']:.0f}s)"
    if c.get("ia"):
        s += f"  IA {c['ia']['nota']:.0f}/10  {c['ia']['titulo']}"
    return s


def gerar_lista(cands: list[dict], maximo: int, pasta_saida: Path, prefixo: str, ctx: Contexto, sem_render: bool) -> None:
    prontos = 0
    for i, c in enumerate(cands, 1):
        c["arquivo"] = None
        linha = _linha(i, c)
        if c.get("descartado"):
            print(f"{linha}  -> descartado ({c['descartado']})")
            continue
        if sem_render:
            print(linha + (f"  \"{c['texto'][:70]}\"" if c.get("texto") and not c.get("ia") else ""))
            continue
        if prontos >= maximo:
            continue
        destino = pasta_saida / f"{prefixo}_{i:02d}_{int(c['inicio'])}.mp4"
        if renderizar_trecho(c, destino, ctx) is None:
            print(f"{linha}  -> descartado (tela parada {c['tela_parada']:.0%})")
            continue
        c["arquivo"] = config.relativo(destino)
        prontos += 1
        print(f"{linha}  -> {destino.name}" + (f"\n        \"{c['texto'][:90]}\"" if c.get("texto") and not c.get("ia") else ""))


def compilacao_automatica(curtos: list[dict], cfg: dict) -> list[dict]:
    """Sem IA: uma compilação "melhores momentos" com os cortes curtos de maior nota que somem 65–120s."""
    tk = cfg["tiktok"]
    prontos = sorted((c for c in curtos if c.get("arquivo")), key=lambda c: c["nota"], reverse=True)
    escolhidos, total = [], 0.0
    for c in prontos:
        dur = c["fim"] - c["inicio"]
        if total + dur <= tk["duracao_max"]:
            escolhidos.append(c)
            total += dur
        if len(escolhidos) == 4 or total >= tk["duracao_min"]:
            break
    if len(escolhidos) < 2 or total < tk["duracao_min"]:
        return []
    escolhidos.sort(key=lambda c: c["inicio"])  # ordem cronológica da live
    return [{"partes": [c["id"] for c in escolhidos], "inicio": escolhidos[0]["inicio"], "duracao": round(total, 1),
             "ia": None, "automatica": True}]


def gerar_compilacoes(comps: list[dict], curtos: list[dict], pasta_saida: Path, base: str, ctx: Contexto) -> None:
    por_id = {c["id"]: c for c in curtos}
    for k, comp in enumerate(comps, 1):
        comp["arquivo"] = None
        partes = []
        for pid in comp["partes"]:
            c = por_id[pid]
            arq = c.get("arquivo") or c.get("arquivo_parte")
            if not arq:  # parte que não entrou entre os curtos renderizados: renderiza só para a compilação
                feito = renderizar_trecho(c, pasta_saida.parent / "partes" / f"{base}_{pid}_{int(c['inicio'])}.mp4", ctx)
                c["arquivo_parte"] = arq = config.relativo(feito) if feito else None
            if not arq:
                break
            partes.append(config.absoluto(arq))
        titulo = (comp.get("ia") or {}).get("titulo") or "melhores momentos (automática)"
        if len(partes) != len(comp["partes"]):
            comp["descartado"] = "parte com tela parada"
            print(f"  compilação {k}: {titulo}  -> descartada (uma parte tem tela parada)")
            continue
        destino = pasta_saida / f"{base}_compilacao_{k:02d}.mp4"
        render.concatenar(partes, destino)
        comp["arquivo"] = config.relativo(destino)
        print(f"  compilação {k}: {titulo}  ({comp['duracao']:.0f}s, {len(partes)} partes)  -> {destino.name}")


def cmd_processar(cfg, a):
    from . import enquadrar

    pasta = config.pasta_canal(cfg, a.canal)
    video = Path(a.video)
    base = video.stem.removesuffix("_audio")
    # o enquadramento desta live manda no do canal: o streamer muda a cam de lugar entre lives
    canal = enquadrar.aplicar(config.canal(cfg, a.canal), config.RAIZ / cfg["pasta_dados"],
                              a.canal, vod=base)
    inicio = a.inicio or vod.inicio_do_vod(video)
    arquivos_chat = [Path(p) for p in a.chat] if a.chat else sorted((pasta / "chat").glob("*.jsonl"))
    msgs = None
    if inicio and arquivos_chat:
        msgs = detect.ler_chat(arquivos_chat, inicio, inicio + 24 * 3600)
    elif not inicio:
        print("Aviso: horário de início do VOD desconhecido (sem .info.json nem --inicio); usando só o áudio.")

    w = cfg.get("whisper") or {}
    tk = cfg.get("tiktok") or {}
    usar_whisper = bool(w.get("ativo")) and not a.sem_whisper
    usar_tiktok = bool(tk.get("ativo")) and not a.sem_tiktok

    nota, info = detect.serie_nota(video, msgs, inicio, cfg)
    curtos = detect.candidatos(nota, cfg, w.get("candidatos_para_ouvir") if usar_whisper else None)
    longos = detect.candidatos_longos(nota, cfg) if usar_tiktok else []
    sinais = ("chat + áudio" if info["usou_chat"] else "só áudio") + (" + fala (Whisper)" if usar_whisper else "")
    print(f"VOD {info['duracao'] // 60} min | sinais: {sinais} | mensagens: {info['mensagens']} | "
          f"candidatos: {len(curtos)} curtos, {len(longos)} longos")

    comps_ia = None
    if usar_whisper:
        tr = ouvir(curtos, video, cfg, cfg["corte"]["duracao_max"], "curtos")
        ouvir(longos, video, cfg, tk.get("duracao_max", 120), "longos", tr)
    for prefixo, lista in (("c", curtos), ("l", longos)):
        for i, c in enumerate(lista):
            c["id"] = f"{prefixo}{i}"
    if usar_whisper:
        comps_ia = avaliar_com_ia(curtos, longos, canal, cfg, a)

    ctx = Contexto(video=video, pasta=pasta, canal=canal, url=vod.url_do_vod(video),
                   so_audio=video.stem.endswith("_audio"), legendas=usar_whisper and bool(w.get("legendas")),
                   limite_parado=cfg["corte"].get("max_tela_parada", 1.0))

    print("\nCURTOS (Shorts / Reels):")
    gerar_lista(curtos, cfg["corte"]["max_cortes_por_vod"], pasta / "cortes" / "curtos", base, ctx, a.sem_render)

    comps = []
    if usar_tiktok:
        print("\nTIKTOK — trechos longos:")
        gerar_lista(longos, tk["max_longos_por_live"], pasta / "cortes" / "tiktok", f"{base}_longo", ctx, a.sem_render)
        if not a.sem_render:
            from . import ia
            comps = ia.montar_compilacoes(curtos, comps_ia, cfg) if comps_ia is not None else compilacao_automatica(curtos, cfg)
            print("\nTIKTOK — compilações:" + ("" if comps else " nenhuma (cortes insuficientes para somar 65s)"))
            gerar_compilacoes(comps, curtos, pasta / "cortes" / "tiktok", base, ctx)

    saida_json = pasta / "candidatos" / f"{video.stem}.json"
    saida_json.write_text(json.dumps({"video": config.relativo(video), "canal": a.canal, **info, "candidatos": curtos,
                                      "longos": longos, "compilacoes": comps}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\nResultado salvo em {saida_json}")


def main():
    p = argparse.ArgumentParser(prog="cortes")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("vods"); s.add_argument("canal"); s.add_argument("-n", type=int, default=5); s.set_defaults(f=cmd_vods)
    s = sub.add_parser("baixar"); s.add_argument("canal"); s.add_argument("url"); s.set_defaults(f=cmd_baixar)
    s = sub.add_parser("baixar-audio"); s.add_argument("canal"); s.add_argument("url"); s.set_defaults(f=cmd_baixar_audio)
    s = sub.add_parser("chat-twitch"); s.set_defaults(f=cmd_chat_twitch)
    s = sub.add_parser("chat-vod"); s.add_argument("canal"); s.add_argument("url")
    s.add_argument("--inicio", type=float, help="epoch do começo da live (padrão: lê do .info.json do áudio)")
    s.add_argument("--refazer", action="store_true", help="baixa de novo mesmo se o arquivo já existir")
    s.set_defaults(f=cmd_chat_vod)
    s = sub.add_parser("kick-assinar"); s.set_defaults(f=cmd_kick_assinar)
    s = sub.add_parser("kick-webhook"); s.set_defaults(f=cmd_kick_webhook)
    s = sub.add_parser("painel"); s.add_argument("--porta", type=int, default=8800); s.set_defaults(f=cmd_painel)
    s = sub.add_parser("enquadrar"); s.add_argument("canal"); s.add_argument("video")
    s.add_argument("--porta", type=int, default=8810); s.set_defaults(f=cmd_enquadrar)
    s = sub.add_parser("edit", help="edit de filme: gancho com fala + planos cortados na batida da música")
    s.add_argument("filme", help="arquivo do filme ou endereço do YouTube (é baixado antes)")
    s.add_argument("musica", help="arquivo da música ou endereço do YouTube (só o áudio é baixado)")
    s.add_argument("--qualidade-filme", choices=["1080", "720", "480", "melhor"],
                   help="com o filme no YouTube: até quantas linhas baixar (padrão 1080)")
    s.add_argument("--qualidade-musica", choices=["melhor", "192", "128"],
                   help="com a música no YouTube: kbps do mp3 (padrão melhor)")
    s.add_argument("--tema", help='dica para a IA, ex.: "o romance do Peter e da Gwen"')
    s.add_argument("--modelo", help="modelo de edit (modelos/<id>.yaml), ex.: honorable; veja `python -m cortes modelos`")
    s.add_argument("--trecho", help="só esta parte do filme, ex.: 1:20:00-1:42:00 (mais rápido e mais focado)")
    s.add_argument("--gancho", help="fala de gancho escolhida à mão, ex.: 1:23:10-1:23:19")
    s.add_argument("--drop", help="segundo da música (já tratada) onde os cortes começam")
    s.add_argument("--fala-drop", help="com --drop-filme: segundo do filme em que a fala do drop termina "
                   "(o som do filme segue por cima da música até ali, com legenda)")
    s.add_argument("--drop-fala", choices=["depois", "durante"],
                   help="fala do gatilho: depois = o drop entra quando ela acaba; durante = junto, com a música mais baixa")
    s.add_argument("--ritmo", choices=["rapido", "normal", "lento"], help="tamanho dos cortes (sem isso: o tema)")
    s.add_argument("--abertura", choices=["sim", "nao"],
                   help="falas do filme antes do gancho, sem música (sem isso: o tema)")
    s.add_argument("--drop-filme", help="momento do filme que cai no drop, ex.: 3:56 (o estalo); o gancho termina ali")
    s.add_argument("--proporcao", choices=["4:5", "9:16"], help="4:5 com tarjas (padrão do config) ou 9:16 tela cheia")
    s.add_argument("--slowed", type=float, help="velocidade da música: 1 = original, 0.85 = slowed")
    s.add_argument("--volume-musica", type=float,
                   help="volume da música sobre o nível padrão: 1 = padrão, 0.6 = mais baixa, 1.3 = mais alta")
    s.add_argument("--musica-no-gancho", choices=["sim", "nao"],
                   help="nao = música muda durante o gancho, entra só no drop (mais impacto)")
    s.add_argument("--duracao", type=float, help="segundos da parte cortada na batida (sem isso: o tema, depois o config)")
    s.add_argument("--idioma", help="idioma da fala do filme para o Whisper: pt (padrão), en, es... ou auto")
    s.add_argument("--transicoes", help="variadas (padrão), nenhuma, ou lista: zoom,flash,chicote,giro,fusao")
    s.add_argument("--sem-ia", action="store_true", help="escolhe gancho e planos sem a IA")
    s.add_argument("--so-planejar", action="store_true", help="grava o plano.json sem renderizar")
    s.add_argument("--prontos", action="store_true", help="copia o vídeo e a legenda para a pasta de prontos")
    s.set_defaults(f=cmd_edit)
    s = sub.add_parser("baixar-youtube", help="baixa um vídeo do YouTube para usar num edit")
    s.add_argument("url"); s.add_argument("--audio", action="store_true", help="só o áudio, em mp3 (para a música)")
    s.add_argument("--qualidade", help="vídeo: 1080 (padrão), 720, 480 ou melhor; áudio: melhor (padrão), 192 ou 128")
    s.set_defaults(f=cmd_baixar_youtube)
    s = sub.add_parser("modelos", help="lista os modelos de edit"); s.set_defaults(f=cmd_modelos)
    s = sub.add_parser("edit-render"); s.add_argument("plano")
    s.add_argument("--previa", action="store_true", help="prévia rápida em 540 px (previa.mp4), para conferir um ajuste")
    s.add_argument("--prontos", action="store_true", help="copia o vídeo e a legenda para a pasta de prontos")
    s.set_defaults(f=cmd_edit_render)
    s = sub.add_parser("processar")
    s.add_argument("canal"); s.add_argument("video")
    s.add_argument("--chat", nargs="*"); s.add_argument("--inicio", type=float)
    s.add_argument("--sem-render", action="store_true", help="só lista os momentos, sem baixar nem gerar vídeo")
    s.add_argument("--sem-whisper", action="store_true", help="não transcreve (mais rápido, sem legendas)")
    s.add_argument("--sem-ia", action="store_true", help="não usa a IA para filtrar e dar títulos")
    s.add_argument("--sem-tiktok", action="store_true", help="gera só os cortes curtos")
    s.set_defaults(f=cmd_processar)
    a = p.parse_args()
    a.f(config.carregar(), a)


if __name__ == "__main__":
    main()
