import pandas as pd

from scrapper.analise import gerar_grafico_ativo_html


def test_gera_fragmento_autossuficiente_com_cdn():
    serie = pd.Series(
        {pd.Timestamp("2024-01-02"): 100.0, pd.Timestamp("2024-01-03"): 100.5},
        name="AMW",
    )
    html = gerar_grafico_ativo_html("AMW", serie)
    assert "<div" in html
    assert "Plotly.newPlot" in html
    # include_plotlyjs="cdn": a tag da CDN vem ANTES do Plotly.newPlot,
    # para a lib estar carregada quando o gráfico é plotado.
    assert "cdn.plot.ly" in html
    assert html.index("cdn.plot.ly") < html.index("Plotly.newPlot")


def test_serie_vazia_devolve_string_vazia():
    assert gerar_grafico_ativo_html("X", pd.Series(dtype=float)) == ""
