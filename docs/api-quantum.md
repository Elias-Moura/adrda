# API do Quantum — engenharia reversa

> **Status:** documento de descoberta. Estamos mapeando como a API do Quantum
> funciona para, depois, ajustar o back-end e torná-lo mais flexível (suporte a
> ETFs, BDRs, FIIs e fundos, busca por nome/ticker além de CNPJ). Nada aqui é
> definitivo — é o registro do que foi observado na rede.

Base URL: `https://www.comparadordeativos.com.br`

Toda a captura foi feita via **Playwright MCP** (login manual na janela do
Chromium, inspeção com `browser_network_requests`). Ver memória
`captura-requisicoes-quantum`.

---

## Autenticação

Sessão baseada em **cookie `JSESSIONID`** (setado no login). As chamadas de
busca usam apenas o cookie; o **Bearer JWT** (obtido em `/token/refresh`) é
exigido nas chamadas à API de dados (`/b`).

| Passo | Método | Endpoint | Observação |
|-------|--------|----------|------------|
| Login | `POST` | `/webaxis/webaxis2/notAuthorised/login/logar/realizaLogin` | Body JSON `{username, senha, autenticador, isNavegadorChrome, paginaRedirecionar}`; seta `JSESSIONID` |
| Token | `GET` | `/webaxis/webaxis2/token/refresh?_=<ts_ms>` | Devolve o Bearer JWT |

---

## Busca de ativos (`buscaGlobal`)

Único endpoint, usado em dois modos. **Mesma URL**, muda só o parâmetro `isCNPJ`.

```
GET /webaxis/webaxis2/buscaGlobal/ajax/buscar
```

| Parâmetro | Busca por CNPJ | Busca por texto (UI "Search assets") |
|-----------|----------------|--------------------------------------|
| `filtroBusca` | `defaultSearch` | `defaultSearch` |
| `searchString` | CNPJ (url-encoded) | nome ou ticker (url-encoded) |
| `isCNPJ` | `true` | `false` |
| `cancelaBusca` | — | `false` |
| `isCodigoSUSEP` | — | `false` |
| `codigoGrupoExpandido` | — | `` (vazio) |
| `quantidadeMaximaPorGrupo` | — | `5` |
| `_` | — | timestamp em ms (cache-buster) |

**Headers relevantes:** `accept: application/json, text/javascript, */*; q=0.01`,
`content-type: application/x-www-form-urlencoded`, `x-requested-with: XMLHttpRequest`.
Autenticação só pelo cookie `JSESSIONID` (não precisa de Bearer aqui).

**Encoding:** resposta em `ISO-8859-1` (`Content-Type: application/json;charset=ISO-8859-1`).
Tratada pelo fallback latin-1 de `_decode_json`.

### Formato da resposta

A resposta é uma **lista de grupos** (cada `codigoGrupo` é um tipo/agrupamento).
Uma mesma pesquisa pode retornar **vários grupos**.

```jsonc
[
  {
    "codigoGrupo": 0,
    "totalResultados": 1,
    "primeirosResultados": [
      {
        "itemSelecionavel": {
          "label": "AMW CASH CLASH FI RENDA FIXA LP",
          "identificador": "612014",          // id_quantum
          "tipoItemSelecionavel": "FI"         // = {tipo} usado em /api/ativos/{tipo}/...
        },
        "informacaoAdicional": "CNPJ: 42.550.188/0001-91 | Situation: Active | Management Company: Amw Asset Management",
        "codigoGrupo": 0
      }
    ]
  }
]
```

- `tipoItemSelecionavel` é o **mesmo valor** usado como `{tipo}` nas chamadas a
  `/api/ativos/{tipo}/{id}/...`.
- O **CNPJ** (e a gestora) só aparecem dentro da string `informacaoAdicional`,
  e somente para fundos. Para ações (`ACAO`) vem `Type: ... | Stock Exchange: ...`.

### Casos observados (2026-05-26)

| Pesquisa | Grupos retornados | `tipoItemSelecionavel` | `identificador` | Detalhe em `informacaoAdicional` |
|----------|-------------------|------------------------|-----------------|----------------------------------|
| `HASH11` (ETF cripto) | **2** | `FI` + `ACAO` | `587494` / `27343` | fundo de índice **e** ETF de bolsa |
| `KNCR11` (FII) | 1 | `FII` | `32706958` | CNPJ + gestora |
| `BIAU39` (BDR) | 1 | `ACAO` | `15337` | `Type: BDR \| Stock Exchange: BMFBovespa` |
| `AMW Cash Clash` (fundo) | 1 | `FI` | `612014` | CNPJ `42.550.188/0001-91` |
| `VALE3` (ação) | **2** | `ACAO` + `RENDA_FIXA` | `700` / **`"VALE38"`** | ação `Type: Stocks`; debênture `Type: Debênture` |

**Subtipos de `ACAO`.** Ação, BDR e ETF são **todos** `tipoItemSelecionavel=ACAO`,
com o **mesmo** conjunto de 14 medidas e os mesmos endpoints. O subtipo aparece só
no `informacaoAdicional`: `Type: Stocks` (ação), `Type: BDR`, `Type: ETF`.

**`identificador` nem sempre é numérico.** FI/FII/ACAO/INDICE usam id numérico,
mas **`RENDA_FIXA` (debêntures) usa código string** (ex.: `"VALE38"`).

> **Pontos-chave para o back-end:**
> - O `HASH11` e o `VALE3` provam que a busca por nome/ticker pode devolver
>   **vários candidatos de tipos diferentes** (FI+ACAO; ACAO+RENDA_FIXA). O código
>   de CNPJ assume `dados[0]['primeirosResultados'][0]` — pega cegamente o 1º
>   grupo. Para busca por texto é preciso **escolher o tipo certo**.
> - ⚠️ `_parsear_resultados_busca` faz `int(item["identificador"])` —
>   **quebra (`ValueError`) em resultados `RENDA_FIXA`** com id string. Tratar o
>   identificador como string (ou tolerar não-numéricos).

---

## API de dados (`/b` — multiplex)

Endpoint multiplex (`POST /b`) que empacota uma ou mais sub-requisições com
`relativeUrl`. Já mapeado anteriormente; resumo:

| `relativeUrl` | Uso |
|---------------|-----|
| `/api/ativos/{tipo}/{id}/medidas/valor` | Dados complementares (CNPJ, gestão, taxas, início do fundo, etc.) |
| `/api/ativos/{tipo}/{id}/medidas/serie` | Série temporal de cotas (base 100) |

Para `PORTFOLIO`, o identificador na URL é o **nome url-encoded** em vez do id
numérico (ver `resolve_relative_url`).

### Conjuntos de medidas de `medidas/valor` por tipo (capturado 2026-05-26)

A resposta de `/medidas/valor` (`responseList[0].body`) é uma **lista posicional**
de `{"valor": ...}` — **sem o nome da medida**. A ordem é definida pelo array de
`{"medida": ...}` que **nós enviamos** no body da sub-requisição. Capturadas as
três ordens reais (multiplex `/b`, comparação FI+FII+ACAO):

**`FI` — 24 medidas:**
```
NOME, CLASSIFICACAO_LEGAL, CNPJ, GESTAO, CLASSIFICACAO_ANBIMA, BENCHMARK,
ABERTO_PARA_CAPTACAO, PUBLICO_ALVO, TAXA_ADMINISTRACAO_E_GESTAO,
TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA, TAXA_DE_PERFORMANCE,
TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA, APLICACAO_MINIMA,
CONVERSAO_DA_COTA_PARA_APLICACAO, CONVERSAO_DA_COTA_PARA_RESGATE,
DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS, TAXAS_INFORMACOES_ADICIONAIS_EXTRA,
INICIO_DO_FUNDO, MOVIMENTACAO_MINIMA, DIVULGACAO, PORCENTAGEM_RENDA_VARIAVEL_FIE,
TAXA_DE_RESGATE_EXTRA, TRIBUTACAO, POSSUI_SERIE
```
> Nota: a contagem real é **24** (o doc de design dizia "25"; vale a captura).

**`FII` — 22 medidas:**
```
NOME, CLASSIFICACAO_LEGAL, CNPJ, ADMINISTRADOR, GESTAO, PUBLICO_ALVO,
CLASSIFICACAO_ANBIMA, INVESTIMENTO_TIPO_DE_IMOVEL, INVESTIMENTO_QUANTIDADE_DE_IMOVEIS,
RENTABILIDADE_ALVO, SITUACAO_ATUAL, TAXA_ADMINISTRACAO_E_GESTAO, TAXA_DE_PERFORMANCE,
TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA, INVESTIMENTO_LOCALIZACAO_DO_IMOVEL_EXTRA,
TAXAS_INFORMACOES_ADICIONAIS_EXTRA, INICIO_DO_FUNDO, APLICACAO_MINIMA,
MOVIMENTACAO_MINIMA, DIVULGACAO, TRIBUTACAO, POSSUI_SERIE
```

**`ACAO` (ação/BDR/ETF) — 14 medidas:**
```
NOME, TIPO_DE_ATIVO, TICKER, CLASSE, BOLSA, SETOR_QUANTUM, CONTROLE_ACIONARIO,
GOVERNANCA_CORPORATIVA, INICIO_DO_FUNDO, TAXA_DE_ADMINISTRACAO, APLICACAO_MINIMA,
MOVIMENTACAO_MINIMA, TRIBUTACAO, POSSUI_SERIE
```
> O subtipo (`Stocks`/`AÇÃO`, `BDR`, `ETF`) sai de `TIPO_DE_ATIVO`; `ticker` de
> `TICKER`; `setor` de `SETOR_QUANTUM`. ACAO **não** tem `CNPJ` nem `GESTAO`.

`INDICE` e `RENDA_FIXA` **não** apareceram com card de `medidas/valor` nesta
captura (índice é semeado por catálogo; só precisa de série). Tratar metadados
desses dois como tolerantes/mínimos até haver captura própria.

---

## Retorno de dados (séries) e benchmarks

Capturado ao abrir a comparação dos 4 ativos + CDI/IPCA (26/05/2026). **Validado
contra a implementação atual — `get_retorno_carteira` e `monta_df_rentabilidade_diaria`
estão corretos.**

### Série de cotas (`EVOLUCAO_DO_ATIVO`)

Payload enviado pelo site é **idêntico** ao que `get_retorno_carteira` monta:

```jsonc
// relativeUrl: /api/ativos/{tipo}/{id}/medidas/serie  (dentro do multiplex POST /b)
{
  "medida": "EVOLUCAO_DO_ATIVO",
  "dataInicial": "2021-09-13",
  "dataFinal": "2026-05-25",
  "propriedades": { "valorBase": 100, "periodicidade": "DIARIA" }
}
```

Resposta (`responseList[0].body`, string JSON) — formato que o parser já consome:

```jsonc
{
  "formatoExibicaoData": "MM/dd/yyyy",
  "formato": "MOEDA",
  "serie": [
    { "data": "2025-05-26", "valor": "100.0" },
    { "data": "2025-05-27", "valor": "100.05565696321608" }
    // ... um ponto por dia útil, base 100
  ]
}
```

> Única diferença observada: o site manda `Accept-Language: en-US` (UI em inglês);
> o código usa `pt-BR`. Irrelevante para a série.

### Benchmarks = ativos do tipo `INDICE`

**Não existe endpoint separado de benchmark.** Índices são ativos `INDICE` e usam
o **mesmo** `/api/ativos/INDICE/{id}/medidas/serie` com `EVOLUCAO_DO_ATIVO`. Para
puxar o CDI basta `AtivoQuantum(tipo="INDICE", id_quantum=1)`.

Lista de `/api/benchmarks/porFuncionalidade/COMPARACAO` (id → descrição):

| id | Benchmark | id | Benchmark |
|----|-----------|----|-----------|
| 1 | CDI | 31 | IPCA |
| 4 | Ibovespa | 51 | IMA-B |
| 7 | Dólar | 15 | IRF-M |
| 114 | IDA-DI | 453 | Poupança (Selic) |
| 8 | Poupança | | |

### Métricas de risco — disponíveis na API, mas calculáveis localmente

A aba de análise de risco dispara medidas prontas via `/medidas/valor` e
`/medidas/serie`: `RETORNO`, `PORCENTAGEM_BENCHMARK_RETORNO` (% do CDI),
`RETORNO_MEDIO_ANUALIZADO`, `VOLATILIDADE`, `SHARPE` (`ativoSemRisco: CDI`),
`RETORNO_MAXIMO/MINIMO/MEDIO`, `NUM_VEZES_RETORNO_POSITIVO/NEGATIVO`,
`JANELA_MOVEL_RETORNO_EFETIVO` (`valorJanela: 20` — média móvel de 20 dias).

**Decisão de projeto:** todas essas métricas podem ser calculadas do nosso lado a
partir da série diária (`EVOLUCAO_DO_ATIVO`) com pandas/numpy. Preferir o cálculo
local em vez de depender desses endpoints (menos requisições, mais controle).

### Multiplex em lote — oportunidade

O site empacota **vários ativos numa única requisição `/b`**: o gráfico de
evolução mandou os 4 ativos + ~9 índices num só POST (cada um como uma
sub-requisição no array `requests`). Nosso código hoje faz **uma chamada `/b` por
ativo**. Dá para batelar N ativos por requisição — ganho relevante para o `scrap`.

## Extrato / carteira investida (composição dos ativos)

Capturado em 26/05/2026 e **confirmado/implementado em 28/05/2026** (fundo AMW Cash
Clash, `id_quantum=612014`). **Esta parte NÃO é a API REST limpa** — são páginas HTML
renderizadas no servidor (servlet `.qt`, com jQuery; **não é Wicket**), com estado
preso à sessão por uma `chave` (UUID).

> ✅ **Implementado** em `scrapper/quantum/carteira_html.py` (parser),
> `QuantumClient.abrir_carteira_fundo`/`trocar_competencia_carteira` (transporte) e
> `QuantumService.sincronizar_carteiras` (orquestração). A tela `/ativos/<id>/`
> consome isso com seletor de competências, valor em R$ mil e agregações.

### Disponibilidade por tipo de ativo (testado)

| Tipo | Tem carteira investida? | Evidência |
|------|-------------------------|-----------|
| `FI` (fundo) | ✅ Sim | `statusCode 200` + payLoad |
| `FII` | ✅ Sim | `statusCode 200` + payLoad (`codigo=32706958`) |
| `ACAO` (BDR/ETF) | ❌ Não | `statusCode 500` — *"The fund has no portfolio."* |

> Ou seja: BDR/ação não tem composição (papel único, sem portfólio subjacente),
> mas **FII tem** (patrimônio em imóveis/cotas).

### Dois relatórios

- **`carteiraFundo.qt`** — carteira **direta** do fundo. ✅ É a que usamos.
- **`carteiraPortfolio.qt`** — carteira **consolidada** (look-through de fundos
  aninhados). Para fundos simples os dois batem; para fundos de fundos diferem.
  ⚠️ **Bloqueada fora do contexto de comparação:** acessar direto retorna *"It was
  not possible to create the portfolio"*. Só abre depois de adicionar o ativo à
  ferramenta de comparação. Por isso a implementação usa a **direta**.

### Fluxo (confirmado e reproduzido)

A página real exige **dois POSTs** (a `wait.jsp` é só uma tela de "Loading" que
faz `document.form.submit()` automaticamente para o `.qt`). Sequência:

```
1. GET /webaxis/wait.jsp?codigo=612014&mostrarProgresso=true
       &gotopage=carteiraFundo.qt&acao=acessoDireto&esconderBotaoVoltar=true
   → página de espera com um <form method=post action="carteiraFundo.qt"> oculto.

2. POST /webaxis/carteiraFundo.qt
   data: codigo=612014, gotopage=carteiraFundo.qt, acao=acessoDireto, esconderBotaoVoltar=true
   → HTML completo (~205 KB) da competência MAIS RECENTE, com o <select id="datas">,
     a tabela de posições, as agregações e a `chave` (UUID minúsculo, aparece como
     &chave=... no JS inline). É o primeiro UUID minúsculo do HTML.

3. Trocar competência (dado o HTML atual, de onde se extrai a chave):
   a) GET /webaxis/wait.jsp?gotopage=carteiraFundo.qt&acao=alterarData
          &data=MM/DD/YYYY&chave=<uuid_atual>&ocultarAtivosSemParticipacao=false
      → nova página de espera com uma `chave` RENOVADA no form.
   b) POST /webaxis/carteiraFundo.qt
          data: gotopage=carteiraFundo.qt, acao=alterarData, data=MM/DD/YYYY,
                chave=<uuid_renovado>, ocultarAtivosSemParticipacao=false
      → HTML completo da competência pedida (que traz, por sua vez, a chave do
        próximo passo). Encadeia-se assim por todas as competências.

   (Export Excel/PDF: GET carteiraFundo.qt?acao=exportarExcel|exportarPDF&chave=<uuid>
    — porém o Excel retornou página de erro fora do contexto vivo; preferimos
    raspar o HTML do passo 2/3, que já tem tudo.)
```

> ⚠️ **Competência = último dia ÚTIL do mês**, não o dia 1º nem o último dia de
> calendário. Ex.: `02/27/2026` (28 é sábado), `11/28/2025` (30 é domingo). Mandar
> a data errada faz o REST devolver `[]` e o `.qt` não achar a competência. A lista
> certa vem pronta no `<select id="datas">` (MM/DD/YYYY) — não precisa adivinhar.

### Dados disponíveis no relatório

- Cabeçalho: nome, **data de competência** (`<select id="datas">`; no AMW, 56 meses
  de 09/2021 a 04/2026), CNPJ, gestão.
- Agregações com %: **Asset Type** (Government Bonds, Private Bonds, Committed
  operation, Derivative...), **Sector** (Federal Government, Banks...), **Risk**
  (Rating AAA, Market's risk...), **Class** (Selic, Inflation, Prefixed...). No HTML
  vêm como pares `<font color="#004379">rótulo</font>` / `<font color="#004379">%</font>`,
  em ordem, com os 4 cabeçalhos de dimensão e terminando em `Portfolio Composition`.
- **Composição** (tabela, ~52 linhas): `Nome | Valor (milhares) | Participação %`.
  Cada linha tem `exibirDetalhes('<uuid>')` na âncora do nome; valor/participação em
  `<font><font>85,517.91</font></font>` (formato en-US: vírgula de milhar, ponto
  decimal). Ex.: `LFT - Venc.: 01/03/2030 | 85,517.91 | 12.3351 %`.

### Estratégia de reprodução (implementada)

1. Raspar o **HTML** dos passos 2/3 (parser em `carteira_html.py`). O Export Excel
   é frágil (estado preso à sessão; deu página de erro fora do contexto vivo).
2. ⚠️ **Rótulos ficam em INGLÊS** mesmo mandando `Accept-Language: pt-BR` — a conta
   está fixada em inglês. O parser identifica as 4 dimensões pelos cabeçalhos fixos
   (`Asset Type`/`Sector`/`Risk`/`Class`) e as posições pela estrutura
   (`exibirDetalhes` + `<font>` aninhado), não por texto traduzível.
3. ⚠️ **Conta single-session:** um login do backend **derruba** quem estiver no
   navegador com o mesmo usuário (e vice-versa). A sincronização de todas as
   competências leva ~40 s; rodar como Job e, idealmente, com conta dedicada.

### Alternativa REST JSON (`/api/ativos/{tipo}/{id}/carteira`) — inspecionado

Há um endpoint REST JSON de carteira (dentro do multiplex `/b`), visto nos cards
de comparação:

```
/api/ativos/{tipo}/{id}/carteira?identificador={id}&tipoItemQuantum={tipo}
  &tipoCarteira=INDIVIDUAL|CONSOLIDADA&dataCompetencia=YYYY-MM-DD
  &quantidade={N}&exibirSomatorioOutros=true
```

Resposta (`responseList[0].body`, string JSON) = lista de `{ativo, participacao}`:

```jsonc
[
  {"ativo":"LFT - Venc.: 01/03/2030","participacao":"12.33510179749553600"},
  // ...
  {"ativo":"Outros Ativos","participacao":"29.75195144..."}  // só se quantidade < total
]
```

**Testado (26–28/05/2026):**

| Tipo | Resultado |
|------|-----------|
| `FI`, `quantidade=10` | top-10 + linha `"Outros Ativos"` (somatório do resto) |
| `FI`, `quantidade=100` | **carteira completa** (53 itens, sem agrupar) |
| `FI`, `tipoCarteira=CONSOLIDADA` | **funciona** (consolidada, participação confere com a tela) |
| `FII`, `INDIVIDUAL`/`CONSOLIDADA` | **`[]` vazio** — não exposto por aqui |

> ⚠️ Mesma regra de competência do `.qt`: `dataCompetencia` precisa ser o **último
> dia útil do mês** (exato). `dataCompetencia` é obrigatório; sem ele → 400. Não há
> endpoint que liste as competências (testados `/carteira/datasDisponiveis`,
> `/competencias`, etc. → todos 404); a lista só vem do `<select>` do `.qt`.

**Conclusões:**

- ✅ Para **FI**, com `quantidade` alto, é a via mais limpa para **participação**:
  composição completa em JSON, sem o fluxo `chave`+HTML. Aceita
  `tipoCarteira=CONSOLIDADA`.
- ❌ Só traz `ativo` + `participacao` — **não** tem valor em milhares, agregações,
  nem a lista de competências (isso só no relatório `.qt`).
- ❌ **FII retorna vazio** — para composição de FII, usar o extrato `.qt`.
- ⚠️ `/b` **exige o Bearer token** (`authorization`); só o cookie → 401 (Varnish).
  `_headers_api()` já envia o token. (A busca global e o `laminaFundo` aceitam só
  o cookie JSESSIONID.)

**Resumo da decisão:**

| Necessidade | Via recomendada |
|-------------|-----------------|
| Valor (milhares) + agregações + lista de competências (**o que a app usa**) | Relatório `.qt` `carteiraFundo.qt` (scrape HTML) |
| Só a % de cada posição de **FI** (mais leve) | REST JSON `/carteira` (`QuantumService.coletar_carteira`) |
| Composição de **FII** | Extrato `.qt` (`laminaFundo`) — REST vem vazio |
| **BDR/ação** | Não há carteira |

---

## Reprodução em Python

Implementado em `quantum_scrapper.py`:

| Símbolo | Papel |
|---------|-------|
| `ResultadoBusca` (dataclass) | Candidato achatado: `label`, `tipo`, `id_quantum`, `cnpj`, `codigo_grupo` |
| `buscar_ativos(termo, max_por_grupo=5)` | Busca por texto (sync); achata todos os grupos |
| `_buscar_ativos_async(termo, client)` | Variante async (padrão trio do projeto) |
| `_parsear_resultados_busca(grupos)` | Achata grupos + extrai CNPJ de `informacaoAdicional` via regex |
| `_build_url_busca_texto(termo, max)` | Monta a URL idêntica à do navegador |

Exemplo:

```python
qs = QuantumScrapper().login()
for r in qs.buscar_ativos("HASH11"):
    print(r.tipo, r.id_quantum, r.label)
# FI    587494  HASHDEX NASDAQ CME CRYPTO INDEX ... - HASH11
# ACAO   27343  HASHDEX NCI CI - HASH11
```

---

## Pendências para a flexibilização do back-end

- [ ] **Seleção de tipo na busca por texto.** Decidir a estratégia quando há
  múltiplos grupos: preferência por tipo (`FI` > `ACAO`?), filtro explícito pelo
  chamador, ou retornar todos e deixar a camada superior escolher.
- [ ] **Unificar busca por CNPJ e por texto.** Hoje `req_cnpj` e `buscar_ativos`
  compartilham endpoint mas têm parsing diferente. `_processar_ativo_async`
  ainda assume `dados[0][...][0]`; alinhar para usar `_parsear_resultados_busca`.
- [ ] **Mapear ETFs/BDRs (`ACAO`) no pipeline.** Hoje ativos sem CNPJ são
  ignorados com `WARNING`. Com a busca por texto + `tipoItemSelecionavel`, dá
  para suportá-los (eles não têm CNPJ, mas têm `id_quantum` e `tipo=ACAO`).
- [ ] **Coluna `tipo`/`ticker` no Excel de entrada** para indicar a estratégia
  de busca (CNPJ vs. ticker) por ativo.
- [ ] **`medidas/valor` usa conjuntos de medidas distintos por tipo.** Capturado:
  `FI`=25 medidas, `FII`=22 (com `ADMINISTRADOR`, `INVESTIMENTO_*`), `ACAO`=14
  (com `TICKER`, `BOLSA`, `SETOR_QUANTUM`, sem `CNPJ`). O código atual
  (`_build_payload_dados_complementares` + `_simplificar_retorno_multiplex`)
  tem a lista de 25 medidas do `FI` **hard-coded** e valida o tamanho — vai
  **quebrar** para `FII`/`ACAO`. Tornar o conjunto de medidas dependente do tipo.
- [ ] **Benchmarks via `INDICE`.** Adicionar um catálogo dos índices (tabela
  acima) para puxar séries de CDI/IPCA/etc. reusando `get_retorno_carteira`.
- [ ] **Batelar séries no multiplex `/b`.** Substituir N chamadas (uma por ativo)
  por uma só com várias sub-requisições — aplicar no `scrap`.
- [ ] **Métricas de risco no nosso lado.** Calcular volatilidade, Sharpe, janela
  móvel 20d etc. a partir da série diária (pandas), sem depender da API.

> Relacionado: o TODO "Suporte a ETFs e ativos sem CNPJ" em
> [`progresso.md`](progresso.md) — a busca por texto documentada aqui é o
> caminho para resolvê-lo.
