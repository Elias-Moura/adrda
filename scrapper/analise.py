"""
Geração de relatório HTML de carteiras — versão Django.

Recebe dicionários de pd.Series (base 100) e devolve HTML completo.
Extraído e refatorado de analise.py (raiz do projeto).
Diferença principal: janela móvel de 20 dias calculada localmente via
pandas rolling em vez de buscada na API do Quantum.
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

# Paleta base — ampliada dinamicamente quando há mais séries
_CORES_CARTEIRAS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
]
_CORES_INDICES = [
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
]


def _ciclo(paleta: list[str], n: int) -> list[str]:
    """Repete a paleta até ter n cores."""
    return [paleta[i % len(paleta)] for i in range(n)]


def gerar_relatorio_html(
    precos_carteiras: dict[str, pd.Series],
    precos_indices: dict[str, pd.Series],
) -> str:
    """
    Gera um relatório HTML completo de desempenho de carteiras.

    Args:
        precos_carteiras: {nome: pd.Series base-100 com DatetimeIndex}
        precos_indices:   {nome: pd.Series base-100 com DatetimeIndex}

    Returns:
        String HTML completa (standalone, inclui Plotly via CDN).
    """
    import plotly.graph_objects as go
    import quantstats as qs
    from plotly.subplots import make_subplots

    carteira_nomes = list(precos_carteiras)
    indice_nomes = list(precos_indices)

    cores_c = _ciclo(_CORES_CARTEIRAS, len(carteira_nomes))
    cores_i = _ciclo(_CORES_INDICES, len(indice_nomes))

    # ── DataFrames consolidados ───────────────────────────────────────────
    df_precos = pd.DataFrame({**precos_carteiras, **precos_indices})
    df_retornos = df_precos.pct_change().dropna()

    # Janela móvel de 20 dias calculada localmente
    janelas_carteiras: dict[str, pd.Series] = {
        nome: df_retornos[nome]
        .rolling(20)
        .apply(lambda x: (1 + x).prod() - 1, raw=True)
        .dropna()
        for nome in carteira_nomes
    }

    periodo_inicio = df_precos.index[0].strftime("%d/%m/%Y")
    periodo_fim = df_precos.index[-1].strftime("%d/%m/%Y")
    num_dias = len(df_precos)

    # ── Métricas ─────────────────────────────────────────────────────────
    warnings.filterwarnings("ignore")
    cdi_nome = next((n for n in indice_nomes if "CDI" in n.upper()), None)

    if cdi_nome and cdi_nome in df_retornos.columns:
        cdi_total = (1 + df_retornos[cdi_nome]).prod() - 1
        n_anos = len(df_retornos[cdi_nome]) / 252
        cdi_anual = (1 + cdi_total) ** (1 / n_anos) - 1
    else:
        cdi_anual = 0.10  # fallback 10% a.a.

    def _metricas(nome: str, rets: pd.Series) -> dict:
        rets = rets.dropna()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return {
                "Ativo": nome,
                "Retorno Total": (1 + rets).prod() - 1,
                "CAGR": qs.stats.cagr(rets),
                "Volatilidade": qs.stats.volatility(rets),
                "Sharpe": qs.stats.sharpe(rets, rf=cdi_anual),
                "Sortino": qs.stats.sortino(rets, rf=cdi_anual),
                "Max Drawdown": qs.stats.max_drawdown(rets),
                "Calmar": qs.stats.calmar(rets),
                "VaR 95%": qs.stats.value_at_risk(rets, confidence=0.95),
            }

    todos_ativos = carteira_nomes + indice_nomes
    tabela_metricas = pd.DataFrame(
        [_metricas(n, df_retornos[n]) for n in todos_ativos if n in df_retornos.columns]
    ).set_index("Ativo")

    # ── Gráficos ─────────────────────────────────────────────────────────

    def _html(fig) -> str:
        return fig.to_html(
            full_html=False, include_plotlyjs=False, config={"responsive": True}
        )

    # 1. Evolução de cotas
    fig_cotas = go.Figure()
    for i, nome in enumerate(carteira_nomes):
        fig_cotas.add_trace(go.Scatter(
            x=df_precos.index, y=df_precos[nome], name=nome,
            line=dict(color=cores_c[i], width=2.5),
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}<extra>" + nome + "</extra>",
        ))
    for i, nome in enumerate(indice_nomes):
        fig_cotas.add_trace(go.Scatter(
            x=df_precos.index, y=df_precos[nome], name=nome,
            line=dict(color=cores_i[i], width=1.2, dash="dot"),
            visible="legendonly",
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}<extra>" + nome + "</extra>",
        ))
    fig_cotas.update_layout(
        title="Evolução das Cotas (Base 100)", height=500,
        xaxis_title="Data", yaxis_title="Valor (Base 100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified", plot_bgcolor="#f8f9fa", paper_bgcolor="white",
    )

    # 2. Drawdown
    def _drawdown(rets: pd.Series) -> pd.Series:
        wealth = (1 + rets).cumprod()
        return (wealth - wealth.cummax()) / wealth.cummax()

    fig_dd = go.Figure()
    for i, nome in enumerate(carteira_nomes):
        dd = _drawdown(df_retornos[nome])
        fig_dd.add_trace(go.Scatter(
            x=dd.index, y=dd * 100, name=nome,
            line=dict(color=cores_c[i], width=2),
            hovertemplate="%{x|%d/%m/%Y}<br>DD: %{y:.2f}%<extra>" + nome + "</extra>",
        ))
    fig_dd.update_layout(
        title="Drawdown Histórico das Carteiras (%)", height=450,
        xaxis_title="Data", yaxis_title="Drawdown (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified", plot_bgcolor="#f8f9fa", paper_bgcolor="white",
    )

    # 3. Janela móvel 20 dias
    fig_janela = go.Figure()
    for i, nome in enumerate(carteira_nomes):
        s = janelas_carteiras.get(nome, pd.Series(dtype=float))
        if s.empty:
            continue
        fig_janela.add_trace(go.Scatter(
            x=s.index, y=s * 100, name=nome,
            line=dict(color=cores_c[i], width=2),
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}%<extra>" + nome + "</extra>",
        ))
    fig_janela.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_janela.update_layout(
        title="Retorno em Janela Móvel de 20 Dias (%)", height=450,
        xaxis_title="Data", yaxis_title="Retorno (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified", plot_bgcolor="#f8f9fa", paper_bgcolor="white",
    )

    # 4. Bar chart métricas
    metricas_bar = ["CAGR", "Volatilidade", "Max Drawdown"]
    fig_bar = make_subplots(rows=1, cols=3, subplot_titles=metricas_bar)
    todos_cores = cores_c + cores_i
    todos_validos = [n for n in todos_ativos if n in tabela_metricas.index]
    for col_idx, metrica in enumerate(metricas_bar, start=1):
        vals = tabela_metricas.loc[todos_validos, metrica].values * 100
        fig_bar.add_trace(go.Bar(
            x=todos_validos, y=vals,
            marker_color=todos_cores[:len(todos_validos)],
            showlegend=False,
            hovertemplate="%{x}<br>" + metrica + ": %{y:.2f}%<extra></extra>",
        ), row=1, col=col_idx)
    fig_bar.update_layout(
        title="Comparativo de Métricas — Carteiras vs Índices",
        height=450, plot_bgcolor="#f8f9fa", paper_bgcolor="white",
    )
    for i in range(1, 4):
        fig_bar.update_xaxes(tickangle=-45, row=1, col=i)

    # 5. Heatmaps mensais
    def _heatmap(nome: str, rets: pd.Series, cor: str) -> go.Figure:
        monthly = (1 + rets).resample("ME").prod() - 1
        monthly.index = monthly.index.to_period("M")
        pivot = pd.DataFrame({
            "ano": monthly.index.year,
            "mes": monthly.index.month,
            "retorno": monthly.values,
        }).pivot(index="mes", columns="ano", values="retorno")
        meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                 "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
        pivot.index = [meses[m - 1] for m in pivot.index]
        fig = go.Figure(go.Heatmap(
            z=pivot.values * 100,
            x=[str(c) for c in pivot.columns],
            y=pivot.index.tolist(),
            colorscale=[
                [0.0, "#d73027"], [0.35, "#fee090"],
                [0.5, "#ffffbf"], [0.65, "#e0f3f8"], [1.0, "#1a9850"],
            ],
            zmid=0,
            text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row]
                  for row in pivot.values * 100],
            texttemplate="%{text}", textfont=dict(size=10),
            colorbar=dict(title="%"),
            hovertemplate="Ano: %{x}<br>Mês: %{y}<br>Retorno: %{z:.2f}%<extra></extra>",
        ))
        fig.update_layout(
            title=f"Retornos Mensais — {nome}",
            xaxis_title="Ano", yaxis_title="Mês",
            height=350, plot_bgcolor="#f8f9fa", paper_bgcolor="white",
        )
        return fig

    figs_heatmap = [
        _heatmap(nome, df_retornos[nome], cores_c[i])
        for i, nome in enumerate(carteira_nomes)
        if nome in df_retornos.columns
    ]

    # ── Tabela HTML ───────────────────────────────────────────────────────
    colunas_pct = ["Retorno Total", "CAGR", "Volatilidade", "Max Drawdown", "VaR 95%"]
    colunas_num = ["Sharpe", "Sortino", "Calmar"]

    linhas = []
    for nome, row in tabela_metricas.iterrows():
        classe = "carteira" if nome in carteira_nomes else "indice"
        cells = f'<td class="ativo {classe}">{nome}</td>'
        for col in tabela_metricas.columns:
            v = row[col]
            if pd.isna(v):
                cells += "<td>—</td>"
                continue
            if col in colunas_pct:
                txt = f"{v*100:.2f}%"
                cor = "pos" if v > 0 else "neg"
            elif col in colunas_num:
                txt = f"{v:.2f}"
                cor = "pos" if v > 0 else "neg"
            else:
                txt = str(v)
                cor = ""
            cells += f'<td class="{cor}">{txt}</td>'
        linhas.append(f"<tr>{cells}</tr>")

    cabecalho = (
        "<tr><th>Ativo</th>"
        + "".join(f"<th>{c}</th>" for c in tabela_metricas.columns)
        + "</tr>"
    )
    tabela_html = f"""
    <table id="tabela-metricas">
      <thead>{cabecalho}</thead>
      <tbody>{"".join(linhas)}</tbody>
    </table>
    """

    # ── KPI badges ────────────────────────────────────────────────────────
    kpis = ""
    for i, nome in enumerate(carteira_nomes):
        if nome not in tabela_metricas.index:
            continue
        ret_total = tabela_metricas.loc[nome, "Retorno Total"]
        cagr = tabela_metricas.loc[nome, "CAGR"]
        sharpe = tabela_metricas.loc[nome, "Sharpe"]
        cor = cores_c[i]
        kpis += f"""
      <div class="kpi" style="border-top-color:{cor}">
        <div class="kpi-label">{nome}</div>
        <div class="kpi-value" style="color:{'var(--pos)' if ret_total > 0 else 'var(--neg)'}">
          {ret_total*100:.1f}%
        </div>
        <div class="kpi-sub">CAGR {cagr*100:.1f}% &nbsp;|&nbsp; Sharpe {sharpe:.2f}</div>
      </div>
        """

    # ── Legenda ───────────────────────────────────────────────────────────
    legenda = ""
    for i, nome in enumerate(carteira_nomes):
        legenda += f'<div class="legenda-item"><div class="dot" style="background:{cores_c[i]}"></div>{nome}</div>\n'
    for i, nome in enumerate(indice_nomes):
        legenda += f'<div class="legenda-item"><div class="dot" style="background:{cores_i[i]};opacity:.7"></div>{nome}</div>\n'

    heatmaps_html = "".join(f'<div class="card">{_html(f)}</div>\n' for f in figs_heatmap)

    # ── HTML final ────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Relatório de Carteiras — Quantum</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {{
    --primary:#1a3a5c; --accent:#2e86de; --bg:#f4f6f9; --card:#ffffff;
    --border:#dee2e6; --pos:#27ae60; --neg:#e74c3c; --text:#2c3e50; --muted:#6c757d;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px}}
  header{{background:var(--primary);color:white;padding:28px 40px;border-bottom:4px solid var(--accent)}}
  header h1{{font-size:1.7rem;font-weight:700}}
  header p{{margin-top:6px;opacity:.8;font-size:.9rem}}
  header a{{color:rgba(255,255,255,.7);font-size:.85rem;text-decoration:none}}
  header a:hover{{color:white}}
  .container{{max-width:1400px;margin:0 auto;padding:30px 24px}}
  .section{{margin-bottom:36px}}
  .section-title{{font-size:1.1rem;font-weight:700;color:var(--primary);border-left:4px solid var(--accent);padding-left:12px;margin-bottom:16px}}
  .card{{background:var(--card);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.08);padding:20px;margin-bottom:20px;overflow:auto}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-bottom:20px}}
  .kpi{{background:var(--card);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:16px 20px;border-top:4px solid var(--accent)}}
  .kpi-label{{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
  .kpi-value{{font-size:1.4rem;font-weight:700;margin-top:4px}}
  .kpi-sub{{font-size:.78rem;color:var(--muted);margin-top:2px}}
  #tabela-metricas{{width:100%;border-collapse:collapse;font-size:13px}}
  #tabela-metricas th{{background:var(--primary);color:white;padding:10px 12px;text-align:right;font-weight:600;position:sticky;top:0;z-index:2}}
  #tabela-metricas th:first-child{{text-align:left}}
  #tabela-metricas td{{padding:9px 12px;border-bottom:1px solid var(--border);text-align:right}}
  #tabela-metricas td.ativo{{text-align:left;font-weight:600}}
  #tabela-metricas td.carteira{{color:var(--primary)}}
  #tabela-metricas td.indice{{color:var(--muted)}}
  #tabela-metricas tr:hover td{{background:#eef2f7}}
  #tabela-metricas .pos{{color:var(--pos);font-weight:600}}
  #tabela-metricas .neg{{color:var(--neg);font-weight:600}}
  .heatmap-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(560px,1fr));gap:16px}}
  .heatmap-grid .card{{margin-bottom:0}}
  .legenda{{display:flex;gap:20px;margin-bottom:12px;flex-wrap:wrap}}
  .legenda-item{{display:flex;align-items:center;gap:6px;font-size:.82rem}}
  .dot{{width:12px;height:12px;border-radius:50%;flex-shrink:0}}
  footer{{text-align:center;padding:24px;color:var(--muted);font-size:.8rem;border-top:1px solid var(--border);margin-top:20px}}
  .glossario-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px}}
  .glossario-item{{background:#f8f9fa;border-radius:8px;padding:14px 16px;border-left:4px solid var(--accent)}}
  .glossario-titulo{{font-weight:700;color:var(--primary);font-size:.92rem;margin-bottom:6px}}
  .glossario-sigla{{font-weight:400;color:var(--muted);font-size:.82rem}}
  .glossario-texto{{color:var(--text);font-size:.84rem;line-height:1.55}}
  .glossario-texto em{{font-style:normal;font-family:monospace;background:#e9ecef;padding:1px 4px;border-radius:3px}}
</style>
</head>
<body>
<header>
  <h1>Relatório de Análise de Carteiras</h1>
  <p>Fonte: Quantum Comparador de Ativos &nbsp;|&nbsp;
     Período: {periodo_inicio} → {periodo_fim} &nbsp;|&nbsp;
     {num_dias} dias úteis</p>
  <p style="margin-top:8px"><a href="/">← Voltar ao Dashboard</a></p>
</header>
<div class="container">

  <div class="section">
    <div class="section-title">Retorno Acumulado (período completo)</div>
    <div class="kpi-grid">{kpis}</div>
  </div>

  <div class="section">
    <div class="section-title">Métricas Comparativas — Carteiras e Índices</div>
    <div class="legenda">{legenda}</div>
    <div class="card">{tabela_html}</div>
  </div>

  <div class="section">
    <div class="section-title">Evolução das Cotas (Base 100)</div>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:10px">
      Índices aparecem como linhas pontilhadas — clique na legenda para exibir/ocultar.
    </p>
    <div class="card">{_html(fig_cotas)}</div>
  </div>

  <div class="section">
    <div class="section-title">Comparativo: CAGR, Volatilidade e Drawdown Máximo</div>
    <div class="card">{_html(fig_bar)}</div>
  </div>

  <div class="section">
    <div class="section-title">Drawdown Histórico das Carteiras</div>
    <div class="card">{_html(fig_dd)}</div>
  </div>

  <div class="section">
    <div class="section-title">Retorno em Janela Móvel de 20 Dias</div>
    <div class="card">{_html(fig_janela)}</div>
  </div>

  <div class="section">
    <div class="section-title">Heatmaps de Retorno Mensal por Carteira</div>
    <div class="heatmap-grid">{heatmaps_html}</div>
  </div>
    <!-- Glossário de Indicadores -->
  <div class="section">
    <div class="section-title">Glossário de Indicadores</div>
    <div class="card">
      <div class="glossario-grid">

        <div class="glossario-item">
          <div class="glossario-titulo">Retorno Total</div>
          <div class="glossario-texto">
            Variação percentual acumulada do valor da carteira ao longo de todo o período analisado,
            partindo de uma base 100. Um retorno total de 102% significa que R$&nbsp;100 investidos
            tornaram-se R$&nbsp;202.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">CAGR <span class="glossario-sigla">(Compound Annual Growth Rate)</span></div>
          <div class="glossario-texto">
            Taxa de crescimento anual composta — a taxa constante que, aplicada anualmente, produziria
            o mesmo retorno total no período. Permite comparar ativos com históricos de durações diferentes
            em uma mesma base anual.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Volatilidade</div>
          <div class="glossario-texto">
            Desvio padrão anualizado dos retornos diários. Mede o quanto os retornos oscilam em torno
            da média — quanto maior, mais imprevisível o comportamento do ativo no curto prazo.
            Calculada com base em 252 dias úteis por ano.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Índice de Sharpe</div>
          <div class="glossario-texto">
            Mede o retorno em excesso ao CDI (taxa livre de risco) por unidade de risco (volatilidade).
            Fórmula: <em>(CAGR − CDI) ÷ Volatilidade</em>. Quanto maior, melhor a relação
            risco-retorno. Valores acima de 1 são considerados bons; abaixo de 0 indicam que o ativo
            não remunerou o risco assumido além do CDI.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Índice de Sortino</div>
          <div class="glossario-texto">
            Variante do Sharpe que penaliza apenas a volatilidade negativa (downside deviation),
            ignorando os dias de alta. É mais justo para carteiras que oscilam mais para cima do que
            para baixo. Quanto maior, melhor.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Max Drawdown</div>
          <div class="glossario-texto">
            Maior queda percentual observada entre um pico e o vale subsequente ao longo do histórico.
            Representa o pior cenário de perda que um investidor teria sofrido se tivesse entrado no
            pior momento e saído no pior. Essencial para avaliar o risco de perda de capital.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Índice de Calmar</div>
          <div class="glossario-texto">
            Razão entre o CAGR e o valor absoluto do Max Drawdown.
            Fórmula: <em>CAGR ÷ |Max Drawdown|</em>. Responde à pergunta: "quanto de retorno anual
            estou recebendo por cada unidade de queda máxima suportada?". Quanto maior, melhor a
            eficiência na gestão de risco.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">VaR 95% <span class="glossario-sigla">(Value at Risk)</span></div>
          <div class="glossario-texto">
            Perda máxima esperada em um único dia com 95% de confiança estatística. Por exemplo,
            VaR 95% de −1,5% significa que, em condições normais de mercado, há apenas 5% de chance
            de a carteira perder mais de 1,5% em um único dia.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Janela Móvel de 20 Dias</div>
          <div class="glossario-texto">
            Retorno acumulado nos últimos 20 dias úteis (aproximadamente 1 mês), recalculado a cada
            dia. Permite visualizar tendências de curto prazo e identificar períodos de aceleração ou
            desaceleração do desempenho ao longo do tempo.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Drawdown Histórico</div>
          <div class="glossario-texto">
            Série temporal que mostra, em cada data, quanto o valor da carteira está abaixo do seu
            pico histórico anterior. Um drawdown de 0% indica que a carteira está em máxima histórica;
            valores negativos mostram a magnitude da queda em relação ao topo mais recente.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">Heatmap de Retornos Mensais</div>
          <div class="glossario-texto">
            Tabela colorida com o retorno de cada mês em cada ano. Verde indica retorno positivo,
            vermelho indica retorno negativo — quanto mais intenso, maior a magnitude. Permite
            identificar sazonalidades, períodos de crise e consistência da carteira ao longo do tempo.
          </div>
        </div>

        <div class="glossario-item">
          <div class="glossario-titulo">CDI <span class="glossario-sigla">(Certificado de Depósito Interbancário)</span></div>
          <div class="glossario-texto">
            Taxa de referência do mercado financeiro brasileiro, utilizada como benchmark de renda fixa
            e como taxa livre de risco no cálculo do Sharpe e Sortino. Representa o custo de
            oportunidade mínimo esperado por um investidor conservador.
          </div>
        </div>

      </div>
    </div>
  </div>
</div>
<footer>
  Gerado com Python · Pandas · QuantStats · Plotly &nbsp;|&nbsp;
  Dados: Quantum Comparador de Ativos &nbsp;|&nbsp; {periodo_fim}
</footer>
</body>
</html>"""


def gerar_grafico_ativo_html(nome: str, serie) -> str:
    """Figura Plotly da evolução base-100 de um único ativo.

    Devolve um fragmento HTML (div) sem a lib Plotly embutida — a página inclui
    o Plotly via CDN. Série vazia -> string vazia (o template mostra um aviso).
    """
    if serie is None or len(serie) == 0:
        return ""
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(serie.index), y=list(serie.values), name=nome,
        line=dict(color="#0d6efd", width=2.5),
        hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        height=420, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Data", yaxis_title="Valor (Base 100)",
        plot_bgcolor="#f8f9fa", paper_bgcolor="white", showlegend=False,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
