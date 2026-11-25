"""Teste dos modelos de edit (modelos/*.yaml) sem filme, música, IA ou Whisper de verdade:

- carregar, listar e aplicar um modelo (config < modelo < opções da mão), recusar o que não existe;
- o letreiro: telas palavra por palavra e os relâmpagos (buracos da fala, com o filme);
- a escolha das transições do Honorable (rolo no drop, moldura de tempos em tempos, corte seco);
- um edit inteiro com o Honorable, renderizado numa pasta temporária: letreiro escuro com texto,
  filme nos relâmpagos, o rolo terminando no preto e a moldura branca piscando.

  python tests/teste_modelos.py
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cortes import cenas, config, edit, efeitos, legendas, modelos, painel_edit  # noqa: E402
from teste_edit import gerar_filme, gerar_musica  # noqa: E402


def recusa(f, *a):
    try:
        f(*a)
    except ValueError:
        return
    raise AssertionError(f"aceitou {a}")


def quadros(video: Path, w: int, h: int) -> np.ndarray:
    bruto = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(video), "-vf", f"scale={w}:{h}",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(bruto, np.uint8).reshape(-1, h, w).astype(np.float32)


def main():
    pasta = Path(tempfile.mkdtemp(prefix="teste_modelos_"))

    # carregar, listar, aplicar
    ids = [m["id"] for m in modelos.listar()]
    assert "honorable" in ids, ids
    m = modelos.carregar("Honorable ")
    assert m["edit"]["transicao_drop"] == "rolo" and m["letreiro"]["fonte"] == "Impact"
    assert m["letreiro"]["segura"] == modelos.LETREIRO["segura"]          # o que o modelo não diz vem do padrão
    for ruim in ("nao_existe", "../config", ""):
        recusa(modelos.carregar, ruim)
    secao = modelos.aplicar({"proporcao": "4:5", "slowed": 0.9, "cor": {"grao": 5, "vinheta": False}}, "honorable")
    assert secao["proporcao"] == "9:16" and secao["slowed"] == 0.9 and secao["modelo"] == "honorable"
    assert secao["cor"]["balanco"] == "quente" and secao["cor"]["grao"] == 2 and secao["cor"]["vinheta"] is True
    ce = edit.cfg_edit({"edit": {**secao, "proporcao": "4:5"}})           # a mão vale mais que o modelo
    assert ce["proporcao"] == "4:5" and ce["letreiro"]["cores"] == ["FFFFFF", "E8202A"]
    # um modelo com chave errada é recusado (e some da lista)
    original = modelos.PASTA
    modelos.PASTA = pasta / "modelos"
    modelos.PASTA.mkdir()
    (modelos.PASTA / "torto.yaml").write_text("edit:\n  transicoes: [teletransporte]\n", encoding="utf-8")
    (modelos.PASTA / "torto2.yaml").write_text("edit:\n  nao_existe: 1\n", encoding="utf-8")
    try:
        recusa(modelos.carregar, "torto")
        recusa(modelos.carregar, "torto2")
        assert modelos.listar() == []
    finally:
        modelos.PASTA = original
    print(f"ok  modelos: {', '.join(ids)}; config < modelo < mão; recusa o que não existe")

    # letreiro: telas e relâmpagos
    est = m["letreiro"]
    fala = [{"w": "You", "s": 0.3, "e": 0.6}, {"w": "tell", "s": 0.65, "e": 0.9}, {"w": "them!", "s": 0.95, "e": 1.3},
            {"w": "I", "s": 2.4, "e": 2.5}, {"w": "believed", "s": 2.55, "e": 3.0}, {"w": "in", "s": 3.05, "e": 3.15},
            {"w": "myself,", "s": 3.2, "e": 3.7}, {"w": "when", "s": 3.75, "e": 3.95}]
    telas, janelas, rel = legendas.telas_letreiro(fala, 4.6, est)
    assert [[p["w"] for p in t] for t in telas] == [["YOU", "TELL", "THEM"], ["I", "BELIEVED", "IN", "MYSELF"], ["WHEN"]]
    assert rel == [(1.5, 2.36), (4.15, 4.6)], rel          # o buraco depois de "them" e o fim
    assert not any(a < 0.3 < b for a, b in rel)            # antes da 1ª palavra (0,26 s): curto, fica o preto
    ass = legendas.gerar_ass_letreiro(telas, janelas, pasta / "l.ass", est)
    texto = ass.read_text(encoding="utf-8")
    assert "Impact" in texto and r"\c&H002A20E8&" in texto and r"\fscx122" in texto and "MYSELF" in texto
    assert "\a" not in texto
    assert legendas.gerar_ass_letreiro([], [], pasta / "vazio.ass", est) is None
    print(f"ok  letreiro: {len(telas)} telas, relâmpagos {rel}")

    # transições do Honorable
    tr = secao["transicoes"]
    escolha = [edit._transicao(i, 0.7, tr, False, 0.7, "rolo") for i in range(10)]
    assert escolha[0] == "rolo" and escolha[3] == escolha[9] == "moldura" and escolha[8] == "flash", escolha
    assert set(escolha[1:3] + escolha[4:8]) == {"corte"}, escolha
    assert edit._transicao(3, 0.7, tr, False, 0.4, "rolo") == "corte"       # corte de antes curto: sem moldura
    assert edit._transicao(0, 0.7, [], False, 0, "rolo") == "corte"          # "nenhuma" vale até para o drop
    assert edit.ler_transicoes("corte,flash,moldura") == ["corte", "flash", "moldura"]
    print(f"ok  transições: {', '.join(escolha)}")

    # um edit inteiro com o Honorable (sem IA nem Whisper: as falas são de mentira)
    musica, filme = pasta / "musica.wav", pasta / "filme.mp4"
    gerar_musica(musica)
    gerar_filme(filme)
    cs = cenas.detectar(filme)
    assert all("mov" in c and 0 <= c["mov"] < 0.05 for c in cs), cs[:3]       # cor lisa: quase parado
    args, _ = painel_edit.argumentos({"filme": str(filme), "musica": str(musica), "modelo": "honorable"})
    assert "--modelo=honorable" in args, args
    recusa(painel_edit.argumentos, {"filme": str(filme), "musica": str(musica), "modelo": "nao_existe"})
    falas = [{"w": w, "s": s, "e": e} for w, s, e in [
        ("You", 30.3, 30.6), ("tell", 30.65, 30.9), ("them.", 30.95, 31.3),
        ("I", 32.4, 32.5), ("believed", 32.55, 33.0), ("in", 33.05, 33.15), ("myself.", 33.2, 33.7),
        ("When", 34.4, 34.6), ("nobody", 34.65, 35.0), ("else", 35.05, 35.3), ("did.", 35.35, 35.8)]]
    orig = edit.analisar_filme
    edit.analisar_filme = lambda *a, **k: (cs, falas, pasta / "planos_falsos.json", None)
    try:
        arq = edit.planejar(filme, musica, {"pasta_dados": str(pasta / "dados"), "edit": secao}, gancho="30.2-35.9",
                            duracao=8, usar_ia=False, aviso=lambda *a: None)
    finally:
        edit.analisar_filme = orig
    p = json.loads(arq.read_text(encoding="utf-8"))
    assert p["modelo"] == "honorable" and p["estilo"]["letreiro"] and p["estilo"]["fim_preto"] == 0.9
    assert p["cortes"][0]["transicao"] == "rolo", p["cortes"][0]
    assert "moldura" in [c["transicao"] for c in p["cortes"]], [c["transicao"] for c in p["cortes"]]
    video = edit.renderizar(arq)
    assert not list(arq.parent.glob("letreiro_*.ass")), "o .ass do letreiro ficou para trás"
    assert not (arq.parent / "gancho.ass").exists(), "com letreiro, as falas não levam a legenda neon"
    q = quadros(video, 90, 160)
    g, F = p["gancho"], edit.FPS
    em = lambda t: round((t - g["inicio"]) * F)            # quadro do vídeo num segundo do filme (gancho)
    for t in (31.1, 33.5, 35.5):                            # letreiro: escuro, com letras acesas
        x = q[em(t)]
        assert x.mean() < 45 and x.max() > 100, (t, x.mean(), x.max())
    meio = q[em(31.9)]                                      # relâmpago: o filme (rosa, aos 31,9 s)
    assert meio.mean() > 120, meio.mean()
    t_drop = round((g["fim"] - g["inicio"]) * F)
    assert q[t_drop - 1].mean() < 8, q[t_drop - 3:t_drop + 1].mean(axis=(1, 2))   # o rolo terminou no preto
    k = next(c for c in p["cortes"] if c["transicao"] == "moldura")
    b = round(k["saida"] * F) - efeitos.QUADROS["moldura"]  # 1º estágio: retângulo branco de 40% no meio
    assert q[b, 70:90, 35:55].min() > 230 and q[b, :20, :20].max() < 235, (q[b, 70:90, 35:55].min(), q[b, :20, :20].max())
    for n in (b, b + 3, b + 7, round(k["saida"] * F) - 1):
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-i", str(video), "-vf", f"select=eq(n\\,{n})",
                        "-frames:v", "1", str(pasta / f"moldura_{n}.png")], check=True)
    for t in (31.1, 31.9, 35.5):
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-i", str(video), "-vf", f"select=eq(n\\,{em(t)})",
                        "-frames:v", "1", str(pasta / f"letreiro_{t}.png")], check=True)
    # a prévia da galeria: feita pelo próprio edit sobre mídia sintética, guardada e refeita só se velha
    cfg = {"pasta_dados": str(pasta / "previas")}
    v1 = modelos.previa("honorable", cfg)
    assert v1.name == "previa.mp4" and v1.stat().st_size > 100_000, v1
    antes = v1.stat().st_mtime
    assert modelos.previa("Honorable", cfg).stat().st_mtime == antes          # em cache
    assert modelos.previa("padrao", cfg).exists()
    recusa(modelos.previa, "nao_existe", cfg)
    lista = modelos.listar(com_padrao=True)
    assert lista[0]["id"] == "padrao" and lista[0]["proporcao"] == "4:5" and not lista[0]["letreiro"]
    hon = next(x for x in lista if x["id"] == "honorable")
    assert hon["letreiro"] and hon["transicao_drop"] == "rolo" and hon["proporcao"] == "9:16"
    print(f"ok  prévias da galeria: {v1}")
    teste_funk_power(pasta, filme, musica, cs, falas)
    teste_peak_days(pasta, filme, musica, cs, falas)
    print(f"ok  edit com o Honorable: {video} ({p['duracao']:.1f}s, {len(p['cortes'])} cortes); quadros em {pasta}")


def teste_funk_power(pasta: Path, filme: Path, musica: Path, cs: list[dict], falas: list[dict]):
    """Velocity edit: rampa de velocidade com borrão, planos que mexem primeiro, preparação antes do drop."""
    # a rampa: uma bola a velocidade constante; depois da rampa ela corre nas pontas e anda devagar no meio
    bola = pasta / "bola.mp4"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x202830:s=640x360:r=24:d=2",
                    "-vf", "geq=lum='if(lt(hypot(X-(20+600*T/2),Y-180),20),250,lum(X,Y))':cb='cb(X,Y)':cr='cr(X,Y)'",
                    "-c:v", "libx264", "-crf", "12", str(bola)], check=True)
    q = 19                                   # um corte de 0,63 s com 1 s de filme (vel 1,6)
    for borrao in (False, True):
        filtro = edit._filtro_plano("0:v", "v", "crop=iw:ih", (1280, 720), q, 1.6, "1.0", False, rampa=0.85,
                                    borrao=borrao)
        bruto = subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(bola), "-filter_complex", filtro, "-map", "[v]",
                                "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        fr = np.frombuffer(bruto, np.uint8).reshape(-1, 360, 640).astype(np.float32)
        assert len(fr) == q, len(fr)
        xs = np.array([np.average(np.arange(640), weights=np.maximum(f[180] - 60, 0) + 1e-6) for f in fr])
        passo = np.abs(np.diff(xs))
        ponta, meio = (passo[:3].mean() + passo[-3:].mean()) / 2, passo[q // 2 - 3:q // 2 + 2].mean()
        assert ponta > 2.5 * meio, (borrao, passo.round(1))
        if borrao:                           # com a mistura de quadros, o lento anda sem tranco (nenhum passo 0)
            assert passo.min() > 2 and passo.max() < 3 * passo[3:-3].mean() + 15, passo.round(1)
    # planos que mexem primeiro; os parados para o fim, na ordem que tinham
    por_id = {i: {"id": i, "mov": m} for i, m in enumerate([0.05, 0.001, 0.03, 0.002, 0.04, 0.06, 0.003], 1)}
    assert edit._por_movimento(list(por_id), por_id) == [1, 3, 5, 6, 2, 4, 7]
    assert edit._por_movimento([1, 2], {1: {"id": 1}, 2: {"id": 2}}) == [1, 2]
    # a preparação: começa numa batida perto de 6 s antes do drop e troca de plano no meio
    bt = [k * 0.6 for k in range(60)]
    pp = edit._pontos_preparacao(bt, 24.0, 6.0)
    assert pp[0] == 18.0 and pp[-1] == 24.0 and len(pp) == 3 and abs(pp[1] - 21.0) < 0.31, pp
    assert edit._pontos_preparacao(bt, 1.0, 6.0) == [] and edit._pontos_preparacao(bt, 24.0, 0) == []

    secao = modelos.aplicar({}, "funk_power")
    orig = edit.analisar_filme
    edit.analisar_filme = lambda *a, **k: (cs, falas, pasta / "planos_falsos.json", None)
    try:
        arq = edit.planejar(filme, musica, {"pasta_dados": str(pasta / "dados_funk"), "edit": secao},
                            gancho="30.2-33.7", duracao=6, usar_ia=False, aviso=lambda *a: None)
    finally:
        edit.analisar_filme = orig
    p = json.loads(arq.read_text(encoding="utf-8"))
    g_dur = p["gancho"]["fim"] - p["gancho"]["inicio"]
    prep, cortes = p["preparacao"], p["cortes"]
    assert len(prep) == 2 and abs(p["preparacao_dur"] - 6) < 0.7, (len(prep), p["preparacao_dur"])
    assert all(c["vel"] <= edit.VEL_PREPARACAO and "rampa" not in c and c["zoom"] == "empurra" for c in prep), prep
    assert all(c["rampa"] == secao["rampa"] and c["zoom"] == "nenhum" and not c["tremer"] for c in cortes), cortes[0]
    assert {c["transicao"] for c in cortes} == {"corte"}
    assert not {c["cena"] for c in prep} & {c["cena"] for c in cortes}, "plano da preparação repetido depois"
    assert abs(cortes[0]["saida"] - (g_dur + p["preparacao_dur"])) < 0.01, (cortes[0]["saida"], g_dur)
    assert abs(p["musica_inicio"] - (p["drop"] - g_dur - p["preparacao_dur"])) < 0.01
    video = edit.renderizar(arq)
    info = subprocess.run([config.ffmpeg(), "-hide_banner", "-i", str(video)], capture_output=True, text=True).stderr
    h, m_, s_ = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info).groups()
    assert abs(float(s_) + 60 * int(m_) - p["duracao"]) < 0.1, (s_, p["duracao"])
    fr = quadros(video, 90, 160)
    dif = np.r_[0, np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))]
    assert fr[0].mean() < 10, fr[0].mean()                       # sai do preto
    for c in [prep[0]] + cortes[:4]:                             # os cortes secos caem no quadro certo
        k = round(c["saida"] * edit.FPS)
        assert dif[k] == dif[k - 2:k + 3].max(), (c, dif[k - 3:k + 4].round(1))
    print(f"ok  Funk Power: rampa (pontas {ponta / meio:.0f}x mais rápidas que o meio) com rastro, movimento, "
          f"preparação {p['preparacao_dur']:.1f}s + {len(cortes)} cortes = {p['duracao']:.1f}s")



def teste_peak_days(pasta: Path, filme: Path, musica: Path, cs: list[dict], falas: list[dict]):
    """Legenda em destaque (pequenas em cima, a palavra-chave grande com degradê), texto do editor
    uma palavra por batida com a piscada preta, e as transições mergulho e flash seco."""
    m = modelos.carregar("peak_days")
    assert m["destaque"]["fonte"] == "Impact" and m["edit"]["transicao_drop"] == "mergulho"
    assert m["destaque"]["segura"] == modelos.DESTAQUE["segura"]
    resumo = next(x for x in modelos.listar() if x["id"] == "peak_days")
    assert resumo["destaque"] and resumo["texto_editor"] and not resumo["letreiro"], resumo
    est = m["destaque"]

    # as frases: as grandes são as últimas palavras, no máximo metade da frase
    def w(lista, t0=0.0):
        return [{"w": x, "s": t0 + 0.3 * i, "e": t0 + 0.3 * i + 0.25} for i, x in enumerate(lista)]
    fr = legendas.frases_destaque(w(["let's", "get", "started."]) + w(["To", "me,", "my", "X-Men!"], 3)
                                  + w("lend me the strength of the all fathers".split(), 6), est)
    partes = [([p["w"] for p in a], [p["w"] for p in b]) for a, b in fr]
    assert partes == [(["let's", "get"], ["started."]), (["To", "me,"], ["my", "X-Men!"]),
                      (["lend", "me", "the", "strength", "of"], ["the", "all", "fathers"])], partes

    # o .ass: o degradê sai em faixas recortadas; renderizado no preto, o topo da palavra grande é
    # rosa e a base é laranja (a 1ª cor da paleta), e as pequenas são brancas
    ass = legendas.gerar_ass_destaque(w(["let's", "get", "started."]), [], pasta / "destaque.ass", est, 1100)
    texto = ass.read_text(encoding="utf-8")
    assert texto.count("\\clip(") == est["faixas"] and "Pequena" in texto, texto[-600:]
    png = pasta / "destaque.png"
    subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1",
                    "-vf", f"subtitles=filename={ass.name}", "-ss", "0.8", "-frames:v", "1", png.name],
                   check=True, cwd=pasta)
    rgb = np.frombuffer(subprocess.run([config.ffmpeg(), "-v", "error", "-i", str(png), "-f", "rawvideo",
                                        "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout,
                        np.uint8).reshape(1920, 1080, 3).astype(np.float32)
    faixa = rgb[1100 - 60:1100 + 60]
    letra = faixa.max(axis=2) > 180                         # os pixels da palavra grande
    linhas = np.where(letra.any(axis=1))[0]
    topo, base = faixa[linhas[: len(linhas) // 3]], faixa[linhas[-len(linhas) // 3:]]
    azul = lambda x: x[..., 2][x.max(axis=2) > 180].mean()
    assert azul(topo) > azul(base) + 40, (azul(topo), azul(base))       # rosa em cima, laranja embaixo
    peq = rgb[1100 - 160:1100 - 70]
    assert (peq.min(axis=2) > 200).sum() > 200, "as palavras pequenas (brancas) não apareceram"

    # as transições do modelo: mergulho no drop, flash seco de tempos em tempos, corte seco de base
    ok = m["edit"]["transicoes"]
    escolha = [edit._transicao(i, 0.63, ok, False, 0.63, "mergulho") for i in range(12)]
    assert escolha[0] == "mergulho" and "flash_seco" in escolha and escolha.count("corte") >= 4, escolha
    f_seco = edit._filtro_plano("0:v", "v", "crop=iw:ih", (2160, 2700), 19, 1.0, "1.0", False, entra="flash_seco")
    assert "color=white:t=fill:enable='eq(n,0)'" in f_seco
    f_merg = edit._filtro_plano("0:v", "v", "crop=iw:ih", (2160, 2700), 19, 1.0, "1.0", False,
                                entra="mergulho", sai="mergulho")
    assert f_merg.count("fade=t=") == 2 and "drawbox" in f_merg and "gblur" in f_merg, f_merg

    # um edit inteiro com o Peak Days, com o texto do editor (sem IA: as palavras vêm do teste)
    secao = modelos.aplicar({}, "peak_days")
    orig = edit.analisar_filme
    edit.analisar_filme = lambda *a, **k: (cs, falas, pasta / "planos_falsos.json", None)
    try:
        arq = edit.planejar(filme, musica, {"pasta_dados": str(pasta / "dados_peak"), "edit": secao},
                            gancho="30.2-35.9", duracao=6, usar_ia=False, aviso=lambda *a: None)
    finally:
        edit.analisar_filme = orig
    p = json.loads(arq.read_text(encoding="utf-8"))
    assert p["texto_editor"] == [] and p["estilo"]["destaque"], "sem IA, sem texto do editor"
    ce = edit.cfg_edit({"edit": secao})
    p["texto_editor"] = edit._texto_editor({"texto_editor": ["O", "DOUTOR", "CHEGOU"]}, ce, p["cortes"], None)
    assert [x["s"] for x in p["texto_editor"]] == [c["saida"] for c in p["cortes"][:3]], p["texto_editor"]
    arq.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    assert p["cortes"][0]["transicao"] == "mergulho", p["cortes"][0]
    video = edit.renderizar(arq)
    q = quadros(video, 108, 192)
    F = edit.FPS
    k0 = round(p["cortes"][0]["saida"] * F)
    risco = q[k0 + 1]                                        # mergulho: preto com um risco de luz no meio
    assert risco[:80].max() < 40 and risco[90:102].max() > 120, (risco[:80].max(), risco[90:102].max())
    k1 = round(p["texto_editor"][1]["s"] * F)                # a piscada: quadro preto só com a palavra
    blink, depois = q[k1], q[k1 + 2]
    assert blink[30:60].mean() < 20 and blink[85:105].max() > 200, (blink[30:60].mean(), blink[85:105].max())
    assert depois[30:60].mean() > blink[30:60].mean() + 15, "a piscada durou mais de um quadro"
    assert not (arq.parent / "gancho.ass").read_text(encoding="utf-8").count("Letra,"), "usou a legenda neon"
    print(f"ok  Peak Days: legenda em destaque com degradê, texto do editor com piscada, mergulho com risco, "
          f"flash seco ({len(p['cortes'])} cortes, {p['duracao']:.1f}s)")


if __name__ == "__main__":
    main()
