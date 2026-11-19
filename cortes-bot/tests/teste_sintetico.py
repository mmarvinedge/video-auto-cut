"""Teste ponta a ponta sem baixar nada: gera uma "live" falsa de 10 min com momentos conhecidos
e confere se o detector os encontra e se o corte vertical sai em 1080x1920.

  python tests/teste_sintetico.py
"""
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cortes import chat_twitch, config, detect, fala, ia, legendas, render  # noqa: E402

DURACAO = 600
MOMENTO_FORTE = 300      # grito + chat explodindo
MOMENTO_AUDIO = 450      # só grito
INICIO_VOD = 1_700_000_000.0


def gerar_video(destino: Path) -> None:
    vol = (f"volume='if(between(t,{MOMENTO_FORTE},{MOMENTO_FORTE + 6})+between(t,{MOMENTO_AUDIO},{MOMENTO_AUDIO + 5}),1.0,0.06)':eval=frame")
    subprocess.run([
        config.ffmpeg(), "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=15:duration={DURACAO}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.5:duration={DURACAO}:seed=7",
        "-af", vol, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-c:a", "aac", "-shortest", str(destino),
    ], check=True)


def gerar_chat(destino: Path) -> None:
    random.seed(1)
    falas = ["boa", "kkk", "que isso", "GTA 6 chegou", "salve", "lag?", "bora", "vai pro carro"]
    linhas = []
    for t in range(DURACAO):
        n = random.choices([0, 1, 2, 3], weights=[2, 4, 3, 1])[0]
        if MOMENTO_FORTE + 3 <= t <= MOMENTO_FORTE + 15:   # chat reage com atraso
            n += 14
            linhas += [{"ts": INICIO_VOD + t + random.random(), "user": f"u{i}", "text": random.choice(["KEKW", "kkkkkkk", "KEKW KEKW", "OMEGALUL"])} for i in range(n)]
            continue
        linhas += [{"ts": INICIO_VOD + t + random.random(), "user": f"u{i}", "text": random.choice(falas)} for i in range(n)]
    destino.write_text("\n".join(json.dumps(x) for x in linhas), encoding="utf-8")


def resolucao(video: Path) -> tuple[int, int]:
    err = subprocess.run([config.ffmpeg(), "-i", str(video)], capture_output=True, text=True).stderr
    m = re.search(r"Video:.*?(\d{3,4})x(\d{3,4})", err)
    return int(m.group(1)), int(m.group(2))


def main():
    # parser do IRC da Twitch
    linha = "@display-name=Fulano;tmi-sent-ts=1700000123456 :fulano!fulano@fulano.tmi.twitch.tv PRIVMSG #alanzoka :KEKW que isso"
    m = chat_twitch.parse_privmsg(linha)
    assert m == {"ts": 1700000123.456, "user": "Fulano", "text": "KEKW que isso"}, m
    assert chat_twitch.parse_privmsg(":tmi.twitch.tv PING") is None
    print("ok  parser do chat da Twitch")

    rel = config.relativo(config.RAIZ / "dados" / "alanzoka" / "cortes" / "x.mp4")
    assert rel == "dados/alanzoka/cortes/x.mp4" and config.absoluto(rel) == config.RAIZ / rel, rel
    print("ok  caminhos salvos relativos à pasta do projeto (sobrevivem se ela mudar de lugar)")

    cfg = config.carregar()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        video, chat = tmp / "live.mp4", tmp / "chat.jsonl"
        gerar_video(video)
        gerar_chat(chat)
        print("ok  live sintética gerada")

        msgs = detect.ler_chat([chat], INICIO_VOD, INICIO_VOD + DURACAO)
        cands, info = detect.detectar(video, msgs, INICIO_VOD, cfg)
        print(f"    {info} -> {[(c['inicio'], c['fim'], c['nota']) for c in cands]}")
        assert info["usou_chat"] and info["duracao"] == DURACAO
        cobre = lambda c, t: c["inicio"] <= t <= c["fim"]  # noqa: E731
        assert cobre(cands[0], MOMENTO_FORTE + 2), "o momento mais forte deveria ser o 1º candidato"
        assert any(cobre(c, MOMENTO_AUDIO + 2) for c in cands), "o momento só de áudio deveria aparecer"
        for c in cands:
            assert cfg["corte"]["duracao_min"] <= c["fim"] - c["inicio"] <= cfg["corte"]["duracao_max"], c
        print("ok  detecção encontrou os dois momentos, na ordem certa")

        cands_audio, _ = detect.detectar(video, None, None, cfg)
        assert any(cobre(c, MOMENTO_FORTE + 2) for c in cands_audio)
        print("ok  sem chat (só áudio) também funciona")

        c = cands[0]
        canal = cfg["canais"]["paulinholokobr"]
        for nome, facecam in [("fundo_desfocado", None), ("facecam", {"x": 1440, "y": 0, "w": 480, "h": 270})]:
            saida = config.RAIZ / "dados" / "_teste" / f"corte_{nome}.mp4"
            render.renderizar(video, c["inicio"], c["fim"], saida, {**canal, "facecam": facecam})
            assert resolucao(saida) == (1080, 1920), resolucao(saida)
            print(f"ok  corte vertical ({nome}) 1080x1920 -> {saida.relative_to(config.RAIZ)}")

        # fala: nota, bordas e legenda queimada no vídeo
        ini = c["inicio"]
        palavras = [{"w": w, "s": ini + 2 + k * 0.4, "e": ini + 2.3 + k * 0.4}
                    for k, w in enumerate("Caralho, nossa! Eu morri, chat. Meu Deus kkkkk".split())]
        n = fala.nota_fala(palavras, ini, c["fim"], cfg["whisper"]["reacoes"])
        assert n["reacoes"] >= 4 and n["risadas"] == 1 and n["exclamacoes"] == 1, n
        assert fala.nota_fala([], ini, c["fim"], [])["bruto"] < 0
        novo_ini, novo_fim = fala.ajustar_bordas(palavras, ini + 3, ini + 4.5)
        assert novo_ini < ini + 3 and novo_fim > ini + 4.5, (novo_ini, novo_fim)
        print(f"ok  nota da fala {n} e bordas ajustadas à frase")
        saida = config.RAIZ / "dados" / "_teste" / "corte_legenda.mp4"
        ass = legendas.gerar_ass(palavras, ini, c["fim"], saida.with_suffix(".ass"), 640)
        render.renderizar(video, ini, c["fim"], saida, {**canal, "facecam": {"x": 1440, "y": 0, "w": 480, "h": 270}}, ass)
        assert resolucao(saida) == (1080, 1920)
        print(f"ok  corte com legenda -> {saida.relative_to(config.RAIZ)}")

        # re-render com o tempo errado (fora do arquivo): o ffmpeg "termina bem" com um mp4 vazio,
        # e antes isso substituía o corte bom
        antes = saida.stat().st_size
        try:
            render.renderizar(video, DURACAO + 50, DURACAO + 60, saida, canal)
            raise AssertionError("render fora do vídeo deveria falhar")
        except (RuntimeError, subprocess.CalledProcessError):
            pass
        assert saida.stat().st_size == antes and not saida.with_name(saida.stem + ".tmp.mp4").exists()
        print("ok  render fora do vídeo falha sem apagar o corte que já existia")

        # IA (sem chamar a API): transcrição enviada e aplicação da avaliação
        txt = ia._frases(palavras, ini, c["fim"])
        assert txt.startswith("[00:02] Caralho, nossa!") and "\n" in txt, txt
        cs = [{"id": "c0", "inicio": 100.0, "fim": 150.0, "nota": 3.0}, {"id": "c1", "inicio": 300.0, "fim": 330.0, "nota": 5.0}]
        av = {
            "c0": ia.Avaliacao(id="c0", aprovar=True, nota=9, aparar_inicio=5, aparar_fim=3, titulo="T", descricao="D", hashtags=["gta6"], motivo="bom"),
            "c1": ia.Avaliacao(id="c1", aprovar=False, nota=2, aparar_inicio=0, aparar_fim=15, titulo="X", descricao="", hashtags=[], motivo="pede like"),
        }
        ia.aplicar(cs, av, duracao_min=20)
        assert cs[0]["id"] == "c0" and cs[0]["ia"]["nota"] == 9 and (cs[0]["inicio"], cs[0]["fim"]) == (105.0, 147.0), cs[0]
        assert cs[1]["descartado"] == "IA: pede like" and cs[1]["fim"] == 330.0, cs[1]  # não aparou abaixo de 20s
        print("ok  IA: transcrição formatada, aprovação, aparo e reordenação")

        # TikTok: trechos longos (atividade sustentada), compilações da IA e automática, junção de vídeos
        nota = np.zeros(600)
        nota[100:190] = 1.5          # 90s de atividade sustentada
        nota[400] = 9.0              # pico isolado: bom para curto, ruim para longo
        longos = detect.candidatos_longos(nota, cfg)
        assert longos and longos[0]["inicio"] <= 110 and longos[0]["fim"] >= 180, longos
        assert all(not (l["inicio"] <= 400 < l["fim"]) for l in longos), "pico isolado não deveria virar longo"
        print(f"ok  trechos longos: {[(l['inicio'], l['fim'], l['nota']) for l in longos]}")

        curtos = [{"id": f"c{i}", "inicio": 100.0 * i, "fim": 100.0 * i + d, "nota": 5 - i,
                   "ia": {"aprovar": i != 3}} for i, d in enumerate([30, 25, 40, 30, 50])]
        comps = ia.montar_compilacoes(curtos, [
            ia.Compilacao(ids=["c0", "c1", "c2"], titulo="mortes", descricao="", hashtags=[], motivo=""),   # 95s ok
            ia.Compilacao(ids=["c2", "c4"], titulo="repetido", descricao="", hashtags=[], motivo=""),       # c2 já usado
            ia.Compilacao(ids=["c3", "c4"], titulo="reprovado", descricao="", hashtags=[], motivo=""),      # c3 reprovado
        ], cfg)
        assert [c["partes"] for c in comps] == [["c0", "c1", "c2"]] and comps[0]["duracao"] == 95, comps
        print("ok  compilações da IA validadas (duração, repetição, só aprovados)")

        prontos = [{"id": f"c{i}", "inicio": t, "fim": t + 30, "nota": n, "arquivo": "x.mp4"}
                   for i, (t, n) in enumerate([(500, 1), (100, 9), (300, 7), (200, 3)])]
        auto = __import__("cortes.__main__", fromlist=["x"]).compilacao_automatica(prontos, cfg)
        # escolhe as 3 maiores notas (c1, c2, c3) e põe na ordem da live: c1 (100s), c3 (200s), c2 (300s)
        assert auto and auto[0]["partes"] == ["c1", "c3", "c2"] and auto[0]["duracao"] == 90, auto
        print("ok  compilação automática (sem IA): maiores notas, ordem da live")

        juntos = render.concatenar([config.RAIZ / "dados" / "_teste" / "corte_legenda.mp4",
                                    config.RAIZ / "dados" / "_teste" / "corte_facecam.mp4"],
                                   config.RAIZ / "dados" / "_teste" / "compilacao.mp4")
        assert resolucao(juntos) == (1080, 1920)
        err = subprocess.run([config.ffmpeg(), "-i", str(juntos)], capture_output=True, text=True).stderr
        dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
        segundos = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
        esperado = 2 * (c["fim"] - c["inicio"])
        assert abs(segundos - esperado) < 1.5, (segundos, esperado)
        print(f"ok  compilação renderizada: {segundos:.0f}s (2 partes)")
    print("\nTudo certo.")


if __name__ == "__main__":
    main()
