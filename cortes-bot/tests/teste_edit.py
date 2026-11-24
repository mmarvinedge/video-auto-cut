"""Teste do edit de filme sem filme nem música de verdade e sem IA/Whisper:

- uma música sintética a 100 BPM, baixinha até 20s e alta depois (o drop);
- um "filme" de 60s com um corte de câmera a cada 4s (cor de fundo trocando);
- confere andamento, batidas, drop, cortes de câmera, o plano e o vídeo final (1080x1920, duração).

  python tests/teste_edit.py
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cortes import batidas, cenas, config, edit  # noqa: E402

BPM, PRIMEIRA, DROP = 100, 0.3, 20.0
PERIODO = 60 / BPM
TROCA = 4.0          # segundos entre os cortes de câmera do filme falso


def gerar_musica(destino: Path) -> None:
    bumbo = f"sin(2*PI*55*t)*exp(-mod(t-{PRIMEIRA},{PERIODO})*18)*gte(t,{PRIMEIRA})"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"aevalsrc='if(lt(t,{DROP}),0.2,1)*{bumbo}+if(lt(t,{DROP}),0.04,0.25)*sin(2*PI*220*t)'"
                    ":s=44100:d=50", str(destino)], check=True)


def gerar_filme(destino: Path) -> None:
    # claras e escuras alternadas: duas cores de brilho parecido quase não mexem na nota de cena
    cores = ["red", "white", "blue", "yellow", "black", "cyan", "navy", "pink", "maroon", "lime",
             "purple", "white", "darkgreen", "orange", "black"]
    entradas, rotulos = [], ""
    for i, c in enumerate(cores):
        entradas += ["-f", "lavfi", "-i", f"color=c={c}:s=1280x720:r=30:d={TROCA}"]
        rotulos += f"[{i}:v]"
    n = len(cores)
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", *entradas,
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={n * TROCA}",
                    "-filter_complex", f"{rotulos}concat=n={n}:v=1:a=0,"
                    f"drawtext=fontfile='{cenas.FONTE}':text='%{{pts\\:hms}}':fontsize=90:x=500:y=300[v]",
                    "-map", "[v]", "-map", f"{n}:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(destino)], check=True)


def main():
    pasta = Path(tempfile.mkdtemp(prefix="teste_edit_"))
    musica, filme = pasta / "musica.wav", pasta / "filme.mp4"
    gerar_musica(musica)
    gerar_filme(filme)

    # música: andamento, batidas no lugar e drop
    mus = batidas.analisar(musica)
    assert abs(mus["bpm"] - BPM) < 1.5, mus["bpm"]
    bt = np.array(mus["batidas"])
    erro = np.abs((bt - PRIMEIRA) / PERIODO - np.round((bt - PRIMEIRA) / PERIODO)) * PERIODO
    assert erro.mean() < 0.015, f"batidas fora do lugar: erro médio {erro.mean():.3f}s"
    i_drop = batidas.achar_drop(np.array(mus["energia"]), bt, antes=5, depois=12)
    assert abs(bt[i_drop] - DROP) < PERIODO, f"drop em {bt[i_drop]}, esperado ~{DROP}"
    print(f"ok  música: {mus['bpm']} BPM, drop em {bt[i_drop]:.2f}s")

    # slowed: o andamento cai na mesma proporção
    lenta = batidas.analisar(batidas.preparar(musica, pasta / "lenta.wav", 0.85, True))
    assert abs(lenta["bpm"] - BPM * 0.85) < 1.5, lenta["bpm"]
    print(f"ok  slowed: {lenta['bpm']} BPM")

    # cortes de câmera
    cs = cenas.detectar(filme)
    achados = [c["inicio"] for c in cs[1:]]
    esperados = [TROCA * k for k in range(1, 15)]
    assert len(achados) == len(esperados) and max(abs(a - b) for a, b in zip(achados, esperados)) < 0.1, achados
    print(f"ok  cenas: {len(cs)} planos")

    # corte fraco (cena escura): pico isolado de 0,15 conta; movimento de câmera (0,15 por 1 s) não
    tempos = np.arange(0, 6, 1 / 24)
    notas = np.full(len(tempos), 0.01)
    notas[48] = 0.15                                   # corte em 2,0 s
    notas[96:120] = 0.15                               # chicote de câmera de 4,0 a 5,0 s
    achados = cenas._escolher_cortes(tempos, notas)
    assert achados == [tempos[48]], achados
    print("ok  corte fraco: pico isolado sim, movimento não")

    # tarjas pretas: vídeo 2,39:1 dentro de um 16:9
    tarjado = pasta / "tarjado.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x536:r=24:d=4",
                    "-vf", "pad=1280:720:0:92:black", "-c:v", "libx264", "-preset", "ultrafast", str(tarjado)],
                   check=True)
    caixa = cenas.tarja(tarjado, amostras=4)
    assert caixa and abs(caixa[1] - 536) <= 4 and abs(caixa[3] - 92) <= 4, caixa
    assert cenas.tarja(filme, amostras=4) is None
    assert cenas._recorte(1280, 720, 0.8, caixa).startswith(f"crop={caixa[0]}:{caixa[1]}:")
    print(f"ok  tarja: {caixa}")

    # clarão (o estalo) ou tela preta no momento do drop não servem de primeiro plano
    clarao = pasta / "clarao.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=640x360:r=24:d=2",
                    "-c:v", "libx264", "-preset", "ultrafast", str(clarao)], check=True)
    assert not cenas.imagem_util(clarao, 0.5)
    assert cenas.imagem_util(tarjado, 1.0, caixa)
    print("ok  clarão no drop: recusado; imagem normal: aceita")

    # pontos de corte na batida, dentro dos limites
    pontos = batidas.cortes_na_batida(mus["batidas"], float(bt[i_drop]), 10, 0.55, 1.6)
    passos = np.diff(pontos)
    assert all(0.55 <= p <= 1.6 for p in passos), passos
    assert abs(pontos[-1] - pontos[0] - 10) <= passos.max(), pontos

    # plano montado à mão (no lugar da IA e do Whisper) e render
    g_ini, g_dur = 2.0, 3.0
    palavras = [{"w": "Você", "s": 2.1, "e": 2.4}, {"w": "é", "s": 2.4, "e": 2.5}, {"w": "o", "s": 2.5, "e": 2.6},
                {"w": "Peter,", "s": 2.6, "e": 3.1}, {"w": "não", "s": 3.4, "e": 3.7}, {"w": "é?", "s": 3.7, "e": 4.2}]
    cortes = edit.montar_cortes(pontos, float(bt[i_drop]), g_dur, cs[2:], 0.85)
    assert cortes[0]["transicao"] == "flash", cortes[0]
    assert all(c["transicao"] in edit.TRANSICOES for c in cortes)
    secos = edit.montar_cortes(pontos, float(bt[i_drop]), g_dur, cs[2:], 0.85, [])
    assert {c["transicao"] for c in secos} == {"corte"}

    # escolha das transições: fusão só em corte longo e com filme sobrando no plano anterior
    todas = list(edit.PADRAO["transicoes"])
    assert edit._transicao(3, 1.2, todas, True) == "fusao"
    assert edit._transicao(3, 1.2, todas, False) != "fusao"
    assert edit._transicao(3, 0.6, todas, True) != "fusao"
    assert edit.ler_transicoes("nenhuma") == [] and edit.ler_transicoes("variadas") == todas
    assert edit.ler_transicoes("zoom, giro") == ["zoom", "giro"]
    try:
        edit.ler_transicoes("zoom,explosao")
        raise AssertionError("aceitou uma transição que não existe")
    except ValueError:
        pass
    print("ok  transições: escolha e opções")

    # filme e música do computador ou do YouTube (com a qualidade do download), sem rede
    from cortes import painel_edit, youtube
    url = "https://www.youtube.com/watch?v=abc123XYZ"
    args, titulo = painel_edit.argumentos({"filme": url, "filme_de": "youtube", "filme_qualidade": "720",
                                           "musica": str(musica)})
    assert args[:3] == ["edit", url, str(musica)] and "--qualidade-filme=720" in args and "YouTube" in titulo, args
    args, _ = painel_edit.argumentos({"filme": str(filme), "musica": url, "musica_de": "youtube"})
    assert args[2] == url and "--qualidade-musica=melhor" in args, args
    for ruim in ({"filme": url, "filme_de": "youtube", "filme_qualidade": "4k", "musica": str(musica)},
                 {"filme": "nao é endereço", "filme_de": "youtube", "musica": str(musica)},
                 {"filme": str(pasta / "nao_existe.mp4"), "musica": str(musica)}):
        try:
            painel_edit.argumentos(ruim)
            raise AssertionError(f"aceitou {ruim}")
        except ValueError:
            pass
    baixados = []
    original_baixar = youtube.baixar
    youtube.baixar = lambda u, audio, destino, aviso=print, q=None: baixados.append((u, audio, q)) or Path("baixado.mp3")
    try:
        assert youtube.resolver(str(filme), False, None, {"pasta_dados": str(pasta)}) == filme and not baixados
        assert youtube.resolver(url, True, "192", {"pasta_dados": str(pasta)}, aviso=lambda *a: None) == Path("baixado.mp3")
        assert baixados == [(url, True, "192")], baixados
    finally:
        youtube.baixar = original_baixar
    assert youtube._sufixo("1080", False) == "" and youtube._sufixo("720", False) == " [720p]"
    assert youtube._sufixo("melhor", True) == "" and youtube._sufixo("128", True) == " [128k]"
    print("ok  filme e música do computador ou do YouTube, com a qualidade do download")

    # plano longo usado mais de uma vez: cada uso pega outro pedaço, sem repetir imagem
    longo = {"id": 99, "inicio": 100.0, "fim": 112.0}
    repetidos = edit.montar_cortes([0, 1, 2, 3], 0, 0, [longo], 0.85)
    pedacos = sorted((c["fonte"], c["fonte"] + c["dur"] * c["vel"]) for c in repetidos)
    assert len(repetidos) == 3 and all(b0 <= a1 for (_, b0), (a1, _) in zip(pedacos, pedacos[1:])), pedacos
    assert all(100 <= a0 and b0 <= 112 for a0, b0 in pedacos), pedacos
    # o pedaço que o gancho já mostrou não volta depois do drop
    depois = edit.montar_cortes([0, 1], 0, 0, [longo], 0.85, ocupado=(100.0, 106.0))
    assert depois[0]["fonte"] >= 106.0, depois

    # drop num momento do filme (o estalo em 236,3): o primeiro corte começa nele, mesmo passando do
    # fim do plano, e o gancho termina ali (estica o silêncio antes; corta palavra que viria depois)
    estalo = {"id": 93, "inicio": 236.3, "fim": 237.0}
    outro = {"id": 5, "inicio": 10.0, "fim": 20.0}
    com_drop = edit.montar_cortes([0, 1.0, 2.0], 0, 5.0, [outro], 0.85, primeiro=(estalo, 236.3))
    assert com_drop[0]["cena"] == 93 and com_drop[0]["fonte"] == 236.3 and com_drop[0]["transicao"] == "zoom"
    assert com_drop[1]["cena"] == 5, com_drop
    fala = [{"w": "Sou...", "s": 231.0, "e": 231.8}, {"w": "Ferro.", "s": 235.2, "e": 235.9},
            {"w": "depois", "s": 237.0, "e": 237.4}]
    g0 = {"inicio": 230.8, "fim": 236.2, "palavras": fala[:2]}
    assert edit._gancho_ate(g0, 236.3, 40)["fim"] == 236.3
    g1 = edit._gancho_ate({"inicio": 230.8, "fim": 237.8, "palavras": fala}, 236.3, 40)
    assert g1["fim"] == 236.3 and [p["w"] for p in g1["palavras"]] == ["Sou...", "Ferro."]
    assert edit._gancho_ate(g0, 300.0, 40) == g0          # longe demais: não mexe
    assert edit._gancho_ate({"inicio": 0, "fim": 0, "palavras": []}, 5.0, 40)["fim"] == 0
    print("ok  drop no momento do filme e gancho até ele")

    # Whisper sem filtro de voz: o que ele inventa na trilha sai, a fala fica
    from types import SimpleNamespace as Seg
    from cortes import transcrever
    bom = dict(compression_ratio=1.2, no_speech_prob=0.01, avg_logprob=-0.3)
    assert not transcrever._inventado(Seg(text=" And I... am... Iron Man.", **bom))
    for texto in (" Thank you.", " BIRDS CHILDREN", " [Música]", " ♪ la la ♪", " Legendas pela comunidade Amara.org"):
        assert transcrever._inventado(Seg(text=texto, **bom)), texto
    assert transcrever._inventado(Seg(text=" hmm", compression_ratio=1.0, no_speech_prob=0.9, avg_logprob=-1.5))
    print("ok  planos sem repetir trecho; falas inventadas filtradas")
    assert edit.ler_idioma(" EN ") == "en" and edit.ler_idioma("auto") == "auto"
    for ruim in ("inglês", "", "en;rm"):
        try:
            edit.ler_idioma(ruim)
            raise AssertionError(f"aceitou o idioma {ruim!r}")
        except ValueError:
            pass

    # o render passa por todas as transições, em ordem
    for i, c in enumerate(cortes):
        c["transicao"] = edit.TRANSICOES[i % len(edit.TRANSICOES)]
    ce = edit.cfg_edit({})
    plano = {
        "filme": str(filme), "musica": str(musica), "bpm": mus["bpm"], "drop": float(bt[i_drop]),
        "musica_inicio": float(bt[i_drop]) - g_dur,
        "gancho": {"inicio": g_ini, "fim": g_ini + g_dur, "palavras": palavras},
        "cortes": cortes, "duracao": round(g_dur + pontos[-1] - pontos[0], 3),
        "titulo": "Teste", "descricao": "", "hashtags": ["edit"],
        "estilo": {k: ce[k] for k in ("proporcao", "volume_gancho", "legenda_cor", "legenda_clara", "legenda_y", "cor")},
    }
    arq = pasta / "edit" / "plano.json"
    arq.parent.mkdir()
    arq.write_text(json.dumps(plano, ensure_ascii=False), encoding="utf-8")
    video = edit.renderizar(arq)
    info = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True).stderr
    assert "1080x1920" in info, info
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info).groups()
    assert abs(float(s) + 60 * int(m) - plano["duracao"]) < 0.1, (s, plano["duracao"])
    assert video.with_suffix(".txt").exists()
    assert not list(arq.parent.glob("*.filtro.txt")), "o arquivo do filtro ficou para trás"
    assert "PETER" in (arq.parent / "gancho.ass").read_text(encoding="utf-8")
    print(f"ok  render: {video} ({plano['duracao']:.1f}s, {len(cortes)} cortes)")

    # cada corte seco cai no quadro da batida (a fusão e o flash são graduais: ficam de fora).
    # A fusão estica o plano anterior; se o xfade escorregasse um quadro, todo o resto atrasaria.
    bruto = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(video), "-vf", "scale=64:112",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    q = np.frombuffer(bruto, np.uint8).reshape(-1, 112, 64).astype(np.float32)
    dif = np.r_[0, np.abs(np.diff(q, axis=0)).mean(axis=(1, 2))]
    for c in cortes:
        if c["transicao"] in ("fusao", "flash"):
            continue
        k = round(c["saida"] * edit.FPS)
        assert dif[k] == dif[k - 2:k + 3].max() and dif[k] > 15, (c, dif[k - 3:k + 4].round(1))
    print(f"ok  cortes na batida: {sum(c['transicao'] not in ('fusao', 'flash') for c in cortes)} conferidos")

    # música muda no gancho: as duas versões diferem só antes do drop (a música baixinha que uma
    # tem e a outra não); depois do drop o som é o mesmo
    def audio(v):
        bruto = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(v), "-vn", "-ac", "1", "-ar", "16000",
                                "-f", "f32le", "-"], capture_output=True).stdout
        return np.frombuffer(bruto, np.float32)
    plano_mudo = dict(plano, estilo=dict(plano["estilo"], musica_no_gancho=False))
    arq3 = pasta / "mudo" / "plano.json"
    arq3.parent.mkdir()
    arq3.write_text(json.dumps(plano_mudo, ensure_ascii=False), encoding="utf-8")
    video3 = edit.renderizar(arq3)
    x, y = audio(video), audio(video3)
    n = min(len(x), len(y))
    dif = np.abs(x[:n] - y[:n])
    antes = float(dif[int(0.3 * 16000):int((g_dur - 0.4) * 16000)].mean())
    depois = float(dif[int((g_dur + 0.5) * 16000):int((g_dur + 3) * 16000)].mean())
    assert antes > 5 * depois, (antes, depois)
    print(f"ok  música muda no gancho: diferença {antes:.4f} antes do drop, {depois:.4f} depois")

    # filme sem fala: sem gancho, o edit abre direto no drop (antes o render quebrava com o gancho 0–0)
    assert edit._gancho_heuristico([], ce, None)["fim"] == 0
    assert edit._encaixar_gancho([], 0.0, 0.0, ce)["fim"] == 0
    sem = dict(plano, gancho={"inicio": 0.0, "fim": 0.0, "palavras": []}, musica_inicio=float(bt[i_drop]),
               duracao=round(pontos[-1] - pontos[0], 3),
               cortes=[dict(c, saida=round(c["saida"] - g_dur, 3)) for c in cortes])
    arq2 = pasta / "sem_gancho" / "plano.json"
    arq2.parent.mkdir()
    arq2.write_text(json.dumps(sem, ensure_ascii=False), encoding="utf-8")
    video2 = edit.renderizar(arq2)
    info2 = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(video2)], capture_output=True, text=True).stderr
    h, m, s2 = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info2).groups()
    assert abs(float(s2) + 60 * int(m) - sem["duracao"]) < 0.1, (s2, sem["duracao"])
    assert not (arq2.parent / "gancho.ass").exists()
    print(f"ok  sem gancho: {sem['duracao']:.1f}s, abre no drop")

    # planejamento completo, sem IA nem Whisper (falas de mentira): abertura com duas falas, ritmo
    # rápido e a fala "A mim, X-Men!" em cima do drop. O filme tem um seno de 300 Hz; a música,
    # 55 e 220 Hz: dá para ver no som quem está tocando em cada parte.
    falas = [{"w": "A", "s": 10.2, "e": 10.4}, {"w": "hora", "s": 10.4, "e": 10.7}, {"w": "chegou.", "s": 10.7, "e": 11.2},
             {"w": "Agrupem-se", "s": 14.1, "e": 14.8}, {"w": "agora.", "s": 14.8, "e": 15.3},
             {"w": "Vamos", "s": 30.2, "e": 30.6}, {"w": "começar.", "s": 30.6, "e": 31.4},
             {"w": "A", "s": 33.1, "e": 33.3}, {"w": "mim,", "s": 33.3, "e": 33.7}, {"w": "X-Men!", "s": 33.8, "e": 34.6}]
    original = edit.analisar_filme, cenas.imagem_util
    edit.analisar_filme = lambda *a, **k: (cs, falas, pasta / "planos_falsos.json", None)
    cenas.imagem_util = lambda *a, **k: True              # cor lisa não tem contraste; testado à parte
    try:
        arq4 = edit.planejar(filme, musica, {"pasta_dados": str(pasta / "dados"), "edit": {}}, gancho="30-33",
                             drop_filme=33.0, fala_drop=34.6, ritmo="rapido", abertura=True, duracao=8, drop_fala="durante",
                             usar_ia=False, aviso=lambda *a: None)
    finally:
        edit.analisar_filme, cenas.imagem_util = original
    p4 = json.loads(arq4.read_text(encoding="utf-8"))
    batida = 60 / p4["bpm"]
    a_dur, g4 = p4["abertura_dur"], p4["gancho"]
    g4_dur = g4["fim"] - g4["inicio"]
    t_drop4 = a_dur + g4_dur
    ab = p4["abertura_falas"]
    assert [" ".join(w["w"] for w in f["palavras"]) for f in ab] == ["A hora chegou.", "Agrupem-se agora."], ab
    assert abs(a_dur - sum(f["fim"] - f["inicio"] for f in ab)) < 0.05, a_dur
    assert abs(g4["fim"] - 33.0) < 1 / edit.FPS and [w["w"] for w in g4["palavras"]] == ["Vamos", "começar."], g4
    c0 = p4["cortes"][0]
    assert c0["fonte"] == 33.0 and c0["vel"] == 1.0 and c0["dur"] >= 34.6 - 33.0 + 0.25, c0
    assert all(abs(c["dur"] - batida) < 0.05 for c in p4["cortes"][1:-1]), [c["dur"] for c in p4["cortes"]]
    assert [w["w"] for w in p4["fala_drop"]["palavras"]] == ["A", "mim,", "X-Men!"]

    video4 = edit.renderizar(arq4)
    info4 = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(video4)], capture_output=True, text=True).stderr
    h, m, s4 = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info4).groups()
    assert abs(float(s4) - p4["duracao"]) < 0.1, (s4, p4["duracao"])
    assert "MIM" in (arq4.parent / "gancho.ass").read_text(encoding="utf-8"), "faltou a legenda da fala do drop"

    som = audio(video4)

    def banda(a0, a1, hz):
        x = som[int(a0 * 16000):int(a1 * 16000)]
        f = np.abs(np.fft.rfft(x)) / max(len(x), 1)
        fr = np.fft.rfftfreq(len(x), 1 / 16000)
        return float(f[(fr > hz * 0.93) & (fr < hz * 1.07)].sum())

    filme_hz, musica_hz = 300, 220 * 0.85                  # a música foi deixada lenta (0,85)
    abre = (banda(0.15, a_dur - 0.15, filme_hz), banda(0.15, a_dur - 0.15, musica_hz))
    gan = (banda(a_dur + 0.3, t_drop4 - 0.4, filme_hz), banda(a_dur + 0.3, t_drop4 - 0.4, musica_hz))
    fala4 = banda(t_drop4 + 0.2, t_drop4 + 1.4, filme_hz)
    depois4 = banda(t_drop4 + c0["dur"] + 0.3, t_drop4 + c0["dur"] + 2.0, filme_hz)
    assert abre[0] > 5 * abre[1], ("a abertura devia ser só o filme falando, sem música", abre)
    assert "AGRUPEM" in (arq4.parent / "gancho.ass").read_text(encoding="utf-8"), "faltou a legenda da abertura"
    assert gan[0] > 5 * gan[1], ("gancho com música (devia parar seco)", gan)
    assert fala4 > 5 * depois4, ("a fala não segue por cima do drop", fala4, depois4)
    # drop durante a fala: a música fica abafada (ABAFA) debaixo dela e sobe quando ela acaba
    mus_fala = banda(t_drop4 + 0.2, t_drop4 + 1.4, musica_hz)
    mus_depois = banda(t_drop4 + c0["dur"] + 0.6, t_drop4 + c0["dur"] + 1.8, musica_hz)
    assert mus_fala < 0.5 * mus_depois, ("música alta demais debaixo da fala do drop", mus_fala, mus_depois)

    bruto4 = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(video4), "-vf", "scale=64:112",
                             "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    q4 = np.frombuffer(bruto4, np.uint8).reshape(-1, 112, 64).astype(np.float32)
    dif4 = np.r_[0, np.abs(np.diff(q4, axis=0)).mean(axis=(1, 2))]
    # cortes secos entre as falas e para o gancho (cores de brilho parecido: o pico é menor, mas é ali)
    for k in (round((ab[0]["fim"] - ab[0]["inicio"]) * edit.FPS), round(a_dur * edit.FPS)):
        assert dif4[k] == dif4[k - 2:k + 3].max() and dif4[k] > 5, dif4[k - 3:k + 4].round(1)
    # emendas da abertura sem buraco no som: o seno do filme é contínuo, então o nível em volta do
    # corte entre as falas não pode cair (antes caía a -40 dB, porque cada fala sumia antes do corte)
    def db(a0, a1):
        x = som[int(a0 * 16000):int(a1 * 16000)]
        return 20 * np.log10(float(np.sqrt((x ** 2).mean())) + 1e-9)
    corte_ab = (ab[0]["fim"] - ab[0]["inicio"])
    janelas = [db(corte_ab + k * 0.04, corte_ab + (k + 1) * 0.04) for k in range(-5, 5)]
    assert min(janelas) > max(janelas) - 6, ("buraco no som na emenda da abertura", [round(j) for j in janelas])

    # música nivelada: depois da fala do drop ela fica perto de MUSICA_DB, e o volume_musica multiplica
    fim_fala = t_drop4 + c0["dur"] + 0.5
    nivel = db(fim_fala, p4["duracao"] - 1.5)
    assert abs(nivel - edit.MUSICA_DB) < 3, ("música fora do nível", nivel)
    mus4 = str(config.absoluto(p4["musica"]))
    g1, g05 = edit._ganho_musica(mus4, p4["drop"], 5, 1.0), edit._ganho_musica(mus4, p4["drop"], 5, 0.5)
    assert abs(g05 / g1 - 0.5) < 1e-6, (g1, g05)

    # frase inteira: o fim marcado uma palavra antes ("E lutem") pega o "juntos."
    frase = [{"w": "E", "s": 50.0, "e": 50.2}, {"w": "lutem", "s": 50.2, "e": 50.6}, {"w": "juntos.", "s": 50.65, "e": 51.2},
             {"w": "Depois", "s": 53.0, "e": 53.4}]
    inteira = edit._encaixar_gancho(frase, 50.0, 50.6, dict(ce, gancho_min=0.5))
    assert [w["w"] for w in inteira["palavras"]] == ["E", "lutem", "juntos."], inteira
    print(f"ok  emendas sem buraco ({min(janelas):.0f}..{max(janelas):.0f} dB), música a {nivel:.1f} dB, frase inteira")
    # ajuste depois de pronto (a tela do painel): refaz o plano sem IA, guarda o anterior e desfaz
    (pasta / "falas_falsos_pt.json").write_text(json.dumps(falas, ensure_ascii=False), encoding="utf-8")
    cenas.imagem_util = lambda *a, **k: True
    try:
        aj = edit.replanejar(arq4, {"gancho": [30.0, 32.5], "drop_filme": 33.0, "fala_fim": 34.6,
                                    "drop_fala": "depois", "drop_musica": None}, aviso=lambda *a: None)
        assert aj["fala_drop"] is None and abs(aj["gancho"]["fim"] - 34.85) < 1 / edit.FPS, aj["gancho"]
        assert aj["cortes"][0]["fonte"] == 34.85 and aj["titulo"] == p4["titulo"], aj["cortes"][0]
        assert aj["gatilho"] == {"momento": 33.0, "fala_fim": 34.6, "modo": "depois"}, aj["gatilho"]
        assert (arq4.parent / "plano.anterior.json").exists()
        edit.desfazer_ajuste(arq4)
        assert json.loads(arq4.read_text(encoding="utf-8"))["fala_drop"] is not None    # voltou o "durante"
        alvo = p4["drop"] + 2 * batida
        aj2 = edit.replanejar(arq4, {"gancho": [30.0, 32.5], "drop_filme": 33.0, "fala_fim": 34.6,
                                     "drop_fala": "durante", "drop_musica": alvo + 0.05}, aviso=lambda *a: None)
        assert abs(aj2["drop"] - alvo) < 0.05, (aj2["drop"], alvo)
        vol = edit.replanejar(arq4, {"gancho": [30.0, 32.5], "drop_filme": 33.0, "fala_fim": 34.6,
                                     "drop_fala": "durante", "drop_musica": alvo, "volume_musica": 0.5},
                              aviso=lambda *a: None)
        assert vol["estilo"]["volume_musica"] == 0.5 and vol["drop"] == aj2["drop"], vol["estilo"]
        # ajustes gerais (aba Geral): ritmo, duração, transições, abertura e música no gancho
        geral = edit.replanejar(arq4, {"gancho": [30.0, 32.5], "drop_filme": None, "fala_fim": None, "drop_fala": "depois",
                                       "drop_musica": None, "ritmo": "lento", "duracao_musica": 9, "transicoes": [],
                                       "abertura": False, "musica_no_gancho": False}, aviso=lambda *a: None)
        durs = [c["dur"] for c in geral["cortes"]]
        assert all(1.3 <= x <= 3.3 for x in durs[:-1]), durs                 # lento: planos longos
        assert {c["transicao"] for c in geral["cortes"]} == {"corte"}, geral["cortes"]
        assert geral["abertura_falas"] == [] and geral["estilo"]["musica_no_gancho"] is False
        musica_parte = geral["duracao"] - geral["abertura_dur"] - (geral["gancho"]["fim"] - geral["gancho"]["inicio"])
        assert abs(musica_parte - 9) < 2.5 and geral["ritmo"] == "lento", (musica_parte, geral["ritmo"])
        com_ab = edit.replanejar(arq4, {"gancho": [30.0, 32.5], "drop_filme": None, "fala_fim": None,
                                        "drop_fala": "depois", "drop_musica": None, "abertura": True},
                                 aviso=lambda *a: None)
        assert com_ab["abertura_falas"] and com_ab["ritmo"] == "lento", com_ab["abertura_falas"]   # o resto ficou
        sem_g = edit.replanejar(arq4, {"gancho": None, "drop_filme": None, "fala_fim": None, "drop_fala": "depois",
                                       "drop_musica": None, "ritmo": "rapido",
                                       "transicoes": list(edit.PADRAO["transicoes"])}, aviso=lambda *a: None)
        assert sem_g["gancho"]["fim"] == sem_g["gancho"]["inicio"], sem_g["gancho"]
    finally:
        cenas.imagem_util = original[1]
    # fase 2: cada corte à mão (trocar plano, deslizar, transição, dividir, excluir) sem mexer no total
    def cortes_de(arq):
        return json.loads(arq.read_text(encoding="utf-8"))["cortes"]
    antes = cortes_de(arq4)
    soma = round(sum(c["dur"] for c in antes), 3)
    por_cena = {c["id"]: c for c in cs}
    livre = next(c for c in cs if c["id"] not in {x["cena"] for x in antes} and c["fim"] - c["inicio"] > 3)
    d = edit.editar_corte(arq4, {"op": "plano", "i": 1, "cena": livre["id"]})
    c1 = d["cortes"][1]
    assert c1["cena"] == livre["id"] and livre["inicio"] <= c1["fonte"] and c1["fonte"] + c1["dur"] * c1["vel"] <= livre["fim"], c1
    d = edit.editar_corte(arq4, {"op": "deslizar", "i": 1, "fonte": 0})
    assert abs(d["cortes"][1]["fonte"] - (livre["inicio"] + 0.05)) < 0.002, d["cortes"][1]      # preso no plano
    d = edit.editar_corte(arq4, {"op": "transicao", "i": 2, "transicao": "giro"})
    assert d["cortes"][2]["transicao"] == "giro"
    # fusão sem filme sobrando no corte de antes: recusada
    ant = d["cortes"][1]
    edit.editar_corte(arq4, {"op": "deslizar", "i": 1, "fonte": por_cena[ant["cena"]]["fim"]})
    try:
        edit.editar_corte(arq4, {"op": "transicao", "i": 2, "transicao": "fusao"})
        raise AssertionError("aceitou fusão sem filme sobrando")
    except ValueError:
        pass
    n = len(cortes_de(arq4))
    d = edit.editar_corte(arq4, {"op": "excluir", "i": 2})        # o corte 1 fica com a vez do 2
    assert len(d["cortes"]) == n - 1 and d["cortes"][1]["dur"] > 1.8 * batida, d["cortes"][1]
    d = edit.editar_corte(arq4, {"op": "dividir", "i": 1})        # e se divide de novo na batida
    assert len(d["cortes"]) == n and d["cortes"][2]["fonte"] > d["cortes"][1]["fonte"]
    assert abs(d["cortes"][1]["dur"] - batida) < 0.05, d["cortes"][1]
    curto = next(k for k, c in enumerate(d["cortes"]) if c["dur"] < 1.5 * batida)
    try:
        edit.editar_corte(arq4, {"op": "dividir", "i": curto})
        raise AssertionError("dividiu um corte de uma batida")
    except ValueError:
        pass
    d = edit.editar_corte(arq4, {"op": "excluir", "i": 0})        # o primeiro: o de depois assume
    assert len(d["cortes"]) == n - 1
    for x in (d["cortes"],):
        assert round(sum(c["dur"] for c in x), 3) == soma, "a duração total mudou"
        assert all(abs(b["saida"] - a["saida"] - a["dur"]) < 0.002 for a, b in zip(x, x[1:])), "buraco entre os cortes"
    assert d["cortes_editados"] is True
    video5 = edit.renderizar(arq4, previa=True)            # o plano editado renderiza
    assert video5.exists()
    print("ok  cortes à mão: trocar, deslizar, transição (fusão recusada sem filme), dividir, excluir; total igual")

    previa = edit.renderizar(arq4, previa=True)
    info_p = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(previa)], capture_output=True, text=True).stderr
    assert previa.name == "previa.mp4" and "540x960" in info_p, info_p[-300:]
    print("ok  ajuste depois de pronto: refaz sem IA, desfaz, drop na batida escolhida, volume, ajustes gerais, sem gancho; prévia 540x960")

    # drop DEPOIS da fala do gatilho: a fala fecha o gancho (limpa, sem música) e o drop vem quando ela acaba
    edit.analisar_filme = lambda *a, **k: (cs, falas, pasta / "planos_falsos.json", None)
    cenas.imagem_util = lambda *a, **k: True
    try:
        arq5 = edit.planejar(filme, musica, {"pasta_dados": str(pasta / "dados"), "edit": {}}, gancho="30-33",
                             drop_filme=33.0, fala_drop=34.6, drop_fala="depois", duracao=8,
                             usar_ia=False, aviso=lambda *a: None)
    finally:
        edit.analisar_filme, cenas.imagem_util = original
    p5 = json.loads(arq5.read_text(encoding="utf-8"))
    g5 = p5["gancho"]
    assert p5["fala_drop"] is None and p5["drop_fala"] == "depois", p5["fala_drop"]
    assert abs(g5["fim"] - 34.85) < 1 / edit.FPS, g5["fim"]
    assert [w["w"] for w in g5["palavras"]][-3:] == ["A", "mim,", "X-Men!"], g5["palavras"]
    assert p5["cortes"][0]["fonte"] == 34.85, p5["cortes"][0]
    print(f"ok  abertura com falas {a_dur:.1f}s + gancho {g4_dur:.1f}s + fala no drop + ritmo rápido = {p4['duracao']:.1f}s")


if __name__ == "__main__":
    main()
