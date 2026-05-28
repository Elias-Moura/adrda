# Processamento local de cotas por janela (re-base) no relatório

**Data:** 2026-05-28
**Status:** Aprovado para planejamento

## Problema

A view `relatorio` ainda busca a série no Quantum sob demanda quando não há dados
na janela pedida, e exibe a série usando o `valor` canônico (base-100 ancorado na
`primeira_cota`) — que **não** começa em 100 na data inicial da janela.

Como agora persistimos o `valor` como índice canônico **e** o retorno diário, qualquer
janela pode ser reconstruída localmente, re-baseada para 100 na data inicial pedida,
sem tocar no Quantum para fundos que já temos.

## Escopo

Apenas a view **`relatorio`** (`scrapper/views.py`). `exportar_cotas_excel` e
`detalhe_ativo` já leem somente do banco e ficam intocadas.

## Mudança 1 — Re-base local da janela

Hoje `relatorio` passa para `gerar_relatorio_html` o resultado de
`_serie_do_banco_range(ativo, di, df)`, que devolve o `valor` canônico fatiado (não
começa em 100). Passamos a re-basear:

- `rebasear_base_100(serie: pd.Series) -> pd.Series` — **função pura**:
  `serie / serie.iloc[0] * 100`. Série vazia → série vazia. Sem banco, testável isolada.
- `_serie_rebaseada(ativo, di, df) -> pd.Series` — thin wrapper: chama
  `_serie_do_banco_range(ativo, di, df)` e aplica `rebasear_base_100`. Cada série começa
  em 100 no primeiro ponto disponível dentro da janela.

A `relatorio` passa a usar `_serie_rebaseada` no lugar de `_serie_do_banco_range`.

### Equivalência valor ↔ retorno

Re-basear via `valor_t / valor_di × 100` é matematicamente idêntico a compor o retorno
diário armazenado (`100 × ∏(1 + retorno)` dentro da janela), pois `retorno` foi derivado
de `valor`. Usamos `valor` por ser uma expressão única, exata e sem drift cumulativo.
A coluna `retorno` permanece a ferramenta apropriada para um futuro gráfico dedicado de
*retorno* (não de cota).

As métricas do relatório (Sharpe, CAGR, volatilidade, drawdown, heatmaps) derivam de
`df_precos.pct_change()` e são scale-invariant — **não mudam** com o re-base. O re-base
só altera a escala absoluta do gráfico "Evolução das Cotas (Base 100)".

## Mudança 2 — Eliminar a busca no Quantum quando já temos o ativo

No loop da `relatorio`, a checagem atual (`existe dado na janela? → senão busca a
janela`) é trocada por:

- Se o ativo **não tem nenhuma `CotacaoDiaria`** armazenada → uma coleta completa única
  `service.coletar_serie_completa(ativo)` (primeira_cota → hoje; piso 2000-01-01 para
  índices). Depois disso serve do banco.
- Se já tem qualquer cota → **100% local** (fatia + re-base), sem tocar no Quantum.

A falha na coleta não derruba o relatório: é capturada e ignorada (o ativo apenas não
aparece se continuar sem dados), no mesmo estilo do código atual.

## Fluxo de dados (relatorio)

```
para cada ativo selecionado:
    se not CotacaoDiaria.objects.filter(ativo=ativo).exists():   # nunca coletado
        coletar_serie_completa(ativo)        # 1x; falha é ignorada
    serie = _serie_rebaseada(ativo, di, df)  # local; re-base 100 na data inicial
    se serie vazia: pula
    índice  -> precos_indices[nome] = serie
    senão   -> precos_carteiras[nome] = serie
gerar_relatorio_html(precos_carteiras, precos_indices)
```

`gerar_relatorio_html` permanece intocado (continua recebendo dicts de `pd.Series`
base-100 em float).

## Testes

- `rebasear_base_100`: série conhecida → primeiro ponto = 100 e razões preservadas;
  série vazia → vazia.
- `_serie_rebaseada`: rows no banco → janela re-baseada correta, dtype float.
- `relatorio` (view):
  - ativo com dados cobrindo a janela → `QuantumService` **não** é instanciado/chamado.
  - ativo sem nenhuma cota → `coletar_serie_completa` chamado uma vez.

## Fora de escopo (YAGNI)

- **Freshness:** buscar dias recentes faltantes além do último dado armazenado — não
  nesta feature.
- Mudanças em `exportar_cotas_excel` e `detalhe_ativo`.
- Gráfico dedicado de retorno (consumiria a coluna `retorno` diretamente) — feature futura.
