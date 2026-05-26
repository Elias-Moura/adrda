"""
Análise de Carteiras - Quantum Comparador de Ativos
Gera relatório HTML com métricas e gráficos interativos das 5 carteiras.
"""

import json
import warnings
import numpy as np
import pandas as pd
import quantstats as qs
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 1. CONFIGURAÇÕES
# ---------------------------------------------------------------------------

RESPONSE_FILE = "response.json"
OUTPUT_FILE = "relatorio.html"

# Mapeamento dos IDs de índice do Quantum para nomes legíveis
INDICE_NOMES = {
    "1":   "CDI",
    "7":   "IPCA",
    "4":   "IBOVESPA",
    "114": "IMA-B",
    "51":  "IHFA",
    "31":  "IRF-M",
    "15":  "IFIX",
    "453": "BDRX",
    "8":   "Dólar (PTAX)",
}

# Ordem dos requests POST no batch (após os 14 GETs de data)
# Índices [14-18] = 5 carteiras, [19-27] = 9 índices  (EVOLUCAO_DO_ATIVO)
# Índices [28-32] = 5 carteiras, [33-41] = 9 índices  (JANELA_MOVEL)
CARTEIRAS_IDX = list(range(14, 19))
INDICES_IDX   = list(range(19, 28))
JANELA_CART_IDX = list(range(28, 33))

CARTEIRA_NOMES = [
    "Carteira nível 1 2024",
    "Carteira nível 2 2025",
    "Carteira nível 3 2024",
    "Carteira nível 4 2024",
    "Carteira nível 5 2024",
]

INDICE_IDS = ["1", "7", "4", "114", "51", "31", "15", "453", "8"]

# Cores para os gráficos
CORES_CARTEIRAS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
CORES_INDICES   = ["#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
                   "#aec7e8", "#ffbb78", "#98df8a", "#ff9896"]

# ---------------------------------------------------------------------------
# 2. CARGA DOS DADOS
# ---------------------------------------------------------------------------

print("Carregando response.json...")
with open(RESPONSE_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

responses = data["responseList"]


def parse_serie(response_item) -> pd.Series:
    """Converte um item da responseList em pd.Series de valores base-100."""
    body = json.loads(response_item["body"])
    serie = body["serie"]
    datas  = [p["data"] for p in serie]
    valores = [float(p["valor"]) for p in serie]
    idx = pd.to_datetime(datas)
    return pd.Series(valores, index=idx)


# Séries de valor (base 100)
print("Parseando séries de preço...")
precos_carteiras = {
    CARTEIRA_NOMES[i]: parse_serie(responses[CARTEIRAS_IDX[i]])
    for i in range(5)
}

precos_indices = {
    INDICE_NOMES[INDICE_IDS[i]]: parse_serie(responses[INDICES_IDX[i]])
    for i in range(9)
}

# Janela móvel de retorno das carteiras
janelas_carteiras = {
    CARTEIRA_NOMES[i]: parse_serie(responses[JANELA_CART_IDX[i]])
    for i in range(5)
}

# DataFrames consolidados
df_precos = pd.DataFrame({**precos_carteiras, **precos_indices})
df_retornos = df_precos.pct_change().dropna()

df_retornos_carteiras = df_retornos[list(CARTEIRA_NOMES)]
df_retornos_indices   = df_retornos[list(INDICE_NOMES.values())]

print(f"Periodo: {df_precos.index[0].date()} a {df_precos.index[-1].date()}")
print(f"Pontos: {len(df_precos)}")

# ---------------------------------------------------------------------------
# 3. CÁLCULO DE MÉTRICAS
# ---------------------------------------------------------------------------

print("Calculando métricas...")

# Taxa livre de risco: CDI anualizado -> diário (scalar)
cdi_total = (1 + df_retornos["CDI"]).prod() - 1
n_anos    = len(df_retornos["CDI"]) / 252
cdi_anual = (1 + cdi_total) ** (1 / n_anos) - 1
rf_diario = (1 + cdi_anual) ** (1 / 252) - 1


def metricas(nome: str, rets: pd.Series) -> dict:
    """Calcula principais métricas financeiras para uma série de retornos."""
    rets = rets.dropna()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cagr          = qs.stats.cagr(rets)
        vol           = qs.stats.volatility(rets)
        sharpe        = qs.stats.sharpe(rets, rf=cdi_anual)
        sortino       = qs.stats.sortino(rets, rf=cdi_anual)
        max_dd        = qs.stats.max_drawdown(rets)
        calmar        = qs.stats.calmar(rets)
        var95         = qs.stats.value_at_risk(rets, confidence=0.95)
        retorno_total = (1 + rets).prod() - 1

    return {
        "Ativo": nome,
        "Retorno Total": retorno_total,
        "CAGR": cagr,
        "Volatilidade": vol,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Max Drawdown": max_dd,
        "Calmar": calmar,
        "VaR 95%": var95,
    }


todos_ativos = list(CARTEIRA_NOMES) + list(INDICE_NOMES.values())
tabela_metricas = pd.DataFrame([
    metricas(nome, df_retornos[nome]) for nome in todos_ativos
]).set_index("Ativo")

# ---------------------------------------------------------------------------
# 4. FUNÇÕES AUXILIARES PARA GRÁFICOS
# ---------------------------------------------------------------------------

def fmt_pct(v):
    return f"{v*100:.2f}%"


def drawdown_serie(rets: pd.Series) -> pd.Series:
    wealth = (1 + rets).cumprod()
    peak   = wealth.cummax()
    return (wealth - peak) / peak


# ---------------------------------------------------------------------------
# 5. GRÁFICOS PLOTLY
# ---------------------------------------------------------------------------

print("Gerando gráficos...")

# ── 5.1 Evolução de cotas (base 100) ─────────────────────────────────────
fig_cotas = go.Figure()
for i, nome in enumerate(CARTEIRA_NOMES):
    fig_cotas.add_trace(go.Scatter(
        x=df_precos.index, y=df_precos[nome],
        name=nome, line=dict(color=CORES_CARTEIRAS[i], width=2.5),
        hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}<extra>" + nome + "</extra>"
    ))
for i, nome in enumerate(INDICE_NOMES.values()):
    fig_cotas.add_trace(go.Scatter(
        x=df_precos.index, y=df_precos[nome],
        name=nome, line=dict(color=CORES_INDICES[i], width=1.2, dash="dot"),
        visible="legendonly",
        hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}<extra>" + nome + "</extra>"
    ))
fig_cotas.update_layout(
    title="Evolução das Cotas (Base 100)",
    xaxis_title="Data", yaxis_title="Valor (Base 100)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified", height=500,
    plot_bgcolor="#f8f9fa", paper_bgcolor="white"
)

# ── 5.2 Drawdown histórico ────────────────────────────────────────────────
fig_dd = go.Figure()
for i, nome in enumerate(CARTEIRA_NOMES):
    dd = drawdown_serie(df_retornos[nome])
    fig_dd.add_trace(go.Scatter(
        x=dd.index, y=dd * 100,
        name=nome, line=dict(color=CORES_CARTEIRAS[i], width=2),
        fill="tozeroy", fillcolor=CORES_CARTEIRAS[i].replace(")", ", 0.08)").replace("rgb", "rgba") if "rgb" in CORES_CARTEIRAS[i] else None,
        hovertemplate="%{x|%d/%m/%Y}<br>DD: %{y:.2f}%<extra>" + nome + "</extra>"
    ))
fig_dd.update_layout(
    title="Drawdown Histórico das Carteiras (%)",
    xaxis_title="Data", yaxis_title="Drawdown (%)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified", height=450,
    plot_bgcolor="#f8f9fa", paper_bgcolor="white"
)

# ── 5.3 Heatmap de retornos mensais por carteira ─────────────────────────
def heatmap_mensal(nome: str, rets: pd.Series, cor: str) -> go.Figure:
    monthly = (1 + rets).resample("ME").prod() - 1
    monthly.index = monthly.index.to_period("M")
    pivot = pd.DataFrame({
        "ano": monthly.index.year,
        "mes": monthly.index.month,
        "retorno": monthly.values
    }).pivot(index="mes", columns="ano", values="retorno")
    pivot.index = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"][:len(pivot)]

    fig = go.Figure(go.Heatmap(
        z=pivot.values * 100,
        x=[str(c) for c in pivot.columns],
        y=pivot.index.tolist(),
        colorscale=[
            [0.0, "#d73027"], [0.35, "#fee090"],
            [0.5, "#ffffbf"], [0.65, "#e0f3f8"], [1.0, "#1a9850"]
        ],
        zmid=0,
        text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in pivot.values * 100],
        texttemplate="%{text}",
        textfont=dict(size=10),
        colorbar=dict(title="%"),
        hovertemplate="Ano: %{x}<br>Mês: %{y}<br>Retorno: %{z:.2f}%<extra></extra>"
    ))
    fig.update_layout(
        title=f"Retornos Mensais — {nome}",
        xaxis_title="Ano", yaxis_title="Mês",
        height=350, plot_bgcolor="#f8f9fa", paper_bgcolor="white"
    )
    return fig

figs_heatmap = [
    heatmap_mensal(nome, df_retornos[nome], CORES_CARTEIRAS[i])
    for i, nome in enumerate(CARTEIRA_NOMES)
]

# ── 5.4 Janela móvel 20 dias ──────────────────────────────────────────────
fig_janela = go.Figure()
for i, nome in enumerate(CARTEIRA_NOMES):
    s = janelas_carteiras[nome]
    fig_janela.add_trace(go.Scatter(
        x=s.index, y=s * 100,
        name=nome, line=dict(color=CORES_CARTEIRAS[i], width=2),
        hovertemplate="%{x|%d/%m/%Y}<br>%{y:.2f}%<extra>" + nome + "</extra>"
    ))
fig_janela.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
fig_janela.update_layout(
    title="Retorno em Janela Móvel de 20 Dias (%)",
    xaxis_title="Data", yaxis_title="Retorno (%)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified", height=450,
    plot_bgcolor="#f8f9fa", paper_bgcolor="white"
)

# ── 5.5 Bar chart: métricas comparativas ─────────────────────────────────
metricas_bar = ["CAGR", "Volatilidade", "Max Drawdown"]
fig_bar = make_subplots(rows=1, cols=3, subplot_titles=metricas_bar)

for col_idx, metrica in enumerate(metricas_bar, start=1):
    todos_nomes = list(CARTEIRA_NOMES) + list(INDICE_NOMES.values())
    cores = CORES_CARTEIRAS + CORES_INDICES
    vals = tabela_metricas[metrica].loc[todos_nomes].values * 100
    fig_bar.add_trace(go.Bar(
        x=todos_nomes, y=vals,
        marker_color=cores,
        showlegend=False,
        hovertemplate="%{x}<br>" + metrica + ": %{y:.2f}%<extra></extra>"
    ), row=1, col=col_idx)

fig_bar.update_layout(
    title="Comparativo de Métricas — Carteiras vs Índices",
    height=450, plot_bgcolor="#f8f9fa", paper_bgcolor="white"
)
for i in range(1, 4):
    fig_bar.update_xaxes(tickangle=-45, row=1, col=i)

# ---------------------------------------------------------------------------
# 6. TABELA HTML DE MÉTRICAS
# ---------------------------------------------------------------------------

def formatar_tabela(df: pd.DataFrame) -> str:
    """Converte DataFrame de métricas em tabela HTML estilizada."""
    colunas_pct = ["Retorno Total", "CAGR", "Volatilidade", "Max Drawdown", "VaR 95%"]
    colunas_num = ["Sharpe", "Sortino", "Calmar"]

    linhas = []
    for nome, row in df.iterrows():
        eh_carteira = nome in CARTEIRA_NOMES
        classe = "carteira" if eh_carteira else "indice"
        cells = f'<td class="ativo {classe}">{nome}</td>'
        for col in df.columns:
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

    cabecalho = "<tr><th>Ativo</th>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr>"
    return f"""
    <table id="tabela-metricas">
      <thead>{cabecalho}</thead>
      <tbody>{"".join(linhas)}</tbody>
    </table>
    """


tabela_html = formatar_tabela(tabela_metricas)

# ---------------------------------------------------------------------------
# 7. MONTAGEM DO HTML FINAL
# ---------------------------------------------------------------------------

print("Montando relatório HTML...")


def fig_to_html(fig) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})


periodo_inicio = df_precos.index[0].strftime("%d/%m/%Y")
periodo_fim    = df_precos.index[-1].strftime("%d/%m/%Y")
num_dias       = len(df_precos)

html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Relatório de Carteiras — Quantum</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {{
    --primary: #1a3a5c;
    --accent:  #2e86de;
    --bg:      #f4f6f9;
    --card:    #ffffff;
    --border:  #dee2e6;
    --pos:     #27ae60;
    --neg:     #e74c3c;
    --text:    #2c3e50;
    --muted:   #6c757d;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--text); font-size: 14px;
  }}
  header {{
    background: var(--primary); color: white;
    padding: 28px 40px; border-bottom: 4px solid var(--accent);
  }}
  header h1 {{ font-size: 1.7rem; font-weight: 700; }}
  header p  {{ margin-top: 6px; opacity: 0.8; font-size: 0.9rem; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 30px 24px; }}
  .section {{ margin-bottom: 36px; }}
  .section-title {{
    font-size: 1.1rem; font-weight: 700; color: var(--primary);
    border-left: 4px solid var(--accent); padding-left: 12px;
    margin-bottom: 16px;
  }}
  .card {{
    background: var(--card); border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,.08);
    padding: 20px; margin-bottom: 20px;
    overflow: auto;
  }}
  /* KPI badges */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 14px; margin-bottom: 20px;
  }}
  .kpi {{
    background: var(--card); border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0,0,0,.07);
    padding: 16px 20px;
    border-top: 4px solid var(--accent);
  }}
  .kpi-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}
  .kpi-value {{ font-size: 1.4rem; font-weight: 700; margin-top: 4px; }}
  .kpi-sub   {{ font-size: 0.78rem; color: var(--muted); margin-top: 2px; }}
  /* Tabela */
  #tabela-metricas {{
    width: 100%; border-collapse: collapse; font-size: 13px;
  }}
  #tabela-metricas th {{
    background: var(--primary); color: white;
    padding: 10px 12px; text-align: right; font-weight: 600;
    position: sticky; top: 0; z-index: 2;
  }}
  #tabela-metricas th:first-child {{ text-align: left; }}
  #tabela-metricas td {{
    padding: 9px 12px; border-bottom: 1px solid var(--border);
    text-align: right;
  }}
  #tabela-metricas td.ativo {{ text-align: left; font-weight: 600; }}
  #tabela-metricas td.carteira {{ color: var(--primary); }}
  #tabela-metricas td.indice  {{ color: var(--muted); }}
  #tabela-metricas tr:hover td {{ background: #eef2f7; }}
  #tabela-metricas .pos {{ color: var(--pos); font-weight: 600; }}
  #tabela-metricas .neg {{ color: var(--neg); font-weight: 600; }}
  /* Heatmaps em grid */
  .heatmap-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(560px, 1fr));
    gap: 16px;
  }}
  .heatmap-grid .card {{ margin-bottom: 0; }}
  /* Legenda de tipos */
  .legenda {{
    display: flex; gap: 20px; margin-bottom: 12px; flex-wrap: wrap;
  }}
  .legenda-item {{
    display: flex; align-items: center; gap: 6px; font-size: 0.82rem;
  }}
  .dot {{
    width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
  }}
  /* Glossário */
  .glossario-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: 16px;
  }}
  .glossario-item {{
    background: #f8f9fa; border-radius: 8px;
    padding: 14px 16px;
    border-left: 4px solid var(--accent);
  }}
  .glossario-titulo {{
    font-weight: 700; color: var(--primary);
    font-size: 0.92rem; margin-bottom: 6px;
  }}
  .glossario-sigla {{
    font-weight: 400; color: var(--muted); font-size: 0.82rem;
  }}
  .glossario-texto {{
    color: var(--text); font-size: 0.84rem;
    line-height: 1.55;
  }}
  .glossario-texto em {{
    font-style: normal; font-family: monospace;
    background: #e9ecef; padding: 1px 4px; border-radius: 3px;
  }}
  footer {{
    text-align: center; padding: 24px;
    color: var(--muted); font-size: 0.8rem;
    border-top: 1px solid var(--border); margin-top: 20px;
  }}
</style>
</head>
<body>

<header>
  <h1>Relatório de Análise de Carteiras</h1>
  <p>Fonte: Quantum Comparador de Ativos &nbsp;|&nbsp;
     Período: {periodo_inicio} → {periodo_fim} &nbsp;|&nbsp;
     {num_dias} dias úteis</p>
</header>

<div class="container">

  <!-- KPIs de destaque -->
  <div class="section">
    <div class="section-title">Retorno Acumulado (período completo)</div>
    <div class="kpi-grid">
"""

# KPIs das carteiras
for i, nome in enumerate(CARTEIRA_NOMES):
    ret_total = tabela_metricas.loc[nome, "Retorno Total"]
    cagr      = tabela_metricas.loc[nome, "CAGR"]
    sharpe    = tabela_metricas.loc[nome, "Sharpe"]
    cor_dot   = CORES_CARTEIRAS[i]
    html += f"""
      <div class="kpi" style="border-top-color:{cor_dot}">
        <div class="kpi-label">{nome}</div>
        <div class="kpi-value" style="color:{'var(--pos)' if ret_total>0 else 'var(--neg)'}">
          {ret_total*100:.1f}%
        </div>
        <div class="kpi-sub">CAGR {cagr*100:.1f}% &nbsp;|&nbsp; Sharpe {sharpe:.2f}</div>
      </div>
    """

html += """
    </div>
  </div>

  <!-- Tabela completa de métricas -->
  <div class="section">
    <div class="section-title">Métricas Comparativas — Carteiras e Índices</div>
    <div class="legenda">
"""
for i, nome in enumerate(CARTEIRA_NOMES):
    html += f'<div class="legenda-item"><div class="dot" style="background:{CORES_CARTEIRAS[i]}"></div>{nome}</div>\n'
for i, nome in enumerate(INDICE_NOMES.values()):
    html += f'<div class="legenda-item"><div class="dot" style="background:{CORES_INDICES[i]};opacity:.7"></div>{nome}</div>\n'

html += f"""
    </div>
    <div class="card">
      {tabela_html}
    </div>
  </div>

  <!-- Gráfico 1: Evolução de cotas -->
  <div class="section">
    <div class="section-title">Evolução das Cotas (Base 100)</div>
    <p style="color:var(--muted);font-size:.82rem;margin-bottom:10px">
      Índices aparecem como linhas pontilhadas — clique na legenda para exibir/ocultar.
    </p>
    <div class="card">{fig_to_html(fig_cotas)}</div>
  </div>

  <!-- Gráfico comparativo de métricas -->
  <div class="section">
    <div class="section-title">Comparativo: CAGR, Volatilidade e Drawdown Máximo</div>
    <div class="card">{fig_to_html(fig_bar)}</div>
  </div>

  <!-- Gráfico 2: Drawdown -->
  <div class="section">
    <div class="section-title">Drawdown Histórico das Carteiras</div>
    <div class="card">{fig_to_html(fig_dd)}</div>
  </div>

  <!-- Gráfico 3: Janela móvel -->
  <div class="section">
    <div class="section-title">Retorno em Janela Móvel de 20 Dias</div>
    <div class="card">{fig_to_html(fig_janela)}</div>
  </div>

  <!-- Gráfico 4: Heatmaps mensais -->
  <div class="section">
    <div class="section-title">Heatmaps de Retorno Mensal por Carteira</div>
    <div class="heatmap-grid">
"""

for fig_h in figs_heatmap:
    html += f'<div class="card">{fig_to_html(fig_h)}</div>\n'

html += f"""
    </div>
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

</div><!-- /container -->

<footer>
  Gerado automaticamente em Python com Pandas + QuantStats + Plotly &nbsp;|&nbsp;
  Dados: Quantum Comparador de Ativos &nbsp;|&nbsp; {periodo_fim}
</footer>

</body>
</html>
"""

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nRelatorio gerado: {OUTPUT_FILE}")
print(f"  Abra o arquivo no navegador para visualizar.")

# Resumo no terminal
print("\n" + "="*60)
print("RESUMO DE MÉTRICAS")
print("="*60)
cols_show = ["Retorno Total", "CAGR", "Sharpe", "Max Drawdown"]
resumo = tabela_metricas[cols_show].copy()
for c in cols_show:
    if c in ["Retorno Total", "CAGR", "Max Drawdown"]:
        resumo[c] = resumo[c].apply(lambda x: f"{x*100:.2f}%")
    else:
        resumo[c] = resumo[c].apply(lambda x: f"{x:.2f}")
print(resumo.to_string())
