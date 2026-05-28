import pandas as pd

from scrapper.analise import gerar_grafico_ativo_html


def test_gera_div_plotly_sem_plotlyjs():
    serie = pd.Series(
        {pd.Timestamp("2024-01-02"): 100.0, pd.Timestamp("2024-01-03"): 100.5},
        name="AMW",
    )
    html = gerar_grafico_ativo_html("AMW", serie)
    assert "<div" in html
    assert "plotly" in html.lower()
    # include_plotlyjs=False: não embute a lib inteira
    assert "Plotly.newPlot" in html


def test_serie_vazia_devolve_string_vazia():
    assert gerar_grafico_ativo_html("X", pd.Series(dtype=float)) == ""
