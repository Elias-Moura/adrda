# Coleta automática desde a primeira cota + retornos persistidos

**Data:** 2026-05-28
**Status:** Aprovado para planejamento

## Problema

Hoje, adicionar um ativo (`adicionar_ativo` individual ou `buscar_ativos` em lote
por Excel) persiste **apenas os metadados**. As cotas só são coletadas depois, num
passo manual (`scrap_cotas`), para uma janela de datas escolhida pelo usuário.

Queremos:

1. **Coletar automaticamente** a série diária completa (da `primeira_cota` até hoje)
   no momento em que o ativo é adicionado.
2. **Persistir o retorno diário** ao lado da cota, para plotar o retorno de qualquer
   janela de datas sem refazer a busca no Quantum.

## Decisão-chave de modelagem

A série que o Quantum devolve é **base-100 ancorada na `data_inicio` requisitada**.
Ao ancorar sempre na `primeira_cota`, o `valor` armazenado vira um **índice canônico**:
o retorno entre quaisquer duas datas é `valor_fim / valor_ini − 1`. Isso já satisfaz
"plotar o retorno de qualquer janela sem rebuscar". As colunas de retorno são, então,
uma **denormalização** (retorno diário pré-computado) para plotagem direta.

## Modelo de dados — `CotacaoDiaria`

Todas as colunas numéricas passam a usar `DecimalField` (precisão > float). Nenhuma
coluna de retorno aceita `NULL`.

| Coluna       | Definição                          | Tipo                                          |
|--------------|------------------------------------|-----------------------------------------------|
| `valor`      | base-100 (existente → vira Decimal) | `DecimalField(max_digits=20, decimal_places=8)` |
| `retorno`    | `valor_t / valor_{t-1} − 1`        | `DecimalField(max_digits=18, decimal_places=12, default=0)` |
| `retorno_ln` | `ln(valor_t / valor_{t-1})`        | `DecimalField(max_digits=18, decimal_places=12, default=0)` |

- **Primeiro ponto da série:** `retorno = 0` e `retorno_ln = 0` (sem ponto anterior;
  convenção compatível com `∏(1+r)` iniciando em 1).
- Retornos são calculados em aritmética `Decimal` (inclusive `retorno_ln` via
  `Decimal.ln()`, com contexto de precisão suficiente).

### Migração

Migração de schema + dados, em uma operação:

1. Adiciona as três colunas (`valor` alterada para Decimal; `retorno`/`retorno_ln`
   novas com `default=0`).
2. **Backfill:** para cada ativo, lê a série `valor` ordenada por data e grava
   `retorno`/`retorno_ln` (reaproveita `recalcular_retornos`, ver abaixo).

## Cálculo do retorno — recálculo por ativo após upsert

`retorno` de um ponto depende do **ponto anterior na série persistida**. Calcular só
dentro do lote buscado deixaria pontos de fronteira incorretos quando janelas são
costuradas (ex.: `scrap_cotas` com range arbitrário, ou índices coletados em lotes).

**Solução:** função pura `recalcular_retornos(ativo) -> int` (em `services.py`) que:

- lê toda a série `valor` do ativo, ordenada por data;
- recalcula `retorno`/`retorno_ln` em `Decimal` para a série inteira (primeiro ponto = 0);
- grava via `bulk_update(["retorno", "retorno_ln"])`.

Idempotente, sempre correta independentemente de como as cotas chegaram, e barata
(milhares de linhas diárias por ativo). Chamada ao final de `coletar_serie`, dentro
de transação, **após** o upsert de `valor`.

*Alternativa rejeitada:* calcular dentro de `parse_serie` — mais rápido, mas deixa
fronteiras erradas ao stitchar janelas.

## Coleta automática (`primeira_cota → hoje`)

Novo método no `QuantumService`:

```python
def coletar_serie_completa(self, ativo: Ativo) -> int:
    """Coleta a série da primeira cota até hoje e persiste cota + retornos."""
    di = ativo.primeira_cota or date(2000, 1, 1)
    return self.coletar_serie(ativo, di, date.today())
```

- **`primeira_cota` nula** (ex.: renda fixa/ação sem inception conhecido): usa a
  **data-piso `date(2000, 1, 1)`**. O Quantum devolve a série a partir da inception
  real (a base-100 ancora no primeiro ponto disponível), então o piso funciona como
  "desde o início".
- **Índices não disparam** coleta automática (são semeados, não "adicionados").

### Gatilhos (ambos os fluxos de adição)

Dentro das threads/jobs **já existentes**, **após** `importar_ativos`:

- `adicionar_ativo` (individual): coleta a série do ativo recém-importado.
- `buscar_ativos` (lote Excel): coleta a série de cada ativo importado.

Falha na coleta de cotas **não derruba** a importação do ativo (já persistido):
loga via `loguru` e segue — mesmo padrão de `coletar_indices`. O `detalhe` do `Job`
reflete quantos ativos tiveram cotas coletadas.

## Fronteira Decimal ↔ float (pandas/quantstats/plotly)

`valor` vira `Decimal` no banco, mas pandas/numpy/quantstats/plotly operam com
`float`. A conversão acontece nos pontos onde uma `pd.Series` é construída a partir
do banco:

- `views.py::_serie_completa` e `_serie_do_banco_range` — `float(v)` ao montar a Series.
- `views.py::exportar_cotas_excel` — `float(v)` ao montar as Series de cotas.

`analise.py` permanece intocado (continua recebendo `pd.Series` de float). O banco é
a fonte de verdade com precisão Decimal; cálculos que exigem numpy usam float na borda.

## Testes

- `recalcular_retornos`: série conhecida → `retorno`/`retorno_ln` esperados; primeiro
  ponto = 0; idempotência (rodar 2× não muda nada).
- `coletar_serie` (client mockado): persiste `valor` Decimal e dispara o recálculo.
- `coletar_serie_completa`: usa `primeira_cota`; cai na data-piso quando nula.
- Migração de backfill: cotas pré-existentes ganham retornos corretos.
- `_serie_completa`/`exportar_cotas_excel`: Series resultante é dtype float.

## Fora de escopo (YAGNI)

- Não há recoleta agendada/automática de novas cotas diárias (só na adição e no
  `scrap_cotas` manual existente).
- Não muda a UI da tela de detalhe (o gráfico de retorno por janela pode ser um
  passo futuro, sobre as colunas agora disponíveis).
