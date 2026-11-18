"""Linha de comando do bot de cortes.

  python -m cortes vods <canal>                       lista os últimos VODs
  python -m cortes baixar <canal> <url_do_vod>        baixa o VOD inteiro (+ info com horário de início)
  python -m cortes baixar-audio <canal> <url_do_vod>  baixa só o áudio (bem mais leve; basta para processar)
  python -m cortes chat-twitch                        grava o chat ao vivo de todos os canais Twitch
  python -m cortes kick-assinar                       inscreve os canais Kick no webhook de chat (API oficial)
  python -m cortes kick-webhook                       recebe o chat do Kick via webhook
  python -m cortes processar <canal> <video.mp4>      gera as duas versões: curtos (Shorts/Reels) e TikTok (>1 min)
  python -m cortes painel                             abre o painel de revisão em http://localhost:8800
  python -m cortes enquadrar <canal> <video.mp4>      escolhe na tela o recorte da cam e do conteúdo
"""
import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import chat_twitch, config, detect, legendas, render, vod


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
    painel.servir(config.RAIZ / cfg["pasta_dados"], a.porta)


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
        c["fala"] = fala.nota_fala(c["palavras"], c["inicio"], c["fim"], w["reacoes"])
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
    canal = config.canal(cfg, a.canal)
    pasta = config.pasta_canal(cfg, a.canal)
    video = Path(a.video)
    base = video.stem.removesuffix("_audio")
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
    s = sub.add_parser("kick-assinar"); s.set_defaults(f=cmd_kick_assinar)
    s = sub.add_parser("kick-webhook"); s.set_defaults(f=cmd_kick_webhook)
    s = sub.add_parser("painel"); s.add_argument("--porta", type=int, default=8800); s.set_defaults(f=cmd_painel)
    s = sub.add_parser("enquadrar"); s.add_argument("canal"); s.add_argument("video")
    s.add_argument("--porta", type=int, default=8810); s.set_defaults(f=cmd_enquadrar)
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
