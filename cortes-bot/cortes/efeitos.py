"""Efeitos dos modelos de edit, como pedaços de filtro do ffmpeg (o edit.renderizar os encaixa no grafo).

  letreiro  um cartão preto com o texto do .ass em LED: grade de pontos, aberração cromática e brilho
  rolo      os últimos quadros de um trecho enrolam para a esquerda como um rolo de papel (o drop do Honorable)
  moldura   nos últimos quadros de um trecho, uma moldura branca pisca com o plano seguinte dentro dela,
            crescendo até tomar a tela; o plano seguinte entra saindo do branco

Os números são medidos no quadro de 1080 de largura; `escala` = largura / 1080 (a prévia usa 0,5).
"""
FPS = 30
ROLO = 8                # quadros do rolo
# a moldura: (o que aparece, tamanho em relação ao quadro, quadros), nos últimos quadros do trecho
MOLDURA = [("branco", 0.40, 2), ("plano", 0.40, 3), ("branco", 0.60, 2), ("plano", 0.60, 3),
           ("branco", 0.80, 2), ("plano", 0.80, 2), ("branco", 1.0, 1)]
QUADROS = {"rolo": ROLO, "moldura": sum(q for _, _, q in MOLDURA)}


def letreiro(saida: str, ass: str, W: int, H: int, dur: float, est: dict, escala: float) -> list[str]:
    """Filtros que geram o cartão `[saida]` (W x H, `dur` segundos): o texto do `ass` sobre o preto,
    multiplicado por uma grade de LEDs (a máscara é calculada num quadro só e repetida), com o
    vermelho e o azul deslocados e um brilho desfocado por cima."""
    p = max(2, round(est["led_passo"] * escala))
    c, r, fundo = (p - 1) / 2, p * 0.4, est["led_fundo"]
    q = round(dur * FPS) + 2
    ab = max(1, round(est["aberracao"] * escala))
    mascara = (f"color=c=black:s={W}x{H}:r={FPS}:d=0.04,format=gray,"
               f"geq=lum='255*({fundo}+(1-{fundo})*lt(hypot(mod(X,{p})-{c},mod(Y,{p})-{c}),{r}))',"
               f"loop=loop=-1:size=1,setpts=N/{FPS}/TB,trim=end_frame={q},format=gbrp[{saida}m]")
    texto = (f"color=c=black:s={W}x{H}:r={FPS}:d={q / FPS:.3f},subtitles=filename={ass},"
             f"format=gbrp,gblur=sigma={0.7 * escala:.2f}[{saida}t]")
    f = [mascara, texto]
    led = f"[{saida}t][{saida}m]blend=all_mode=multiply,rgbashift=rh={-ab}:bh={ab}"
    if est.get("brilho"):
        b = float(est["brilho"])
        f.append(f"{led},split[{saida}a][{saida}b]")
        f.append(f"[{saida}b]gblur=sigma={12 * escala:.1f},colorchannelmixer=rr={b}:gg={b}:bb={b}[{saida}g]")
        f.append(f"[{saida}a][{saida}g]blend=all_mode=screen,format=yuv420p[{saida}]")
    else:
        f.append(f"{led},format=yuv420p[{saida}]")
    return f


def sem_letreiro(intervalos: list[tuple[float, float]]) -> str:
    """A expressão `enable` que esconde o cartão nos relâmpagos (lá aparece o filme)."""
    if not intervalos:
        return "1"
    return "not(" + "+".join(f"between(t,{a - 0.5 / FPS:.4f},{b - 0.5 / FPS:.4f})" for a, b in intervalos) + ")"


def rolo(entrada: str, saida: str, quadros: int, W: int, H: int) -> list[str]:
    """Os últimos ROLO quadros de `entrada` (que tem `quadros` quadros) enrolam para a esquerda: o
    eixo de um cilindro corre da borda direita até sumir, e o que passa dele dobra para trás,
    menor e mais escuro. Atrás fica o preto."""
    q0 = quadros - ROLO
    R = W * 0.3
    cy = H / 2
    eixo = f"{W}-({W}+{R})*(N+1)/{ROLO}"
    def canal(ch: str) -> str:
        return (f"st(0,{eixo});st(1,(X-ld(0))/{R:.1f});"
                f"if(lt(ld(1),0),{ch}(X,Y),if(gte(ld(1),1),0,"
                f"st(2,asin(ld(1)));st(3,1-cos(ld(2)));st(4,{cy}+(Y-{cy})*(1+0.35*ld(3)));"
                f"if(gt(abs(ld(4)-{cy}),{cy}),0,{ch}(ld(0)+{R:.1f}*ld(2),ld(4))*(1-0.65*ld(3)))))")
    return [f"[{entrada}]split[{saida}x][{saida}y]",
            f"[{saida}x]trim=end_frame={q0}[{saida}a]",
            f"[{saida}y]trim=start_frame={q0},setpts=PTS-STARTPTS,format=gbrp,"
            f"geq=r='{canal('r')}':g='{canal('g')}':b='{canal('b')}',format=yuv420p[{saida}b]",
            f"[{saida}a][{saida}b]concat=n=2:v=1:a=0,settb=AVTB[{saida}]"]


def moldura(entrada: str, quadro: str, saida: str, quadros: int, W: int, H: int) -> list[str]:
    """A moldura piscando nos últimos quadros de `entrada`: retângulo branco, o plano seguinte
    (`quadro`, um quadro só, já em W x H) dentro dele, um retângulo maior... e o branco cheio."""
    q = quadros - QUADROS["moldura"]
    planos = [m for m in MOLDURA if m[0] == "plano"]
    f = [f"[{quadro}]split={len(planos)}" + "".join(f"[{saida}q{i}]" for i in range(len(planos)))]
    atual, i_plano = entrada, 0
    for n, (tipo, tam, qs) in enumerate(MOLDURA):
        w, h = round(W * tam / 2) * 2, round(H * tam / 2) * 2
        x, y = (W - w) // 2, (H - h) // 2
        quando = f"between(t,{(q - 0.5) / FPS:.4f},{(q + qs - 0.5) / FPS:.4f})"
        prox = f"{saida}{n}" if n + 1 < len(MOLDURA) else saida
        if tipo == "branco":
            f.append(f"[{atual}]drawbox=x={x}:y={y}:w={w}:h={h}:color=white@1:t=fill:enable='{quando}'[{prox}]")
        else:
            s = f"{saida}q{i_plano}"
            f.append(f"[{s}]scale={w}:{h},loop=loop=-1:size=1,setpts=N/{FPS}/TB[{s}s]")
            f.append(f"[{atual}][{s}s]overlay=x={x}:y={y}:shortest=1:enable='{quando}'[{prox}]")
            i_plano += 1
        atual, q = prox, q + qs
    return f
