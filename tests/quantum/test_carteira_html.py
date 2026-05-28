"""Testes do parser do relatório HTML carteiraFundo.qt.

O HTML imita a estrutura real (capturada do Quantum): <select> de competências,
linhas de posição via exibirDetalhes (nome / valor em milhares / participação) e
agregações marcadas por <font color="#004379">.
"""
from datetime import date

from scrapper.quantum.carteira_html import (
    extrair_chave,
    parse_carteira_qt,
    parse_datas,
)

# Fragmento mínimo, fiel ao markup real (espaços entre <font> incluídos de propósito).
HTML = """
<html><body>
<script>... "&chave=db5bed57-5b20-4f20-a164-9df8b9a9e22e&codigo=612014" ...</script>
<select id="datas" onchange="getCarteira()">
  <option selected value="04/30/2026">04/30/2026</option>
  <option  value="03/31/2026">03/31/2026</option>
  <option  value="02/27/2026">02/27/2026</option>
</select>

<table>
<td><font color="#004379">Asset Type</font></td>
<td><font color="#004379">Government Bonds</font></td><td><font color="#004379">51.43 %</font></td>
<td><font color="#004379">Private Bonds</font></td><td><font color="#004379">38.07 %</font></td>
<td><font color="#004379">Sector</font></td>
<td><font color="#004379">Federal Government</font></td><td><font color="#004379">61.92 %</font></td>
<td><font color="#004379">Risk</font></td>
<td><font color="#004379">Rating AAA</font></td><td><font color="#004379">61.92 %</font></td>
<td><font color="#004379">Class</font></td>
<td><font color="#004379">Selic</font></td><td><font color="#004379">51.85 %</font></td>
<td><font color="#004379">&nbsp;Portfolio Composition</font></td>
<td><font color="#004379">Asset</font></td>
</table>

<table>
<TR><TD><a href="javascript: exibirDetalhes('81E9191F-55B5-84D3-BF48-019E2B384B82')"><font>LFT - Venc.: 01/03/2030</font></a></TD>
  <TD><font> <font>85,517.91</font> </font></TD>
  <TD><font> <font>12.3351 %</font> </font></TD></TR>
<TR><TD><a href="javascript: exibirDetalhes('AAAA1111-55B5-84D3-BF48-019E2B384B82')"><font>Outros Valores a pagar</font></a></TD>
  <TD><font> <font>-241.23</font> </font></TD>
  <TD><font> <font>-0.0348 %</font> </font></TD></TR>
</table>
</body></html>
"""


def test_extrair_chave():
    assert extrair_chave(HTML) == "db5bed57-5b20-4f20-a164-9df8b9a9e22e"


def test_parse_datas_ordem_decrescente():
    assert parse_datas(HTML) == [date(2026, 4, 30), date(2026, 3, 31), date(2026, 2, 27)]


def test_competencia_selecionada():
    assert parse_carteira_qt(HTML).competencia == date(2026, 4, 30)


def test_posicoes_nome_valor_participacao():
    cart = parse_carteira_qt(HTML)
    assert len(cart.posicoes) == 2
    p0 = cart.posicoes[0]
    assert p0.nome == "LFT - Venc.: 01/03/2030"
    assert p0.valor == 85517.91
    assert p0.participacao == 12.3351
    # valores negativos (a pagar) preservam o sinal
    assert cart.posicoes[1].valor == -241.23
    assert cart.posicoes[1].participacao == -0.0348


def test_agregacoes_quatro_dimensoes():
    agg = parse_carteira_qt(HTML).agregacoes
    assert set(agg) == {"tipo", "setor", "risco", "classe"}
    assert agg["tipo"][0] == ("Government Bonds", 51.43)
    assert agg["tipo"][1] == ("Private Bonds", 38.07)
    assert agg["setor"] == [("Federal Government", 61.92)]
    # 'Portfolio Composition' / 'Asset' não viram dimensão nem item
    assert "Asset" not in dict(agg.get("classe", []))


def test_html_vazio_nao_quebra():
    cart = parse_carteira_qt("<html></html>")
    assert cart.posicoes == []
    assert cart.datas == []
    assert cart.competencia is None
    assert cart.agregacoes == {}
