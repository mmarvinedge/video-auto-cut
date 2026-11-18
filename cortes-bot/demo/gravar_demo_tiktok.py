"""Grava o vídeo de demonstração que o TikTok pede na revisão do app (App Review).

Mostra o fluxo inteiro, de ponta a ponta, no painel de verdade, com legendas em inglês para
quem revisa:
  1. Login Kit: vincular a conta (user.info.basic)
  2. Content Posting API, Direct Post (video.publish): perfil consultado, privacidade escolhida
     pelo usuário, interações, divulgação comercial, consentimento, envio e status
  3. Content Posting API, Upload como rascunho (video.upload): o vídeo vai para a caixa de
     entrada do app do TikTok

ATENÇÃO: publica de verdade, na conta que você autorizar: 1 vídeo como "Só eu" e 1 rascunho.

Antes de rodar:
  - o app do TikTok ainda não foi aprovado, então use as chaves do Sandbox em
    segredos/tiktok_app.json e uma conta cadastrada como "target user" no Sandbox;
  - deixe essa conta do TikTok PRIVADA (o Direct Post de app não auditado só aceita conta privada);
  - abra o painel na porta do Redirect URI:  python -m cortes painel
  - uma vez só:  pip install playwright  e  python -m playwright install chromium

Rodar (na pasta cortes-bot):
  python demo/gravar_demo_tiktok.py

O navegador abre e o roteiro anda sozinho. Só o login no TikTok é com você: quando a página do
TikTok abrir, entre na conta e clique em "Authorize". O vídeo final sai em
dados/_demo/demo_tiktok_<data>.mp4, pronto para enviar (mp4, abaixo de 50 MB).

Opções: --sem-vinculo (pula o passo 1 e usa a conta já vinculada), --sem-direto,
--sem-rascunho, --conta <id ou @usuario>, --painel <url>.
"""
import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from playwright.sync_api import Locator, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cortes import config  # noqa: E402

LIMITE_MB = 50          # limite por arquivo no formulário de revisão do TikTok
TAMANHO = {"width": 1280, "height": 800}
ESPERA_LOGIN_MS = 10 * 60_000
ESPERA_ENVIO_S = 8 * 60
TITULO_PADRAO = "GTA VI: o momento mais caótico da live"

# Legenda fixa na parte de baixo da tela. É um popover para ficar na "top layer" e aparecer
# por cima até da janela modal de publicar; mostrar de novo a traz para a frente.
LEGENDA_JS = """(texto) => {
  let el = document.getElementById("__demo_legenda");
  if (!el) {
    el = document.createElement("div");
    el.id = "__demo_legenda";
    el.setAttribute("popover", "manual");
    Object.assign(el.style, {
      position: "fixed", inset: "auto auto 18px 50%", transform: "translateX(-50%)", margin: "0",
      maxWidth: "min(960px, 92vw)", padding: "12px 20px", border: "0", borderRadius: "10px",
      background: "rgba(0, 0, 0, .88)", color: "#fff", font: "600 18px/1.45 system-ui, sans-serif",
      textAlign: "center", pointerEvents: "none", boxShadow: "0 6px 24px rgba(0, 0, 0, .5)",
    });
    document.body.appendChild(el);
  }
  el.textContent = texto;
  if (el.matches(":popover-open")) el.hidePopover();
  if (texto) el.showPopover();
}"""


def page_base(page: Page) -> str:
    u = page.url.split("://", 1)
    return u[0] + "://" + u[1].split("/", 1)[0]


def pausa(segundos: float) -> None:
    time.sleep(segundos)


def legenda(page: Page, texto: str, segundos: float = 0) -> None:
    page.evaluate(LEGENDA_JS, texto)
    print(f"  · {texto}")
    pausa(segundos)


def destacar(alvo: Locator, segundos: float = 1.0) -> None:
    """Contorna o elemento antes de clicar: o vídeo gravado não mostra o cursor."""
    alvo.scroll_into_view_if_needed()
    alvo.evaluate("e => { e.style.outline = '3px solid #25F4EE'; e.style.outlineOffset = '3px'; }")
    pausa(segundos)


def apagar_destaque(alvo: Locator) -> None:
    # evaluate_all não espera o elemento: depois do clique ele pode já ter sumido (janela fechada)
    alvo.evaluate_all("es => es.forEach(e => { e.style.outline = ''; e.style.outlineOffset = ''; })")


def clicar(alvo: Locator, segundos: float = 1.0) -> None:
    destacar(alvo, segundos)
    alvo.click()
    apagar_destaque(alvo)


def aba(page: Page, nome: str) -> None:
    clicar(page.locator(f'nav a[data-aba="{nome}"]'), 0.6)
    page.wait_for_selector(f"#aba-{nome}:not([hidden])")


def conta_tiktok(base: str, escolha: str | None) -> dict:
    contas = [c for c in httpx.get(f"{base}/api/estado").json()["contas"] if c["plataforma"] == "tiktok"]
    if escolha:
        contas = [c for c in contas if escolha.lstrip("@") in (c["id"], c.get("usuario"))]
    if not contas:
        sys.exit("Nenhuma conta do TikTok vinculada" + (f" que bata com {escolha!r}" if escolha else "") + ".")
    return contas[-1]


# ------------------------------------------------------------------- passo 1: Login Kit
def vincular(page: Page) -> None:
    legenda(page, "Step 1 · Login Kit — the creator connects their own TikTok account to the desktop app.", 1)
    aba(page, "contas")
    botao = page.get_by_role("button", name="Vincular conta do TikTok")
    destacar(botao, 0.5)
    legenda(page, "Clicking “Connect TikTok account” opens TikTok's authorization page "
                  "(scopes: user.info.basic, video.upload, video.publish).", 4)
    painel = page_base(page)
    botao.click()
    page.wait_for_url(lambda url: not url.startswith(painel), timeout=30_000)  # foi para o TikTok
    print("\n  >>> No navegador: entre na conta do TikTok e clique em Authorize. Esperando até 10 min…\n")
    page.wait_for_url(re.compile(r"/oauth/tiktok/callback"), timeout=ESPERA_LOGIN_MS)
    page.wait_for_load_state()
    if "Conta vinculada" not in page.content():
        sys.exit("O TikTok não autorizou: " + page.locator("body").inner_text()[:300])
    legenda(page, "Authorized. The app exchanges the code for a token (PKCE) and reads the display name "
                  "and @username with user.info.basic.", 5)
    page.get_by_role("link", name="Voltar ao painel").click()
    page.wait_for_selector("#aba-contas:not([hidden]) .conta")
    cartao = page.locator(".conta", has=page.locator(".pill", has_text="TikTok")).last
    destacar(cartao, 0.5)
    legenda(page, "The connected account appears with its TikTok name and @username.", 5)
    apagar_destaque(cartao)


# ------------------------------------------------------- passos 2 e 3: Content Posting API
def proximo_card(page: Page) -> Locator:
    aba(page, "revisao")
    page.wait_for_selector("#lista .card")
    card = page.locator("#lista .card", has=page.locator("button.aprovar", has_text="Aprovar")).first
    if not card.count():
        sys.exit("Nenhum corte pendente na Revisão para publicar. Processe uma live antes.")
    card.scroll_into_view_if_needed()
    titulo = card.locator(".titulo")
    if not titulo.input_value().strip():
        destacar(titulo, 0.3)
        titulo.press_sequentially(TITULO_PADRAO, delay=35)
        apagar_destaque(titulo)
    return card


def abrir_janela(page: Page, card: Locator, conta: dict, modo: str) -> Locator:
    clicar(card.locator("button.aprovar"))
    dlg = page.locator("#dlg")
    dlg.wait_for(state="visible")
    # só a conta do TikTok da demonstração
    for cb in dlg.locator('#dlg-contas input[name="conta"]').all():
        if cb.is_enabled():
            cb.set_checked(cb.get_attribute("value") == conta["id"])
    clicar(dlg.locator(f'input[name="tt-modo"][value="{modo}"]'), 0.8)
    return dlg


def confirmar_agora(page: Page, dlg: Locator) -> str:
    """Escolhe "Agora", confirma e devolve o id do item criado na fila."""
    clicar(dlg.locator('input[name="modo"][value="agora"]'), 0.8)
    confirmar = dlg.locator("#dlg-confirmar")
    if confirmar.is_disabled():
        sys.exit("A janela não deixou publicar: " + dlg.locator("#dlg-falta").inner_text())
    with page.expect_response(lambda r: r.url.endswith("/api/publicar")) as resp:
        clicar(confirmar, 1.2)
    r = resp.value.json()
    if not r.get("ok"):
        sys.exit("O painel recusou: " + r.get("erro", "?"))
    dlg.wait_for(state="hidden")
    return r["itens"][0]["id"]


def esperar_envio(page: Page, base: str, item_id: str) -> dict:
    """Mostra a aba Fila enquanto a fila do painel envia; ela se atualiza sozinha a cada 8 s."""
    aba(page, "fila")
    limite = time.time() + ESPERA_ENVIO_S
    while time.time() < limite:
        item = next((i for i in httpx.get(f"{base}/api/fila").json() if i["id"] == item_id), None)
        if item and item["status"] in ("publicado", "erro"):
            page.evaluate("desenharFila()")   # redesenha já, sem esperar os 8 s
            pausa(1.5)
            return item
        pausa(3)
    sys.exit("O envio não terminou em 8 minutos. Veja a aba Fila e o terminal do painel.")


def linha_da_fila(page: Page, titulo: str) -> Locator:
    return page.locator("#fila tbody tr", has_text=titulo).first


def postar_direto(page: Page, base: str, conta: dict) -> None:
    card = proximo_card(page)
    titulo = card.locator(".titulo").input_value()
    legenda(page, "Step 2 · Content Posting API — Direct Post (video.publish). The creator reviews the clip "
                  "and its caption, then clicks “Approve…”.", 4)
    dlg = abrir_janela(page, card, conta, "direto")
    dlg.locator("#dlg-tt-priv option[value]:not([value=''])").first.wait_for(state="attached", timeout=30_000)
    criador = dlg.locator("#dlg-tt-criador")
    destacar(criador, 0.3)
    legenda(page, "Every time this window opens, creator_info/query is called: the creator's nickname, "
                  "the privacy levels they allow, their interaction settings and the max video length.", 6)
    apagar_destaque(criador)

    privacidade = dlg.locator("#dlg-tt-priv")
    destacar(privacidade, 0.3)
    legenda(page, "Privacy has no default: the creator must pick who can see the video "
                  "(only the options returned by TikTok are listed).", 4)
    opcoes = privacidade.locator("option[value]:not([value=''])").evaluate_all("os => os.map(o => o.value)")
    privacidade.select_option("SELF_ONLY" if "SELF_ONLY" in opcoes else opcoes[0])
    pausa(2)
    apagar_destaque(privacidade)

    legenda(page, "Comments, Duet and Stitch start off; the creator turns them on. "
                  "Options disabled in the creator's TikTok settings are greyed out.", 2)
    for campo in ("comentarios", "dueto", "costura"):
        cb = dlg.locator(f"#dlg-tt-{campo}")
        if cb.is_enabled():
            destacar(cb, 0.4)
            cb.check()
            apagar_destaque(cb)
    pausa(2)

    comercial = dlg.locator("#dlg-tt-comercial")
    legenda(page, "Commercial content disclosure: “Your brand” labels it Promotional content, "
                  "“Branded content” labels it Paid partnership (and cannot be private).", 1)
    clicar(comercial, 0.6)
    clicar(dlg.locator("#dlg-tt-marca"), 0.6)
    pausa(2.5)
    clicar(dlg.locator("#dlg-tt-parceria"), 0.6)
    pausa(3)
    dlg.locator("#dlg-tt-parceria").uncheck()
    dlg.locator("#dlg-tt-marca").uncheck()
    comercial.uncheck()
    if "SELF_ONLY" in opcoes:
        privacidade.select_option("SELF_ONLY")

    consentimento = dlg.locator("#dlg-tt-consentimento")
    destacar(consentimento, 0.3)
    legenda(page, "Before posting, the creator sees the consent to TikTok's Music Usage Confirmation "
                  "(and the Branded Content Policy when it applies).", 4)
    apagar_destaque(consentimento)

    legenda(page, "The creator confirms. Nothing is posted without this click.", 1)
    item_id = confirmar_agora(page, dlg)
    legenda(page, "The app calls video/init with these choices, uploads the file in chunks (FILE_UPLOAD) "
                  "and polls status/fetch until TikTok confirms the post.", 0)
    item = esperar_envio(page, base, item_id)
    linha = linha_da_fila(page, titulo)
    destacar(linha, 0.3)
    if item["status"] == "erro":
        legenda(page, f"TikTok returned an error: {item['erro']}", 6)
        sys.exit(f"Erro ao postar direto: {item['erro']}\n(Se for conta pública: deixe a conta privada e rode de novo.)")
    legenda(page, "Posted. The queue shows the result and a link to the video on TikTok.", 5)
    apagar_destaque(linha)
    url = (item.get("resultado") or {}).get("url") or ""
    if url.startswith("http"):
        legenda(page, "Opening the post on TikTok…", 1.5)
        page.goto(url)
        pausa(9)
        page.goto(f"{base}/#fila")
        page.wait_for_selector("#aba-fila:not([hidden])")


def enviar_rascunho(page: Page, base: str, conta: dict) -> None:
    card = proximo_card(page)
    titulo = card.locator(".titulo").input_value()
    legenda(page, "Step 3 · Content Posting API — Upload as draft (video.upload). The video goes to the "
                  "creator's TikTok inbox so they can finish editing and post it from the TikTok app.", 5)
    dlg = abrir_janela(page, card, conta, "rascunho")
    aviso = dlg.locator("#dlg-tt-legenda-aviso")
    destacar(aviso, 0.3)
    legenda(page, "In draft mode TikTok does not take a caption through the API, "
                  "so the app keeps it ready to copy.", 4)
    apagar_destaque(aviso)
    item_id = confirmar_agora(page, dlg)
    legenda(page, "The app calls inbox/video/init, uploads the file and checks the status.", 0)
    item = esperar_envio(page, base, item_id)
    linha = linha_da_fila(page, titulo)
    destacar(linha, 0.3)
    if item["status"] == "erro":
        legenda(page, f"TikTok returned an error: {item['erro']}", 6)
        sys.exit(f"Erro ao enviar o rascunho: {item['erro']}")
    legenda(page, "Sent to the TikTok app: the creator gets an inbox notification to edit and post it. "
                  "“Copy caption” puts the caption on the clipboard.", 6)
    apagar_destaque(linha)


# ------------------------------------------------------------------------- vídeo final
def converter(bruto: Path, destino: Path) -> Path:
    """Playwright grava em WebM; o TikTok aceita mp4/mov de até 50 MB."""
    for crf in (26, 30, 34, 38):
        subprocess.run([config.ffmpeg(), "-y", "-v", "error", "-i", str(bruto), "-c:v", "libx264",
                        "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", "-an", str(destino)], check=True)
        if destino.stat().st_size <= (LIMITE_MB - 1) * 1024 * 1024:
            return destino
    sys.exit(f"O vídeo ficou acima de {LIMITE_MB} MB mesmo comprimido: {destino}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--painel", default="http://localhost:8800")
    p.add_argument("--conta", help="id ou @usuario da conta do TikTok (padrão: a última vinculada)")
    p.add_argument("--sem-vinculo", action="store_true", help="pula o passo do Login Kit")
    p.add_argument("--sem-direto", action="store_true")
    p.add_argument("--sem-rascunho", action="store_true")
    a = p.parse_args()
    base = a.painel.rstrip("/")

    try:
        estado = httpx.get(f"{base}/api/estado").json()
    except httpx.HTTPError:
        sys.exit(f"O painel não respondeu em {base}. Abra antes:  python -m cortes painel")
    if not estado.get("tiktok_configurado"):
        sys.exit("Falta a chave do app do TikTok em segredos/tiktok_app.json (use as do Sandbox).")

    pasta = config.RAIZ / "dados" / "_demo"
    (pasta / "bruto").mkdir(parents=True, exist_ok=True)
    final = pasta / f"demo_tiktok_{datetime.now():%Y-%m-%d_%H%M}.mp4"

    with sync_playwright() as pw:
        navegador = pw.chromium.launch(headless=False, slow_mo=120)
        ctx = navegador.new_context(viewport=TAMANHO, record_video_dir=str(pasta / "bruto"),
                                    record_video_size=TAMANHO, locale="en-US")
        page = ctx.new_page()
        try:
            page.goto(f"{base}/#revisao")
            page.wait_for_selector("#lista .card, #lista .vazio")
            legenda(page, "video-auto-cut — a desktop app that runs on the creator's own computer. It finds "
                          "highlights in their live streams and posts them to their own TikTok account.", 6)
            if not a.sem_vinculo:
                vincular(page)
            conta = conta_tiktok(base, a.conta)
            if not a.sem_direto:
                postar_direto(page, base, conta)
            if not a.sem_rascunho:
                enviar_rascunho(page, base, conta)
            legenda(page, "End of demo · Login Kit (user.info.basic) + Content Posting API "
                          "(video.publish, video.upload) · TikTok Sandbox", 4)
        finally:
            video = page.video
            ctx.close()          # é ao fechar que o Playwright termina de gravar o arquivo
            navegador.close()
            bruto = Path(video.path()) if video else None

    if bruto and bruto.exists():
        converter(bruto, final)
        print(f"\nVídeo pronto: {final}  ({final.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
