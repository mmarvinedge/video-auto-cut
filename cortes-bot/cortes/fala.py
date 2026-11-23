"""Usa a transcrição para (1) dar nota ao que o streamer FALA e (2) ajustar as bordas do corte
para não começar nem terminar no meio de uma frase."""
import re
import unicodedata


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def texto(palavras: list[dict], inicio: float | None = None, fim: float | None = None) -> str:
    return " ".join(p["w"] for p in palavras
                    if (inicio is None or p["e"] > inicio) and (fim is None or p["s"] < fim))


def _contar(termos: list[str], t: str) -> int:
    return sum(len(re.findall(rf"(?<!\w){re.escape(_norm(r))}(?!\w)", t)) for r in termos)


def nota_fala(palavras: list[dict], inicio: float, fim: float, reacoes: list[str],
              pausas: list[str] | None = None, peso_pausa: float = 2.0) -> dict:
    """Pontua a fala dentro do corte: expressões de reação, exclamações e ritmo.

    `pausas` são falas de quem está saindo ou voltando da live ("vou almoçar", "voltei"). Sem chat
    e sem IA, elas apareciam entre os melhores momentos só por serem faladas alto; cada uma tira
    `peso_pausa` da nota (no máximo duas contam, para um corte bom com um "já volto" não morrer)."""
    dentro = [p for p in palavras if p["e"] > inicio and p["s"] < fim]
    duracao = max(fim - inicio, 1)
    t = _norm(texto(dentro))
    hits = _contar(reacoes, t)
    n_pausas = _contar(pausas or [], t)
    risadas = len(re.findall(r"\b(k{3,}|(?:ha){2,}h?|(?:he){2,}h?)\b", t))
    exclam = t.count("!")
    ritmo = len(dentro) / duracao  # palavras por segundo
    bruto = hits * 1.0 + risadas * 1.5 + exclam * 0.4 + min(ritmo, 3.5) * 0.6 - min(n_pausas, 2) * peso_pausa
    if not dentro:
        bruto = -2.0  # corte sem fala nenhuma raramente funciona em vertical
    return {"bruto": round(bruto, 2), "reacoes": hits, "risadas": risadas, "exclamacoes": exclam,
            "palavras_por_s": round(ritmo, 2), "pausas": n_pausas}


def ajustar_bordas(palavras: list[dict], inicio: float, fim: float, folga: float = 4.0,
                   duracao_max: float = 60) -> tuple[float, float]:
    """Puxa o início para o começo da frase e o fim para o final da frase (até `folga` s)."""
    if not palavras:
        return inicio, fim
    pausa = 0.7
    # início: volta até achar uma pausa entre palavras (começo de frase)
    antes = [p for p in palavras if inicio - folga <= p["s"] <= inicio + 1]
    novo_ini = inicio
    for i in range(len(antes) - 1, -1, -1):
        anterior = antes[i - 1]["e"] if i > 0 else -1e9
        if antes[i]["s"] - anterior >= pausa:
            novo_ini = antes[i]["s"] - 0.3
            break
    # fim: avança até a frase acabar (palavra com ponto ou pausa depois)
    depois = [p for p in palavras if fim - 0.3 <= p["e"] <= fim + folga]
    novo_fim = fim
    for i, p in enumerate(depois):
        prox = depois[i + 1]["s"] if i + 1 < len(depois) else 1e9
        if p["w"][-1:] in ".!?" or prox - p["e"] >= pausa:
            novo_fim = p["e"] + 0.5
            break
    if novo_fim - novo_ini > duracao_max:
        novo_fim = novo_ini + duracao_max
    return round(novo_ini, 2), round(novo_fim, 2)


def zscores(valores: list[float]) -> list[float]:
    if len(valores) < 2:
        return [0.0] * len(valores)
    m = sum(valores) / len(valores)
    dp = (sum((v - m) ** 2 for v in valores) / len(valores)) ** 0.5 or 1.0
    return [(v - m) / dp for v in valores]
