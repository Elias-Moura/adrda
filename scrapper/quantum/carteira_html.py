"""Parser do relatório HTML ``carteiraFundo.qt`` do Quantum.

Esta tela NÃO é a API REST limpa: é um servlet ``.qt`` que devolve uma árvore
profunda de ``<table>`` renderizada no servidor. Diferente do endpoint REST
``/carteira`` (que só traz nome + participação), o ``.qt`` carrega também o
**valor em milhares** e as **agregações** por tipo/setor/risco/classe — por isso
raspamos o HTML aqui.

Funções puras (sem rede, sem Django). A extração é por estrutura, não por rótulo
traduzível: posições vêm das linhas com ``exibirDetalhes('<uuid>')`` e as
agregações dos ``<font color="#004379">`` (rótulo, %) agrupados pelos 4 cabeçalhos
de dimensão fixos da conta (Asset Type / Sector / Risk / Class).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from loguru import logger

# chave (UUID minúsculo) que prende o estado da sessão .qt; o primeiro do HTML.
_CHAVE_RE = re.compile(r"chave=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})")
_UUID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")

# Opções do <select id="datas"> — competências disponíveis (MM/DD/YYYY).
_OPCAO_RE = re.compile(r'<option[^>]*\bvalue="(\d{2}/\d{2}/\d{4})"', re.I)
_SELECIONADA_RE = re.compile(r'<option[^>]*\bselected[^>]*\bvalue="(\d{2}/\d{2}/\d{4})"', re.I)

# Linha de posição: âncora exibirDetalhes + nome, depois valor (milhares) e %.
_POSICAO_RE = re.compile(
    r"exibirDetalhes\('[^']+'\)\"[^>]*>\s*<font>(?P<nome>[^<]+)</font>.*?"
    r"<font>\s*<font>\s*(?P<valor>[-\d.,]+)\s*</font>.*?"
    r"<font>\s*<font>\s*(?P<pct>[-\d.,]+)\s*%\s*</font>",
    re.S,
)

# Tokens de agregação (rótulo e %) marcados pela cor #004379.
_AGG_RE = re.compile(r'<font color="#004379">([^<]+)</font>')

# Cabeçalhos de dimensão (conta fixada em inglês) -> chave interna.
_DIMENSOES = {
    "Asset Type": "tipo",
    "Sector": "setor",
    "Risk": "risco",
    "Class": "classe",
}
_FIM_AGG = "Portfolio Composition"


@dataclass
class PosicaoQt:
    nome: str
    valor: float | None  # milhares de reais
    participacao: float   # %


@dataclass
class CarteiraQt:
    competencia: date | None = None
    datas: list[date] = field(default_factory=list)
    posicoes: list[PosicaoQt] = field(default_factory=list)
    # {"tipo": [(rotulo, pct), ...], "setor": [...], "risco": [...], "classe": [...]}
    agregacoes: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


def extrair_chave(html: str) -> str:
    """A chave (UUID) que prende o estado da sessão .qt, necessária p/ trocar mês."""
    m = _CHAVE_RE.search(html) or _UUID_RE.search(html)
    if not m:
        raise ValueError("chave (UUID) não encontrada no HTML da carteira.")
    return m.group(1) if m.re is _CHAVE_RE else m.group(0)


def _num(texto: str) -> float | None:
    """'85,517.91' / '-0.03' -> float. Formato en-US (vírgula de milhar)."""
    try:
        return float(texto.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _data(mmddyyyy: str) -> date | None:
    try:
        m, d, y = (int(x) for x in mmddyyyy.split("/"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def parse_datas(html: str) -> list[date]:
    """Competências disponíveis no <select>, em ordem decrescente (recente→antiga)."""
    datas = [d for raw in _OPCAO_RE.findall(html) if (d := _data(raw))]
    return datas


def parse_carteira_qt(html: str) -> CarteiraQt:
    """HTML do carteiraFundo.qt -> CarteiraQt (competência, datas, posições, agregações)."""
    sel = _SELECIONADA_RE.search(html)
    competencia = _data(sel.group(1)) if sel else None

    posicoes = [
        PosicaoQt(
            nome=m.group("nome").strip(),
            valor=_num(m.group("valor")),
            participacao=_num(m.group("pct")) or 0.0,
        )
        for m in _POSICAO_RE.finditer(html)
    ]

    agregacoes = _parse_agregacoes(html)

    if not posicoes:
        logger.warning("carteiraFundo.qt sem posições (HTML inesperado ou competência vazia).")

    return CarteiraQt(
        competencia=competencia,
        datas=parse_datas(html),
        posicoes=posicoes,
        agregacoes=agregacoes,
    )


def _parse_agregacoes(html: str) -> dict[str, list[tuple[str, float]]]:
    """Agrupa os tokens (#004379) pelas 4 dimensões; ignora '%' como rótulo."""
    tokens = [t.strip() for t in _AGG_RE.findall(html)]
    agg: dict[str, list[tuple[str, float]]] = {}
    dim: str | None = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith(_FIM_AGG):
            break
        if t in _DIMENSOES:
            dim = _DIMENSOES[t]
            agg[dim] = []
            i += 1
            continue
        # par (rótulo, %) — o próximo token é o percentual
        if dim is not None and i + 1 < len(tokens) and tokens[i + 1].endswith("%"):
            pct = _num(tokens[i + 1].rstrip("% ").strip())
            if pct is not None:
                agg[dim].append((t, pct))
            i += 2
            continue
        i += 1
    return agg
