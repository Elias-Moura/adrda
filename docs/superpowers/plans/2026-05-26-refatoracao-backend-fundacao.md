# Refatoração do back-end — Fase 1 (Fundação) — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reestruturar o back-end do Quantum Scrapper em camadas limpas (client HTTP → parsers Pydantic → schemas → services + ORM → views magras), com um modelo `Ativo` unificado e chave natural `(tipo, id_quantum)`, corrigindo os bugs de `id_quantum` numérico e de validação de medidas por tipo.

**Architecture:** Subpacote `scrapper/quantum/` puro-Python (`catalogo`, `schemas`, `parsers`, `client`) sem dependência de Django; `scrapper/services.py` é a única camada que toca o ORM e converte Pydantic → models; as views ficam magras e delegam aos services (mantendo `threading.Thread` + `Job`). Banco pode ser resetado (migração limpa, sem data migration de dados existentes; só seed dos índices).

**Tech Stack:** Python 3.11+, Django 5.x, Pydantic v2, httpx, trio, pandas, pytest + pytest-django, uv.

**Referências de verdade:**
- `docs/api-quantum.md` — engenharia reversa da API (busca, série, medidas por tipo, benchmarks).
- `docs/superpowers/specs/2026-05-26-refatoracao-backend-fundacao-design.md` — design aprovado.

**Decisões já fechadas:**
- Colunas promovidas: `cnpj`, `ticker`, `setor`, `gestora`, `primeira_cota`, `subtipo`.
- Jobs: mantém `threading.Thread` + `Job` (sem Celery).
- `PORTFOLIO`: **fora** do enum `TipoAtivo` nesta fase.
- Medidas por tipo capturadas (2026-05-26): FI=24, FII=22, ACAO=14 (ver `docs/api-quantum.md`).

**Dados capturados (usados literalmente abaixo):**
- Índices/benchmarks (`id_quantum` → nome): `1`=CDI, `31`=IPCA, `4`=Ibovespa, `51`=IMA-B, `15`=IRF-M, `7`=Dólar, `114`=IDA-DI, `453`=Poupança (Selic), `8`=Poupança.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---------|------------------|
| `scrapper/quantum/__init__.py` | API pública do pacote (reexporta nomes principais) |
| `scrapper/quantum/catalogo.py` | Enums (`TipoAtivo`, `SubtipoAcao`) + catálogo de índices + ordem de medidas por tipo |
| `scrapper/quantum/schemas.py` | Modelos Pydantic v2 (domínio + metadados por tipo) |
| `scrapper/quantum/parsers.py` | Funções puras: dict cru → Pydantic |
| `scrapper/quantum/client.py` | `QuantumClient` — só HTTP/sessão/token; devolve dict cru |
| `scrapper/services.py` | `QuantumService` + `seed_indices` — orquestra client+parsers+ORM |
| `scrapper/models.py` | ORM (Ativo unificado, CotacaoDiaria, Job) — **reescrito** |
| `scrapper/admin.py` | Admin do Ativo unificado — **reescrito** |
| `scrapper/views.py` | Views magras chamando services — **reescrito** |
| `scrapper/migrations/0001_initial.py` | Migração limpa (recriada) |
| `scrapper/migrations/0002_seed_indices.py` | Data migration: seed dos índices |
| `tests/quantum/test_catalogo.py` | Testes do catálogo |
| `tests/quantum/test_schemas.py` | Testes dos schemas Pydantic |
| `tests/quantum/test_parsers.py` | Testes dos parsers (dicts crus reais) |
| `tests/quantum/test_client.py` | Testes do client (httpx mockado) |
| `tests/test_services.py` | Testes dos services (`@pytest.mark.django_db`) |
| `pyproject.toml` | `+ pydantic`, `+ pytest-django`, `DJANGO_SETTINGS_MODULE` |

**Decisão de localização de `MEDIDAS_POR_TIPO`:** fica em `catalogo.py` (não em `parsers.py` como rascunhado no spec) porque **client** (monta o payload) e **parsers** (zipam a resposta) precisam dela — e o client não pode importar parsers (camada de baixo não conhece a de cima). `catalogo.py` é puro-Python sem Django, então ambos importam dele.

---

## Ordem de execução

Bottom-up, respeitando dependências entre camadas:
1. Infra de deps/testes → 2. `catalogo` → 3. `schemas` → 4. `parsers` → 5. `client` → 6. `models` (+migração) → 7. `services` (+seed) → 8. `admin` → 9. `views` → 10. `templates` → 11. limpeza do teste legado + verificação final.

---

### Task 1: Dependências e infraestrutura de testes

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/quantum/__init__.py`

- [ ] **Step 1: Adicionar pydantic e pytest-django**

Em `pyproject.toml`, adicionar `"pydantic>=2.7"` à lista `dependencies` (após `"numpy>=1.26",`) e `"pytest-django>=4.8"` ao grupo `dev`:

```toml
dependencies = [
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "trio>=0.26",
    "loguru>=0.7",
    "pandas>=2.2",
    "openpyxl>=3.1",
    "python-dateutil>=2.9",
    "django>=5.0",
    "quantstats>=0.0.62",
    "plotly>=5.22",
    "numpy>=1.26",
    "pydantic>=2.7",
    "taskipy>=1.14.1",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-django>=4.8",
]
```

- [ ] **Step 2: Configurar pytest-django**

Substituir o bloco `[tool.pytest.ini_options]` em `pyproject.toml` por:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
DJANGO_SETTINGS_MODULE = "core.settings"
python_files = ["test_*.py"]
```

- [ ] **Step 3: Criar o pacote de testes do quantum**

Criar `tests/quantum/__init__.py` vazio.

- [ ] **Step 4: Sincronizar dependências**

Run: `uv sync`
Expected: instala `pydantic` e `pytest-django` sem erros.

- [ ] **Step 5: Verificar que o pytest sobe com Django**

Run: `uv run pytest tests/ -q --collect-only`
Expected: coleta os testes existentes sem erro de configuração do Django (pode listar `tests/test_quantum_scrapper.py`).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/quantum/__init__.py
git commit -m "chore: adicionar pydantic e pytest-django para a refatoração do back-end"
```

---

### Task 2: `catalogo.py` — enums, índices e medidas por tipo

**Files:**
- Create: `scrapper/quantum/__init__.py`
- Create: `scrapper/quantum/catalogo.py`
- Test: `tests/quantum/test_catalogo.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/quantum/test_catalogo.py`:

```python
from scrapper.quantum.catalogo import (
    INDICES,
    MEDIDAS_POR_TIPO,
    SubtipoAcao,
    TipoAtivo,
)


class TestTipoAtivo:
    def test_valores_esperados(self):
        assert {t.value for t in TipoAtivo} == {
            "FI", "FII", "ACAO", "INDICE", "RENDA_FIXA"
        }

    def test_portfolio_nao_esta_no_enum(self):
        assert "PORTFOLIO" not in {t.value for t in TipoAtivo}

    def test_e_comparavel_a_string(self):
        assert TipoAtivo.FI == "FI"


class TestSubtipoAcao:
    def test_valores(self):
        assert {s.value for s in SubtipoAcao} == {"Stocks", "BDR", "ETF"}


class TestIndices:
    def test_cdi_id_1(self):
        assert INDICES["1"] == "CDI"

    def test_ipca_id_31(self):
        assert INDICES["31"] == "IPCA"

    def test_chaves_sao_strings(self):
        assert all(isinstance(k, str) for k in INDICES)

    def test_contem_nove_indices(self):
        assert len(INDICES) == 9


class TestMedidasPorTipo:
    def test_fi_tem_24_medidas(self):
        assert len(MEDIDAS_POR_TIPO[TipoAtivo.FI]) == 24

    def test_fii_tem_22_medidas(self):
        assert len(MEDIDAS_POR_TIPO[TipoAtivo.FII]) == 22

    def test_acao_tem_14_medidas(self):
        assert len(MEDIDAS_POR_TIPO[TipoAtivo.ACAO]) == 14

    def test_fi_comeca_com_nome(self):
        assert MEDIDAS_POR_TIPO[TipoAtivo.FI][0] == "NOME"

    def test_acao_contem_ticker_e_setor(self):
        assert "TICKER" in MEDIDAS_POR_TIPO[TipoAtivo.ACAO]
        assert "SETOR_QUANTUM" in MEDIDAS_POR_TIPO[TipoAtivo.ACAO]
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest tests/quantum/test_catalogo.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.quantum'`.

- [ ] **Step 3: Criar o pacote e o catálogo**

Criar `scrapper/quantum/__init__.py` vazio (será preenchido no fim).

Criar `scrapper/quantum/catalogo.py`:

```python
"""Enums, catálogo de índices e ordem de medidas por tipo do Quantum.

Puro-Python: não importa Django nem ORM. Fonte dos dados: docs/api-quantum.md.
"""
from enum import StrEnum


class TipoAtivo(StrEnum):
    """tipoItemSelecionavel do Quantum (= {tipo} nas URLs /api/ativos/{tipo}/...)."""

    FI = "FI"
    FII = "FII"
    ACAO = "ACAO"
    INDICE = "INDICE"
    RENDA_FIXA = "RENDA_FIXA"


class SubtipoAcao(StrEnum):
    """Subtipo de ACAO, derivado de informacaoAdicional / TIPO_DE_ATIVO."""

    STOCKS = "Stocks"
    BDR = "BDR"
    ETF = "ETF"


# Catálogo de índices/benchmarks (id_quantum -> nome).
# Fonte: /api/benchmarks/porFuncionalidade/COMPARACAO (docs/api-quantum.md).
INDICES: dict[str, str] = {
    "1": "CDI",
    "31": "IPCA",
    "4": "Ibovespa",
    "51": "IMA-B",
    "15": "IRF-M",
    "7": "Dólar",
    "114": "IDA-DI",
    "453": "Poupança (Selic)",
    "8": "Poupança",
}

# Ordem das medidas de /medidas/valor por tipo (capturado 2026-05-26).
# A resposta vem como lista posicional de {"valor": ...} sem o nome da medida;
# zipa-se esta ordem (que nós também enviamos no payload do request).
MEDIDAS_POR_TIPO: dict[TipoAtivo, list[str]] = {
    TipoAtivo.FI: [
        "NOME", "CLASSIFICACAO_LEGAL", "CNPJ", "GESTAO", "CLASSIFICACAO_ANBIMA",
        "BENCHMARK", "ABERTO_PARA_CAPTACAO", "PUBLICO_ALVO",
        "TAXA_ADMINISTRACAO_E_GESTAO", "TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA",
        "TAXA_DE_PERFORMANCE", "TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA",
        "APLICACAO_MINIMA", "CONVERSAO_DA_COTA_PARA_APLICACAO",
        "CONVERSAO_DA_COTA_PARA_RESGATE", "DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS",
        "TAXAS_INFORMACOES_ADICIONAIS_EXTRA", "INICIO_DO_FUNDO",
        "MOVIMENTACAO_MINIMA", "DIVULGACAO", "PORCENTAGEM_RENDA_VARIAVEL_FIE",
        "TAXA_DE_RESGATE_EXTRA", "TRIBUTACAO", "POSSUI_SERIE",
    ],
    TipoAtivo.FII: [
        "NOME", "CLASSIFICACAO_LEGAL", "CNPJ", "ADMINISTRADOR", "GESTAO",
        "PUBLICO_ALVO", "CLASSIFICACAO_ANBIMA", "INVESTIMENTO_TIPO_DE_IMOVEL",
        "INVESTIMENTO_QUANTIDADE_DE_IMOVEIS", "RENTABILIDADE_ALVO", "SITUACAO_ATUAL",
        "TAXA_ADMINISTRACAO_E_GESTAO", "TAXA_DE_PERFORMANCE",
        "TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA",
        "INVESTIMENTO_LOCALIZACAO_DO_IMOVEL_EXTRA", "TAXAS_INFORMACOES_ADICIONAIS_EXTRA",
        "INICIO_DO_FUNDO", "APLICACAO_MINIMA", "MOVIMENTACAO_MINIMA", "DIVULGACAO",
        "TRIBUTACAO", "POSSUI_SERIE",
    ],
    TipoAtivo.ACAO: [
        "NOME", "TIPO_DE_ATIVO", "TICKER", "CLASSE", "BOLSA", "SETOR_QUANTUM",
        "CONTROLE_ACIONARIO", "GOVERNANCA_CORPORATIVA", "INICIO_DO_FUNDO",
        "TAXA_DE_ADMINISTRACAO", "APLICACAO_MINIMA", "MOVIMENTACAO_MINIMA",
        "TRIBUTACAO", "POSSUI_SERIE",
    ],
}
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `uv run pytest tests/quantum/test_catalogo.py -q`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add scrapper/quantum/__init__.py scrapper/quantum/catalogo.py tests/quantum/test_catalogo.py
git commit -m "feat(quantum): catálogo de tipos, índices e medidas por tipo"
```

---

### Task 3: `schemas.py` — modelos Pydantic

**Files:**
- Create: `scrapper/quantum/schemas.py`
- Test: `tests/quantum/test_schemas.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/quantum/test_schemas.py`:

```python
from datetime import date

import pytest

from scrapper.quantum.catalogo import TipoAtivo
from scrapper.quantum.schemas import (
    AtivoQuantum,
    MetaACAO,
    MetaFI,
    PontoSerie,
    ResultadoBusca,
    SerieDiaria,
)


class TestResultadoBusca:
    def test_id_quantum_string_renda_fixa(self):
        r = ResultadoBusca(label="VALE38", tipo=TipoAtivo.RENDA_FIXA, id_quantum="VALE38")
        assert r.id_quantum == "VALE38"

    def test_id_quantum_numerico_coagido_para_string(self):
        r = ResultadoBusca(label="X", tipo=TipoAtivo.FI, id_quantum=612014)
        assert r.id_quantum == "612014"

    def test_campos_opcionais_default_none(self):
        r = ResultadoBusca(label="X", tipo=TipoAtivo.FI, id_quantum="1")
        assert r.cnpj is None and r.subtipo is None
        assert r.codigo_grupo == 0


class TestMetadadosTolerantes:
    def test_meta_fi_aceita_campo_faltante(self):
        meta = MetaFI(NOME="Fundo X")
        assert meta.NOME == "Fundo X"
        assert meta.CNPJ is None

    def test_meta_fi_ignora_campo_extra(self):
        meta = MetaFI(NOME="X", CAMPO_NOVO_DO_QUANTUM="valor")
        assert not hasattr(meta, "CAMPO_NOVO_DO_QUANTUM")

    def test_meta_acao_tem_ticker_e_setor(self):
        meta = MetaACAO(TICKER="VALE3", SETOR_QUANTUM="Mineração")
        assert meta.TICKER == "VALE3"
        assert meta.SETOR_QUANTUM == "Mineração"


class TestSerieDiaria:
    def test_ponto_serie(self):
        p = PontoSerie(data=date(2025, 5, 26), valor=100.0)
        assert p.valor == 100.0

    def test_serie_vazia_default(self):
        assert SerieDiaria().pontos == []


class TestAtivoQuantum:
    def test_dominio_minimo(self):
        aq = AtivoQuantum(
            tipo=TipoAtivo.FI, id_quantum="612014", nome="Fundo X",
            metadados=MetaFI(NOME="Fundo X"),
        )
        assert aq.id_quantum == "612014"
        assert aq.primeira_cota is None
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest tests/quantum/test_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.quantum.schemas'`.

- [ ] **Step 3: Escrever os schemas**

Criar `scrapper/quantum/schemas.py`:

```python
"""Modelos Pydantic v2 do domínio Quantum (puro-Python, sem Django).

Metadados tolerantes: todos os campos são Optional e `extra="ignore"`,
para não quebrar se o Quantum mudar/adicionar medidas.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from .catalogo import TipoAtivo


class ResultadoBusca(BaseModel):
    """Candidato achatado da busca global por texto/CNPJ."""

    label: str
    tipo: TipoAtivo
    id_quantum: str  # str! cobre RENDA_FIXA ("VALE38") e corrige o bug do int()
    subtipo: str | None = None
    cnpj: str | None = None
    codigo_grupo: int = 0


class PontoSerie(BaseModel):
    data: date
    valor: float


class SerieDiaria(BaseModel):
    pontos: list[PontoSerie] = []


class MetaBase(BaseModel):
    """Base tolerante para os metadados por tipo."""

    model_config = ConfigDict(extra="ignore")


class MetaFI(MetaBase):
    NOME: str | None = None
    CLASSIFICACAO_LEGAL: str | None = None
    CNPJ: str | None = None
    GESTAO: str | None = None
    CLASSIFICACAO_ANBIMA: str | None = None
    BENCHMARK: str | None = None
    ABERTO_PARA_CAPTACAO: str | None = None
    PUBLICO_ALVO: str | None = None
    TAXA_ADMINISTRACAO_E_GESTAO: str | None = None
    TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA: str | None = None
    TAXA_DE_PERFORMANCE: str | None = None
    TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA: str | None = None
    APLICACAO_MINIMA: str | None = None
    CONVERSAO_DA_COTA_PARA_APLICACAO: str | None = None
    CONVERSAO_DA_COTA_PARA_RESGATE: str | None = None
    DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS: str | None = None
    TAXAS_INFORMACOES_ADICIONAIS_EXTRA: str | None = None
    INICIO_DO_FUNDO: str | None = None
    MOVIMENTACAO_MINIMA: str | None = None
    DIVULGACAO: str | None = None
    PORCENTAGEM_RENDA_VARIAVEL_FIE: str | None = None
    TAXA_DE_RESGATE_EXTRA: str | None = None
    TRIBUTACAO: str | None = None
    POSSUI_SERIE: str | None = None


class MetaFII(MetaBase):
    NOME: str | None = None
    CLASSIFICACAO_LEGAL: str | None = None
    CNPJ: str | None = None
    ADMINISTRADOR: str | None = None
    GESTAO: str | None = None
    PUBLICO_ALVO: str | None = None
    CLASSIFICACAO_ANBIMA: str | None = None
    INVESTIMENTO_TIPO_DE_IMOVEL: str | None = None
    INVESTIMENTO_QUANTIDADE_DE_IMOVEIS: str | None = None
    RENTABILIDADE_ALVO: str | None = None
    SITUACAO_ATUAL: str | None = None
    TAXA_ADMINISTRACAO_E_GESTAO: str | None = None
    TAXA_DE_PERFORMANCE: str | None = None
    TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA: str | None = None
    INVESTIMENTO_LOCALIZACAO_DO_IMOVEL_EXTRA: str | None = None
    TAXAS_INFORMACOES_ADICIONAIS_EXTRA: str | None = None
    INICIO_DO_FUNDO: str | None = None
    APLICACAO_MINIMA: str | None = None
    MOVIMENTACAO_MINIMA: str | None = None
    DIVULGACAO: str | None = None
    TRIBUTACAO: str | None = None
    POSSUI_SERIE: str | None = None


class MetaACAO(MetaBase):
    NOME: str | None = None
    TIPO_DE_ATIVO: str | None = None
    TICKER: str | None = None
    CLASSE: str | None = None
    BOLSA: str | None = None
    SETOR_QUANTUM: str | None = None
    CONTROLE_ACIONARIO: str | None = None
    GOVERNANCA_CORPORATIVA: str | None = None
    INICIO_DO_FUNDO: str | None = None
    TAXA_DE_ADMINISTRACAO: str | None = None
    APLICACAO_MINIMA: str | None = None
    MOVIMENTACAO_MINIMA: str | None = None
    TRIBUTACAO: str | None = None
    POSSUI_SERIE: str | None = None


class MetaIndice(MetaBase):
    """INDICE não tem card de medidas/valor (semeado por catálogo)."""

    NOME: str | None = None


class MetaRendaFixa(MetaBase):
    """RENDA_FIXA: sem captura de medidas; tolerante."""

    NOME: str | None = None


class AtivoQuantum(BaseModel):
    """Objeto de domínio que os services persistem no ORM."""

    tipo: TipoAtivo
    id_quantum: str
    nome: str
    subtipo: str | None = None
    cnpj: str | None = None
    ticker: str | None = None
    setor: str | None = None
    gestora: str | None = None
    primeira_cota: date | None = None
    metadados: MetaFI | MetaFII | MetaACAO | MetaIndice | MetaRendaFixa
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `uv run pytest tests/quantum/test_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapper/quantum/schemas.py tests/quantum/test_schemas.py
git commit -m "feat(quantum): schemas Pydantic do domínio e metadados por tipo"
```

---

### Task 4: `parsers.py` — funções puras cru→Pydantic

**Files:**
- Create: `scrapper/quantum/parsers.py`
- Test: `tests/quantum/test_parsers.py`

Substitui `_parsear_resultados_busca`, `_simplificar_retorno_multiplex` (incluindo a validação de tamanho que quebrava) e `_extrair_serie`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/quantum/test_parsers.py`:

```python
import json
from datetime import date

from scrapper.quantum.catalogo import TipoAtivo
from scrapper.quantum.parsers import (
    montar_ativo,
    parse_metadados,
    parse_resultados_busca,
    parse_serie,
)
from scrapper.quantum.schemas import MetaACAO, MetaFI, ResultadoBusca


def _multiplex(valores: list) -> dict:
    """Resposta multiplex de /medidas/valor: lista posicional de {'valor': ...}."""
    body = json.dumps([{"valor": v} for v in valores])
    return {"responseList": [{"body": body}]}


def _multiplex_serie(pontos: list[tuple[str, str]]) -> dict:
    serie = [{"data": d, "valor": v} for d, v in pontos]
    return {"responseList": [{"body": json.dumps({"serie": serie})}]}


# Captura real: VALE3 devolve ACAO (id 700) + RENDA_FIXA (id "VALE38")
_GRUPOS_VALE3 = [
    {
        "codigoGrupo": 0,
        "primeirosResultados": [{
            "itemSelecionavel": {
                "label": "VALE ON N1 - VALE3",
                "identificador": 700,
                "tipoItemSelecionavel": "ACAO",
            },
            "informacaoAdicional": "Type: Stocks | Stock Exchange: BMFBovespa",
            "codigoGrupo": 0,
        }],
    },
    {
        "codigoGrupo": 1,
        "primeirosResultados": [{
            "itemSelecionavel": {
                "label": "VALE38",
                "identificador": "VALE38",
                "tipoItemSelecionavel": "RENDA_FIXA",
            },
            "informacaoAdicional": "Type: Debênture",
            "codigoGrupo": 1,
        }],
    },
]

_GRUPOS_FI = [{
    "codigoGrupo": 0,
    "primeirosResultados": [{
        "itemSelecionavel": {
            "label": "AMW CASH CLASH FI RENDA FIXA LP",
            "identificador": "612014",
            "tipoItemSelecionavel": "FI",
        },
        "informacaoAdicional": "CNPJ: 42.550.188/0001-91 | Management Company: Amw",
        "codigoGrupo": 0,
    }],
}]


class TestParseResultadosBusca:
    def test_renda_fixa_id_string_nao_quebra(self):
        # Regressão: int("VALE38") quebrava antes.
        resultados = parse_resultados_busca(_GRUPOS_VALE3)
        rf = [r for r in resultados if r.tipo == TipoAtivo.RENDA_FIXA][0]
        assert rf.id_quantum == "VALE38"

    def test_achata_todos_os_grupos(self):
        assert len(parse_resultados_busca(_GRUPOS_VALE3)) == 2

    def test_extrai_cnpj_de_informacao_adicional(self):
        r = parse_resultados_busca(_GRUPOS_FI)[0]
        assert r.cnpj == "42.550.188/0001-91"

    def test_extrai_subtipo_de_acao(self):
        acao = [r for r in parse_resultados_busca(_GRUPOS_VALE3)
                if r.tipo == TipoAtivo.ACAO][0]
        assert acao.subtipo == "Stocks"


class TestParseMetadados:
    _FI_24 = [
        "AMW CASH", "FI Renda Fixa", "42.550.188/0001-91", "Amw Asset", "Renda Fixa",
        "IRF-M", "Sim", "Investidores", "0.17", "2.0", "10.0", "100% do CDI",
        "100.00", "D+0", "D+0", "D+0", "Tx: 0%", "2021-09-10", "0.00", "D",
        "Não informado", "Não possui", "FI_LONGO_PRAZO", "true",
    ]
    _ACAO_14 = [
        "VALE ON N1", "AÇÃO", "VALE3", "ON", "BMFBovespa", "Mineração",
        "Privado", "Novo Mercado", "2000-01-01", "0", "0", "0", "trib", "true",
    ]

    def test_fi_24_valores_nao_quebra(self):
        meta = parse_metadados(TipoAtivo.FI, _multiplex(self._FI_24))
        assert meta.CNPJ == "42.550.188/0001-91"
        assert meta.INICIO_DO_FUNDO == "2021-09-10"

    def test_acao_14_valores_nao_quebra(self):
        # Regressão: validação de 24 medidas quebrava para ACAO.
        meta = parse_metadados(TipoAtivo.ACAO, _multiplex(self._ACAO_14))
        assert meta.TICKER == "VALE3"
        assert meta.SETOR_QUANTUM == "Mineração"

    def test_tolera_menos_valores_que_a_ordem(self):
        meta = parse_metadados(TipoAtivo.FI, _multiplex(["AMW CASH"]))
        assert meta.NOME == "AMW CASH"
        assert meta.CNPJ is None


class TestParseSerie:
    def test_parseia_pontos(self):
        serie = parse_serie(_multiplex_serie([
            ("2025-05-26", "100.0"), ("2025-05-27", "100.05"),
        ]))
        assert len(serie.pontos) == 2
        assert serie.pontos[0].data == date(2025, 5, 26)
        assert serie.pontos[1].valor == 100.05

    def test_serie_ausente_retorna_vazio(self):
        assert parse_serie({"responseList": [{"body": '{"outro": []}'}]}).pontos == []


class TestMontarAtivo:
    def test_fi_promove_cnpj_gestora_primeira_cota(self):
        resultado = ResultadoBusca(
            label="AMW", tipo=TipoAtivo.FI, id_quantum="612014",
            cnpj="42.550.188/0001-91",
        )
        meta = MetaFI(NOME="AMW", CNPJ="42.550.188/0001-91", GESTAO="Amw Asset",
                      INICIO_DO_FUNDO="2021-09-10")
        aq = montar_ativo(resultado, meta)
        assert aq.cnpj == "42.550.188/0001-91"
        assert aq.gestora == "Amw Asset"
        assert aq.primeira_cota == date(2021, 9, 10)

    def test_acao_promove_ticker_setor_subtipo(self):
        resultado = ResultadoBusca(label="VALE3", tipo=TipoAtivo.ACAO,
                                   id_quantum="700", subtipo="Stocks")
        meta = MetaACAO(TICKER="VALE3", SETOR_QUANTUM="Mineração", TIPO_DE_ATIVO="AÇÃO")
        aq = montar_ativo(resultado, meta)
        assert aq.ticker == "VALE3"
        assert aq.setor == "Mineração"
        assert aq.subtipo == "Stocks"

    def test_primeira_cota_invalida_vira_none(self):
        resultado = ResultadoBusca(label="X", tipo=TipoAtivo.FI, id_quantum="1")
        meta = MetaFI(NOME="X", INICIO_DO_FUNDO="Não informado")
        assert montar_ativo(resultado, meta).primeira_cota is None
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest tests/quantum/test_parsers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.quantum.parsers'`.

- [ ] **Step 3: Escrever os parsers**

Criar `scrapper/quantum/parsers.py`:

```python
"""Funções puras: dict cru da API → schemas Pydantic. Sem rede, sem Django."""
from __future__ import annotations

import json
import re
from datetime import date

from .catalogo import MEDIDAS_POR_TIPO, TipoAtivo
from .schemas import (
    AtivoQuantum,
    MetaACAO,
    MetaBase,
    MetaFI,
    MetaFII,
    MetaIndice,
    MetaRendaFixa,
    PontoSerie,
    ResultadoBusca,
    SerieDiaria,
)

_CNPJ_RE = re.compile(r"CNPJ:\s*([\d./-]+)")
_TIPO_RE = re.compile(r"Type:\s*([^|]+)")

_META_CLASS: dict[TipoAtivo, type[MetaBase]] = {
    TipoAtivo.FI: MetaFI,
    TipoAtivo.FII: MetaFII,
    TipoAtivo.ACAO: MetaACAO,
    TipoAtivo.INDICE: MetaIndice,
    TipoAtivo.RENDA_FIXA: MetaRendaFixa,
}


def parse_resultados_busca(grupos: list[dict]) -> list[ResultadoBusca]:
    """Achata o JSON agrupado da busca global numa lista de ResultadoBusca.

    id_quantum sempre como string (cobre RENDA_FIXA). CNPJ e subtipo são
    extraídos de informacaoAdicional quando presentes.
    """
    resultados: list[ResultadoBusca] = []
    for grupo in grupos:
        for entrada in grupo.get("primeirosResultados", []):
            item = entrada.get("itemSelecionavel", {})
            info = entrada.get("informacaoAdicional", "") or ""
            cnpj_match = _CNPJ_RE.search(info)
            tipo_match = _TIPO_RE.search(info)
            resultados.append(ResultadoBusca(
                label=item.get("label", ""),
                tipo=item.get("tipoItemSelecionavel", ""),
                id_quantum=str(item.get("identificador", "")),
                subtipo=tipo_match.group(1).strip() if tipo_match else None,
                cnpj=cnpj_match.group(1) if cnpj_match else None,
                codigo_grupo=grupo.get("codigoGrupo", 0),
            ))
    return resultados


def _body_multiplex(raw_multiplex: dict) -> str | None:
    try:
        return raw_multiplex["responseList"][0]["body"]
    except (KeyError, IndexError, TypeError):
        return None


def parse_metadados(tipo: TipoAtivo, raw_multiplex: dict) -> MetaBase:
    """Zipa a ordem de medidas do tipo com os valores posicionais da resposta.

    Tolerante: zip trunca no menor dos dois; campos faltantes ficam None;
    medidas extras são ignoradas pelo schema (extra='ignore').
    """
    meta_cls = _META_CLASS[TipoAtivo(tipo)]
    ordem = MEDIDAS_POR_TIPO.get(TipoAtivo(tipo), [])
    body = _body_multiplex(raw_multiplex)
    if not body or not ordem:
        return meta_cls()
    try:
        valores = json.loads(body)
    except json.JSONDecodeError:
        return meta_cls()
    dados = {
        nome: item.get("valor")
        for nome, item in zip(ordem, valores)
        if isinstance(item, dict)
    }
    return meta_cls(**dados)


def parse_serie(raw_multiplex: dict) -> SerieDiaria:
    """responseList[0].body -> {'serie': [{data, valor}]} -> SerieDiaria."""
    body = _body_multiplex(raw_multiplex)
    if not body:
        return SerieDiaria()
    try:
        pontos_raw = json.loads(body).get("serie", [])
    except (json.JSONDecodeError, AttributeError):
        return SerieDiaria()
    pontos = [
        PontoSerie(data=date.fromisoformat(p["data"]), valor=float(p["valor"]))
        for p in pontos_raw
    ]
    return SerieDiaria(pontos=pontos)


def _data_ou_none(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def montar_ativo(resultado: ResultadoBusca, meta: MetaBase) -> AtivoQuantum:
    """Combina o resultado da busca + metadados validados num AtivoQuantum,
    derivando as colunas promovidas a partir dos campos disponíveis."""
    ticker = getattr(meta, "TICKER", None)
    setor = getattr(meta, "SETOR_QUANTUM", None)
    cnpj = getattr(meta, "CNPJ", None) or resultado.cnpj
    gestora = getattr(meta, "GESTAO", None)
    subtipo = resultado.subtipo or getattr(meta, "TIPO_DE_ATIVO", None)
    primeira_cota = _data_ou_none(getattr(meta, "INICIO_DO_FUNDO", None))
    nome = getattr(meta, "NOME", None) or resultado.label
    return AtivoQuantum(
        tipo=resultado.tipo,
        id_quantum=resultado.id_quantum,
        nome=nome,
        subtipo=subtipo,
        cnpj=cnpj,
        ticker=ticker,
        setor=setor,
        gestora=gestora,
        primeira_cota=primeira_cota,
        metadados=meta,
    )
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `uv run pytest tests/quantum/test_parsers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapper/quantum/parsers.py tests/quantum/test_parsers.py
git commit -m "feat(quantum): parsers puros (busca, série, metadados) com regressões cobertas"
```

---

### Task 5: `client.py` — transporte HTTP puro

**Files:**
- Create: `scrapper/quantum/client.py`
- Test: `tests/quantum/test_client.py`

`QuantumClient` herda a lógica de login/token/headers do atual `QuantumScrapper`, mas **só devolve dict cru** (sem parsing). Sem Django/ORM.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/quantum/test_client.py`:

```python
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapper.quantum.catalogo import TipoAtivo
from scrapper.quantum.client import QuantumClient


def _make_client(token: str = "Bearer fake") -> QuantumClient:
    c = object.__new__(QuantumClient)
    c.token = token
    c._client = MagicMock()
    return c


class TestBuscar:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.get.return_value.status_code = 200
        self.c._client.get.return_value.json.return_value = [{"codigoGrupo": 0}]

    def test_busca_por_texto_usa_iscnpj_false(self):
        self.c.buscar("HASH11", is_cnpj=False)
        url = self.c._client.get.call_args[0][0]
        assert "isCNPJ=false" in url

    def test_busca_por_cnpj_usa_iscnpj_true(self):
        self.c.buscar("42.550.188/0001-91", is_cnpj=True)
        url = self.c._client.get.call_args[0][0]
        assert "isCNPJ=true" in url

    def test_devolve_dict_cru(self):
        assert self.c.buscar("X") == [{"codigoGrupo": 0}]

    def test_erro_http_levanta_value_error(self):
        self.c._client.get.return_value.status_code = 500
        self.c._client.get.return_value.text = "erro"
        with pytest.raises(ValueError, match="500"):
            self.c.buscar("X")


class TestDadosComplementares:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.post.return_value.status_code = 200
        self.c._client.post.return_value.json.return_value = {"responseList": [{"body": "[]"}]}

    def test_envia_ordem_de_medidas_do_tipo_acao(self):
        self.c.dados_complementares(TipoAtivo.ACAO, "700")
        payload = self.c._client.post.call_args[1]["content"]
        assert "TICKER" in payload
        assert "SETOR_QUANTUM" in payload

    def test_relative_url_contem_tipo_e_id(self):
        self.c.dados_complementares(TipoAtivo.FI, "612014")
        payload = self.c._client.post.call_args[1]["content"]
        assert "/api/ativos/FI/612014/medidas/valor" in payload

    def test_token_no_header(self):
        self.c.dados_complementares(TipoAtivo.FI, "1")
        headers = self.c._client.post.call_args[1]["headers"]
        assert headers["authorization"] == self.c.token

    def test_devolve_dict_cru(self):
        assert self.c.dados_complementares(TipoAtivo.FI, "1") == {"responseList": [{"body": "[]"}]}


class TestSerie:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.post.return_value.status_code = 200
        self.c._client.post.return_value.json.return_value = {"responseList": [{"body": '{"serie":[]}'}]}

    def test_payload_contem_datas_e_medida(self):
        self.c.serie(TipoAtivo.FI, "1", date(2024, 1, 1), date(2024, 12, 31))
        payload = self.c._client.post.call_args[1]["content"]
        assert "2024-01-01" in payload
        assert "2024-12-31" in payload
        assert "EVOLUCAO_DO_ATIVO" in payload

    def test_relative_url_serie(self):
        self.c.serie(TipoAtivo.FI, "612014", date(2024, 1, 1), date(2024, 12, 31))
        payload = self.c._client.post.call_args[1]["content"]
        assert "/api/ativos/FI/612014/medidas/serie" in payload

    def test_devolve_dict_cru(self):
        out = self.c.serie(TipoAtivo.FI, "1", date(2024, 1, 1), date(2024, 12, 31))
        assert out == {"responseList": [{"body": '{"serie":[]}'}]}
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest tests/quantum/test_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.quantum.client'`.

- [ ] **Step 3: Escrever o client**

Criar `scrapper/quantum/client.py`:

```python
"""QuantumClient — transporte HTTP puro (sessão, token, requests crus).

Não importa Django nem ORM, não faz parsing: devolve dict cru.
Login/token/headers portados de quantum_scrapper.QuantumScrapper.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

from .catalogo import MEDIDAS_POR_TIPO, TipoAtivo

load_dotenv()


class QuantumClient:
    _BASE_URL = "https://www.comparadordeativos.com.br"
    _LOGIN_URL = f"{_BASE_URL}/webaxis/webaxis2/notAuthorised/login/logar/realizaLogin"
    _TOKEN_REFRESH_URL = f"{_BASE_URL}/webaxis/webaxis2/token/refresh"
    _API_URL = f"{_BASE_URL}/b"
    _BUSCA_URL = f"{_BASE_URL}/webaxis/webaxis2/buscaGlobal/ajax/buscar"

    def __init__(self) -> None:
        self._client = httpx.Client(follow_redirects=True)
        self.token: str = ""

    # ── Autenticação ────────────────────────────────────────────────────────
    def login(self, username: str | None = None, password: str | None = None) -> None:
        username = username or os.getenv("QUANTUM_USERNAME")
        password = password or os.getenv("QUANTUM_PASSWORD")
        if not username or not password:
            raise ValueError(
                "Credenciais não encontradas. "
                "Configure QUANTUM_USERNAME e QUANTUM_PASSWORD no arquivo .env"
            )
        headers = {
            "accept": "*/*",
            "content-type": "application/json; charset=UTF-8",
            "origin": self._BASE_URL,
            "referer": f"{self._BASE_URL}/webaxis/login.jsp",
            "x-requested-with": "XMLHttpRequest",
        }
        payload = {
            "username": username,
            "senha": password,
            "autenticador": None,
            "isNavegadorChrome": True,
            "paginaRedirecionar": None,
        }
        response = self._client.post(self._LOGIN_URL, headers=headers, json=payload)
        if response.status_code not in (200, 302):
            raise ValueError(f"Falha no login: {response.status_code} {response.text}")
        self.token = self._fetch_bearer_token()
        logger.info("Login realizado com sucesso. Token obtido.")

    def _fetch_bearer_token(self) -> str:
        url = f"{self._TOKEN_REFRESH_URL}?_={int(time.time() * 1000)}"
        headers = {"accept": "*/*", "x-requested-with": "XMLHttpRequest"}
        response = self._client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"Falha ao obter token: {response.status_code} {response.text}")
        return self._extract_bearer(response)

    @staticmethod
    def _extract_bearer(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                for key in ("token", "access_token", "apitoken", "jwt"):
                    if raw := data.get(key):
                        return raw if raw.startswith("Bearer ") else f"Bearer {raw}"
            if isinstance(data, str) and len(data) > 20:
                return data if data.startswith("Bearer ") else f"Bearer {data}"
        except Exception:
            pass
        raw = response.text.strip()
        if raw and len(raw) > 20:
            return raw if raw.startswith("Bearer ") else f"Bearer {raw}"
        raise ValueError(
            "Bearer token não encontrado na resposta de /token/refresh. "
            f"Status: {response.status_code} | Body: {response.text[:200]}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (UnicodeDecodeError, ValueError):
            return json.loads(response.content.decode("latin-1"))

    def _headers_api(self) -> dict:
        return {
            "accept": "*/*",
            "accept-language": "pt-BR,pt;q=0.9,en;q=0.8",
            "authorization": self.token,
            "content-type": "application/json",
            "origin": self._BASE_URL,
            "referer": f"{self._BASE_URL}/static/comparacao/",
        }

    # ── Endpoints (devolvem dict cru) ──────────────────────────────────────────
    def buscar(self, termo: str, is_cnpj: bool = False, max_por_grupo: int = 5) -> list[dict]:
        """Busca global por texto (is_cnpj=False) ou por CNPJ (is_cnpj=True)."""
        if is_cnpj:
            url = (
                f"{self._BUSCA_URL}?filtroBusca=defaultSearch"
                f"&searchString={urllib.parse.quote(termo)}&isCNPJ=true"
            )
        else:
            url = (
                f"{self._BUSCA_URL}?filtroBusca=defaultSearch"
                f"&searchString={urllib.parse.quote(termo)}"
                f"&cancelaBusca=false&isCNPJ=false&isCodigoSUSEP=false"
                f"&codigoGrupoExpandido=&quantidadeMaximaPorGrupo={max_por_grupo}"
                f"&_={int(time.time() * 1000)}"
            )
        headers = {
            **self._headers_api(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"{self._BASE_URL}/webaxis/",
        }
        response = self._client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._decode_json(response)

    def _relative_url(self, tipo: TipoAtivo, id_quantum: str, sufixo: str) -> str:
        return f"/api/ativos/{TipoAtivo(tipo).value}/{id_quantum}/medidas/{sufixo}"

    def dados_complementares(self, tipo: TipoAtivo, id_quantum: str) -> dict:
        """Multiplex /medidas/valor. Devolve o dict cru (responseList)."""
        ordem = MEDIDAS_POR_TIPO.get(TipoAtivo(tipo), [])
        body_medidas = json.dumps([{"medida": m} for m in ordem])
        payload = json.dumps({
            "commonHeader": {
                "Content-Type": "application/json",
                "Accept-Language": "pt-BR",
                "x-Moeda": "BRL",
                "x-Retorno": "Fechamento",
            },
            "requests": [{
                "method": "POST",
                "headers": {},
                "body": body_medidas,
                "relativeUrl": self._relative_url(tipo, id_quantum, "valor"),
            }],
        })
        response = self._client.post(self._API_URL, headers=self._headers_api(), content=payload)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._decode_json(response)

    def serie(
        self, tipo: TipoAtivo, id_quantum: str, data_inicio: date, data_fim: date,
        valor_base: int = 100,
    ) -> dict:
        """Multiplex /medidas/serie (EVOLUCAO_DO_ATIVO). Devolve o dict cru."""
        body = json.dumps({
            "medida": "EVOLUCAO_DO_ATIVO",
            "dataInicial": data_inicio.strftime("%Y-%m-%d"),
            "dataFinal": data_fim.strftime("%Y-%m-%d"),
            "propriedades": {"valorBase": valor_base, "periodicidade": "DIARIA"},
        })
        payload = json.dumps({
            "commonHeader": {
                "Content-Type": "application/json",
                "Accept-Language": "pt-BR",
                "x-Moeda": "BRL",
                "x-Retorno": "Fechamento",
            },
            "requests": [{
                "method": "POST",
                "headers": {},
                "body": body,
                "relativeUrl": self._relative_url(tipo, id_quantum, "serie"),
            }],
        })
        response = self._client.post(self._API_URL, headers=self._headers_api(), content=payload)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._decode_json(response)
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `uv run pytest tests/quantum/test_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapper/quantum/client.py tests/quantum/test_client.py
git commit -m "feat(quantum): QuantumClient HTTP puro (busca, medidas, série)"
```

---

### Task 6: `models.py` — Ativo unificado + migração limpa

**Files:**
- Modify: `scrapper/models.py` (reescrita completa)
- Delete: `scrapper/migrations/0001_initial.py`, `0002_cotacaodiaria.py`, `0003_alter_cotacaodiaria_options.py`
- Create: `scrapper/migrations/0001_initial.py` (gerada)

> ⚠️ Banco resetado nesta fase (decisão do spec). Sem data migration de dados antigos.

- [ ] **Step 1: Reescrever `scrapper/models.py`**

Substituir todo o conteúdo de `scrapper/models.py` por:

```python
from django.db import models

from scrapper.quantum.catalogo import TipoAtivo


class Ativo(models.Model):
    """Ativo unificado do Quantum. Chave natural: (tipo, id_quantum)."""

    TIPO_CHOICES = [(t.value, t.value) for t in TipoAtivo]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    id_quantum = models.CharField(max_length=100)  # string (cobre RENDA_FIXA)
    subtipo = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=200)
    # Colunas promovidas (consultáveis/indexadas)
    cnpj = models.CharField(max_length=20, blank=True, default="", db_index=True)
    ticker = models.CharField(max_length=20, blank=True, default="", db_index=True)
    setor = models.CharField(max_length=120, blank=True, default="")
    gestora = models.CharField(max_length=200, blank=True, default="")
    primeira_cota = models.DateField(null=True, blank=True)
    # Resto dos metadados (já validado por pydantic; meta.model_dump())
    metadados = models.JSONField(default=dict)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Ativo"
        verbose_name_plural = "Ativos"
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "id_quantum"], name="ativo_natural_key"
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.tipo})"

    @property
    def is_indice(self) -> bool:
        return self.tipo == TipoAtivo.INDICE


class CotacaoDiaria(models.Model):
    """Série de valor base-100 por ativo e data."""

    ativo = models.ForeignKey(
        Ativo, on_delete=models.CASCADE, related_name="cotacoes"
    )
    data = models.DateField(db_index=True)
    valor = models.FloatField()

    class Meta:
        ordering = ["data"]
        unique_together = [("ativo", "data")]
        verbose_name = "Cotação Diária"
        verbose_name_plural = "Cotações Diárias"

    def __str__(self):
        return f"{self.ativo.nome} {self.data}: {self.valor:.4f}"


class Job(models.Model):
    TIPO_CHOICES = [
        ("buscar_ativos", "Buscar Ativos"),
        ("scrap", "Scrap Cotas"),
    ]
    STATUS_CHOICES = [
        ("running", "Em execução"),
        ("done", "Concluído"),
        ("error", "Erro"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="running")
    detalhe = models.TextField(blank=True)
    erro = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Job"
        verbose_name_plural = "Jobs"

    def __str__(self):
        return f"Job #{self.id} ({self.get_tipo_display()}) — {self.get_status_display()}"
```

- [ ] **Step 2: Apagar as migrations antigas e o banco**

```bash
rm scrapper/migrations/0001_initial.py scrapper/migrations/0002_cotacaodiaria.py scrapper/migrations/0003_alter_cotacaodiaria_options.py
rm -f db.sqlite3
```

- [ ] **Step 3: Gerar a migração inicial limpa**

Run: `uv run python manage.py makemigrations scrapper`
Expected: cria `scrapper/migrations/0001_initial.py` com `Ativo`, `CotacaoDiaria`, `Job` e a constraint `ativo_natural_key`.

- [ ] **Step 4: Aplicar as migrações**

Run: `uv run python manage.py migrate`
Expected: aplica sem erros (banco novo).

- [ ] **Step 5: Commit**

```bash
git add scrapper/models.py scrapper/migrations/
git commit -m "feat(models): Ativo unificado com chave natural (tipo, id_quantum)"
```

---

### Task 7: `services.py` — orquestração + seed dos índices

**Files:**
- Create: `scrapper/services.py`
- Create: `scrapper/migrations/0002_seed_indices.py`
- Test: `tests/test_services.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_services.py`:

```python
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapper.models import Ativo, CotacaoDiaria
from scrapper.quantum.catalogo import TipoAtivo
from scrapper.services import QuantumService, seed_indices


def _multiplex_valor(valores: list) -> dict:
    body = json.dumps([{"valor": v} for v in valores])
    return {"responseList": [{"body": body}]}


def _multiplex_serie(pontos: list[tuple[str, str]]) -> dict:
    serie = [{"data": d, "valor": v} for d, v in pontos]
    return {"responseList": [{"body": json.dumps({"serie": serie})}]}


_GRUPOS_FI = [{
    "codigoGrupo": 0,
    "primeirosResultados": [{
        "itemSelecionavel": {
            "label": "AMW CASH CLASH FI RENDA FIXA LP",
            "identificador": "612014",
            "tipoItemSelecionavel": "FI",
        },
        "informacaoAdicional": "CNPJ: 42.550.188/0001-91 | Management Company: Amw",
        "codigoGrupo": 0,
    }],
}]

_FI_24 = [
    "AMW CASH", "FI", "42.550.188/0001-91", "Amw Asset", "Renda Fixa", "IRF-M",
    "Sim", "Investidores", "0.17", "2.0", "10.0", "100% do CDI", "100.00",
    "D+0", "D+0", "D+0", "Tx: 0%", "2021-09-10", "0.00", "D",
    "Não informado", "Não possui", "FI_LONGO_PRAZO", "true",
]


@pytest.mark.django_db
class TestImportarAtivos:
    def _service(self) -> QuantumService:
        client = MagicMock()
        client.buscar.return_value = _GRUPOS_FI
        client.dados_complementares.return_value = _multiplex_valor(_FI_24)
        svc = QuantumService(client=client)
        svc._logged_in = True
        return svc

    def test_cria_ativo_unico(self):
        svc = self._service()
        resultados = svc.buscar_por_cnpj("42.550.188/0001-91")
        ativos = svc.importar_ativos(resultados)
        assert len(ativos) == 1
        assert Ativo.objects.count() == 1

    def test_promove_colunas(self):
        svc = self._service()
        resultados = svc.buscar_por_cnpj("42.550.188/0001-91")
        ativo = svc.importar_ativos(resultados)[0]
        assert ativo.cnpj == "42.550.188/0001-91"
        assert ativo.gestora == "Amw Asset"
        assert ativo.primeira_cota == date(2021, 9, 10)
        assert ativo.tipo == "FI"
        assert ativo.id_quantum == "612014"

    def test_idempotente_por_chave_natural(self):
        svc = self._service()
        resultados = svc.buscar_por_cnpj("42.550.188/0001-91")
        svc.importar_ativos(resultados)
        svc.importar_ativos(resultados)
        assert Ativo.objects.count() == 1


@pytest.mark.django_db
class TestColetarSerie:
    def test_salva_cotacoes(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([
            ("2024-01-02", "100.0"), ("2024-01-03", "100.5"),
        ])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")
        n = svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        assert n == 2
        assert CotacaoDiaria.objects.filter(ativo=ativo).count() == 2

    def test_upsert_nao_duplica(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([("2024-01-02", "100.0")])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        assert CotacaoDiaria.objects.filter(ativo=ativo).count() == 1


@pytest.mark.django_db
class TestSeedIndices:
    def test_cria_nove_indices(self):
        seed_indices()
        assert Ativo.objects.filter(tipo="INDICE").count() == 9

    def test_cdi_presente(self):
        seed_indices()
        cdi = Ativo.objects.get(tipo="INDICE", id_quantum="1")
        assert cdi.nome == "CDI"

    def test_idempotente(self):
        seed_indices()
        seed_indices()
        assert Ativo.objects.filter(tipo="INDICE").count() == 9


@pytest.mark.django_db
class TestLoginLazy:
    def test_login_chamado_na_primeira_rede(self):
        client = MagicMock()
        client.buscar.return_value = []
        svc = QuantumService(client=client)
        svc.buscar_por_texto("X")
        client.login.assert_called_once()

    def test_login_nao_repetido(self):
        client = MagicMock()
        client.buscar.return_value = []
        svc = QuantumService(client=client)
        svc.buscar_por_texto("X")
        svc.buscar_por_texto("Y")
        client.login.assert_called_once()
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run pytest tests/test_services.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapper.services'`.

- [ ] **Step 3: Escrever os services**

Criar `scrapper/services.py`:

```python
"""Camada de orquestração: client (HTTP) + parsers (pydantic) + ORM.

Única camada que toca o Django ORM e converte pydantic -> models.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from loguru import logger

from scrapper.models import Ativo, CotacaoDiaria
from scrapper.quantum import parsers
from scrapper.quantum.catalogo import INDICES, TipoAtivo
from scrapper.quantum.client import QuantumClient
from scrapper.quantum.schemas import AtivoQuantum as AtivoQuantumSchema
from scrapper.quantum.schemas import ResultadoBusca


class QuantumService:
    """Orquestra busca/import/coleta. Login lazy na primeira chamada de rede."""

    def __init__(self, client: QuantumClient | None = None) -> None:
        self._client = client or QuantumClient()
        self._logged_in = False

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self._client.login()
            self._logged_in = True

    # ── Busca ───────────────────────────────────────────────────────────────
    def buscar_por_texto(self, termo: str) -> list[ResultadoBusca]:
        self._ensure_login()
        return parsers.parse_resultados_busca(self._client.buscar(termo, is_cnpj=False))

    def buscar_por_cnpj(self, cnpj: str) -> list[ResultadoBusca]:
        self._ensure_login()
        return parsers.parse_resultados_busca(self._client.buscar(cnpj, is_cnpj=True))

    # ── Import (rede -> pydantic -> ORM) ──────────────────────────────────────
    def importar_ativos(self, resultados: list[ResultadoBusca]) -> list[Ativo]:
        """Para cada resultado: busca metadados, monta o domínio e persiste.
        Idempotente via chave natural (tipo, id_quantum)."""
        self._ensure_login()
        ativos: list[Ativo] = []
        for resultado in resultados:
            raw = self._client.dados_complementares(resultado.tipo, resultado.id_quantum)
            meta = parsers.parse_metadados(resultado.tipo, raw)
            aq = parsers.montar_ativo(resultado, meta)
            ativos.append(self._persistir(aq))
        return ativos

    @transaction.atomic
    def _persistir(self, aq: AtivoQuantumSchema) -> Ativo:
        ativo, _ = Ativo.objects.update_or_create(
            tipo=aq.tipo.value,
            id_quantum=aq.id_quantum,
            defaults={
                "nome": aq.nome,
                "subtipo": aq.subtipo or "",
                "cnpj": aq.cnpj or "",
                "ticker": aq.ticker or "",
                "setor": aq.setor or "",
                "gestora": aq.gestora or "",
                "primeira_cota": aq.primeira_cota,
                "metadados": aq.metadados.model_dump(),
            },
        )
        return ativo

    # ── Cotas ─────────────────────────────────────────────────────────────────
    def coletar_serie(self, ativo: Ativo, data_inicio: date, data_fim: date) -> int:
        """Coleta a série diária do ativo e faz upsert em CotacaoDiaria."""
        self._ensure_login()
        di = ativo.primeira_cota if (ativo.primeira_cota and ativo.primeira_cota > data_inicio) else data_inicio
        raw = self._client.serie(TipoAtivo(ativo.tipo), ativo.id_quantum, di, data_fim)
        serie = parsers.parse_serie(raw)
        if not serie.pontos:
            return 0
        objs = [
            CotacaoDiaria(ativo=ativo, data=p.data, valor=p.valor)
            for p in serie.pontos
        ]
        CotacaoDiaria.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["ativo", "data"],
            update_fields=["valor"],
        )
        return len(objs)

    def coletar_indices(self, data_inicio: date, data_fim: date) -> int:
        """Coleta a série de todos os índices semeados."""
        total = 0
        for indice in Ativo.objects.filter(tipo=TipoAtivo.INDICE):
            try:
                total += self.coletar_serie(indice, data_inicio, data_fim)
            except Exception as exc:  # índice indisponível não derruba o lote
                logger.warning(f"Falha ao coletar índice {indice.nome}: {exc}")
        return total


def seed_indices() -> None:
    """Cria/atualiza os Ativos do tipo INDICE a partir de quantum.catalogo."""
    for id_quantum, nome in INDICES.items():
        Ativo.objects.update_or_create(
            tipo=TipoAtivo.INDICE.value,
            id_quantum=id_quantum,
            defaults={"nome": nome},
        )
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `uv run pytest tests/test_services.py -q`
Expected: PASS.

- [ ] **Step 5: Criar a data migration de seed dos índices**

Criar `scrapper/migrations/0002_seed_indices.py`:

```python
from django.db import migrations

# Espelha scrapper.quantum.catalogo.INDICES (inline para não acoplar a
# migração ao código; migração é um snapshot histórico).
_INDICES = {
    "1": "CDI", "31": "IPCA", "4": "Ibovespa", "51": "IMA-B", "15": "IRF-M",
    "7": "Dólar", "114": "IDA-DI", "453": "Poupança (Selic)", "8": "Poupança",
}


def seed(apps, schema_editor):
    Ativo = apps.get_model("scrapper", "Ativo")
    for id_quantum, nome in _INDICES.items():
        Ativo.objects.update_or_create(
            tipo="INDICE", id_quantum=id_quantum, defaults={"nome": nome}
        )


def unseed(apps, schema_editor):
    Ativo = apps.get_model("scrapper", "Ativo")
    Ativo.objects.filter(tipo="INDICE", id_quantum__in=list(_INDICES)).delete()


class Migration(migrations.Migration):
    dependencies = [("scrapper", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 6: Aplicar e verificar o seed**

Run: `uv run python manage.py migrate scrapper`
Then: `uv run python manage.py shell -c "from scrapper.models import Ativo; print(Ativo.objects.filter(tipo='INDICE').count())"`
Expected: imprime `9`.

- [ ] **Step 7: Commit**

```bash
git add scrapper/services.py scrapper/migrations/0002_seed_indices.py tests/test_services.py
git commit -m "feat(services): QuantumService (busca/import/coleta) + seed de índices"
```

---

### Task 8: `admin.py` — admin do Ativo unificado

**Files:**
- Modify: `scrapper/admin.py` (reescrita completa)

- [ ] **Step 1: Reescrever `scrapper/admin.py`**

Substituir todo o conteúdo por:

```python
from django.contrib import admin

from .models import Ativo, CotacaoDiaria, Job


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo", "subtipo", "ticker", "cnpj", "gestora", "atualizado_em"]
    list_filter = ["tipo", "subtipo"]
    search_fields = ["nome", "cnpj", "ticker", "id_quantum"]
    readonly_fields = ["criado_em", "atualizado_em"]


@admin.register(CotacaoDiaria)
class CotacaoDiariaAdmin(admin.ModelAdmin):
    list_display = ["ativo", "data", "valor"]
    list_filter = ["ativo__tipo"]
    search_fields = ["ativo__nome"]
    date_hierarchy = "data"


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["id", "tipo", "status", "detalhe", "criado_em", "concluido_em"]
    list_filter = ["tipo", "status"]
    readonly_fields = ["criado_em", "concluido_em"]
```

- [ ] **Step 2: Verificar que o Django carrega o admin**

Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Commit**

```bash
git add scrapper/admin.py
git commit -m "refactor(admin): admin do Ativo unificado"
```

---

### Task 9: `views.py` — views magras sobre os services

**Files:**
- Modify: `scrapper/views.py` (reescrita completa)

As views deixam de instanciar `QuantumScrapper`/fazer parsing. O modelo unificado elimina o par `Ativo`/`AtivoQuantum`: agora itera-se `Ativo` direto. Excel de importação suporta colunas `cnpj` e/ou `ticker` (busca por CNPJ ou por texto). Índices são coletados via `service.coletar_indices`.

- [ ] **Step 1: Reescrever `scrapper/views.py`**

Substituir todo o conteúdo de `scrapper/views.py` por:

```python
import io
import os
import tempfile
import threading
from datetime import date as date_type

import numpy as np
import pandas as pd
from django.db import close_old_connections
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Ativo, CotacaoDiaria, Job
from .quantum.catalogo import TipoAtivo
from .services import QuantumService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serie_do_banco_range(ativo: Ativo, di, df) -> pd.Series:
    cotacoes = list(
        CotacaoDiaria.objects.filter(ativo=ativo, data__gte=di, data__lte=df)
        .values_list("data", "valor")
        .order_by("data")
    )
    if not cotacoes:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(d): v for d, v in cotacoes}, name=ativo.nome)


def _carregar_termos_excel(filepath: str) -> list[tuple[str, bool]]:
    """Lê um Excel com colunas 'cnpj' e/ou 'ticker'/'nome'.
    Retorna (termo, is_cnpj) por linha. CNPJ tem prioridade quando presente."""
    df = pd.read_excel(filepath)
    df.columns = df.columns.str.lower().str.strip()
    if "cnpj" not in df.columns and "ticker" not in df.columns and "nome" not in df.columns:
        raise ValueError(
            f"Excel precisa de coluna 'cnpj', 'ticker' ou 'nome'. "
            f"Colunas: {list(df.columns)}"
        )
    termos: list[tuple[str, bool]] = []
    for row in df.itertuples():
        cnpj = getattr(row, "cnpj", None)
        if pd.notna(cnpj) if cnpj is not None else False:
            cnpj_str = f"{int(cnpj):014d}" if isinstance(cnpj, float) else str(cnpj).strip()
            if cnpj_str:
                termos.append((cnpj_str, True))
                continue
        for col in ("ticker", "nome"):
            valor = getattr(row, col, None)
            if valor is not None and pd.notna(valor) and str(valor).strip():
                termos.append((str(valor).strip(), False))
                break
    return termos


# ── Views ─────────────────────────────────────────────────────────────────────

def index(request):
    jobs = Job.objects.all()[:15]
    ativos_lista = (
        Ativo.objects.exclude(tipo=TipoAtivo.INDICE).order_by("nome")
    )
    ativos_count = ativos_lista.count()
    tem_cotacoes = CotacaoDiaria.objects.filter(ativo__in=ativos_lista).exists()
    return render(request, "scrapper/index.html", {
        "jobs": jobs,
        "ativos_count": ativos_count,
        "ativos_lista": ativos_lista,
        "tem_cotacoes": tem_cotacoes,
    })


def ativos_list(request):
    ativos = Ativo.objects.exclude(tipo=TipoAtivo.INDICE).order_by("nome")
    return render(request, "scrapper/ativos.html", {"ativos": ativos})


@require_POST
def buscar_ativos(request):
    arquivo = request.FILES.get("arquivo")
    if not arquivo:
        return JsonResponse({"erro": "Nenhum arquivo enviado."}, status=400)

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    for chunk in arquivo.chunks():
        tmp.write(chunk)
    tmp.close()

    job = Job.objects.create(tipo="buscar_ativos", detalhe=arquivo.name)

    def _run(tmp_path: str):
        close_old_connections()
        try:
            termos = _carregar_termos_excel(tmp_path)
            if not termos:
                raise ValueError(
                    "Nenhum ativo no Excel. Use colunas 'cnpj', 'ticker' ou 'nome'."
                )
            service = QuantumService()
            total = 0
            for termo, is_cnpj in termos:
                resultados = (
                    service.buscar_por_cnpj(termo) if is_cnpj
                    else service.buscar_por_texto(termo)
                )
                if resultados:
                    service.importar_ativos(resultados[:1])  # 1º candidato
                    total += 1
            job.status = "done"
            job.detalhe = f"{total} de {len(termos)} ativos importados de '{arquivo.name}'"
            job.concluido_em = timezone.now()
            job.save()
        except Exception as exc:
            job.status = "error"
            job.erro = str(exc)
            job.concluido_em = timezone.now()
            job.save()
        finally:
            close_old_connections()
            os.unlink(tmp_path)

    threading.Thread(target=_run, args=(tmp.name,), daemon=True).start()
    return JsonResponse({"job_id": job.id})


@require_POST
def adicionar_cnpj(request):
    cnpj = request.POST.get("cnpj", "").strip()
    if not cnpj:
        return JsonResponse({"erro": "Informe o CNPJ."}, status=400)

    job = Job.objects.create(tipo="buscar_ativos", detalhe=f"CNPJ: {cnpj}")

    def _run():
        close_old_connections()
        try:
            service = QuantumService()
            resultados = service.buscar_por_cnpj(cnpj)
            if not resultados:
                raise ValueError(f"CNPJ {cnpj!r} não encontrado no Quantum.")
            ativo = service.importar_ativos(resultados[:1])[0]
            job.status = "done"
            job.detalhe = f"Ativo '{ativo.nome}' adicionado (CNPJ: {cnpj})"
            job.concluido_em = timezone.now()
            job.save()
        except Exception as exc:
            job.status = "error"
            job.erro = str(exc)
            job.concluido_em = timezone.now()
            job.save()
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"job_id": job.id})


@require_POST
def scrap_cotas(request):
    data_inicio = request.POST.get("data_inicio")
    data_fim = request.POST.get("data_fim")
    ativo_ids = request.POST.getlist("ativo_ids")

    if not data_inicio or not data_fim:
        return JsonResponse({"erro": "Informe data_inicio e data_fim."}, status=400)
    if not ativo_ids:
        return JsonResponse({"erro": "Selecione pelo menos um ativo."}, status=400)

    job = Job.objects.create(
        tipo="scrap",
        detalhe=f"{data_inicio} → {data_fim} · {len(ativo_ids)} ativo(s)",
    )

    def _run():
        close_old_connections()
        try:
            di = date_type.fromisoformat(data_inicio)
            df_fim = date_type.fromisoformat(data_fim)

            ativos = list(
                Ativo.objects.filter(id__in=ativo_ids).exclude(tipo=TipoAtivo.INDICE)
            )
            if not ativos:
                raise ValueError("Nenhum ativo válido selecionado.")

            service = QuantumService()
            total = 0
            for ativo in ativos:
                total += service.coletar_serie(ativo, di, df_fim)
            total += service.coletar_indices(di, df_fim)

            job.status = "done"
            job.detalhe = (
                f"{len(ativos)} ativo(s) · {total} cotações salvas "
                f"({data_inicio} → {data_fim})"
            )
            job.concluido_em = timezone.now()
            job.save()
        except Exception as exc:
            job.status = "error"
            job.erro = str(exc)
            job.concluido_em = timezone.now()
            job.save()
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"job_id": job.id})


def _selecao_ctx(data_inicio="", data_fim="", erro=""):
    return {
        "carteiras": Ativo.objects.exclude(tipo=TipoAtivo.INDICE).order_by("nome"),
        "indices": Ativo.objects.filter(tipo=TipoAtivo.INDICE).order_by("nome"),
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "erro": erro,
    }


def relatorio(request):
    ids = request.GET.getlist("ids")
    data_inicio_str = request.GET.get("data_inicio", "")
    data_fim_str = request.GET.get("data_fim", "")

    if not ids or not data_inicio_str or not data_fim_str:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
        ))

    try:
        di = date_type.fromisoformat(data_inicio_str)
        df = date_type.fromisoformat(data_fim_str)
    except ValueError:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            erro="Data inválida. Use o formato AAAA-MM-DD.",
        ))

    if di >= df:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
            erro="A data de início deve ser anterior à data de fim.",
        ))

    ativos = list(Ativo.objects.filter(id__in=ids))
    service: QuantumService | None = None

    precos_carteiras: dict[str, pd.Series] = {}
    precos_indices: dict[str, pd.Series] = {}

    for ativo in ativos:
        tem_dados = CotacaoDiaria.objects.filter(
            ativo=ativo, data__gte=di, data__lte=df
        ).exists()
        if not tem_dados:
            if service is None:
                service = QuantumService()
            try:
                service.coletar_serie(ativo, di, df)
            except Exception:
                pass  # ativo ignorado se a busca falhar

        serie = _serie_do_banco_range(ativo, di, df)
        if serie.empty:
            continue
        if ativo.tipo == TipoAtivo.INDICE:
            precos_indices[ativo.nome] = serie
        else:
            precos_carteiras[ativo.nome] = serie

    if not precos_carteiras:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
            erro="Nenhuma cotação encontrada para os ativos e período selecionados.",
        ))

    from .analise import gerar_relatorio_html

    html = gerar_relatorio_html(precos_carteiras, precos_indices)
    return HttpResponse(html)


def exportar_excel(request):
    ids = request.GET.getlist("ids")
    if not ids:
        return HttpResponse("Selecione pelo menos um ativo.", status=400)

    ativos = (
        Ativo.objects.filter(id__in=ids).exclude(tipo=TipoAtivo.INDICE).order_by("nome")
    )
    rows = [
        {"id_quantum": a.id_quantum, "nome": a.nome, "tipo": a.tipo,
         "cnpj": a.cnpj, "ticker": a.ticker, "gestora": a.gestora, **(a.metadados or {})}
        for a in ativos
    ]

    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="dados_complementares.xlsx"'
    return response


def exportar_cotas_excel(request):
    ids = request.GET.getlist("ids")
    data_inicio_str = request.GET.get("data_inicio", "")
    data_fim_str = request.GET.get("data_fim", "")

    aq_qs = Ativo.objects.exclude(tipo=TipoAtivo.INDICE)
    if ids:
        aq_qs = aq_qs.filter(id__in=ids)

    filtro_data: dict = {}
    if data_inicio_str:
        filtro_data["data__gte"] = date_type.fromisoformat(data_inicio_str)
    if data_fim_str:
        filtro_data["data__lte"] = date_type.fromisoformat(data_fim_str)

    cotas: dict[str, pd.Series] = {}
    for ativo in aq_qs.order_by("nome"):
        pts = list(
            CotacaoDiaria.objects.filter(ativo=ativo, **filtro_data)
            .values_list("data", "valor")
            .order_by("data")
        )
        if pts:
            cotas[ativo.nome] = pd.Series({pd.Timestamp(d): v for d, v in pts})

    if not cotas:
        return HttpResponse("Nenhuma cotação encontrada para os ativos selecionados.", status=404)

    df_cotas = pd.DataFrame(cotas).sort_index()
    if not data_inicio_str and not data_fim_str and len(cotas) > 1:
        latest_start = max(s.index[0] for s in cotas.values())
        df_cotas = df_cotas.loc[latest_start:]
    df_cotas = df_cotas.dropna(how="all", axis=0)
    df_cotas.index.name = "data"

    df_ln = np.log(df_cotas / df_cotas.shift(1)).dropna(how="all", axis=0)
    df_ln.index.name = "data"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_cotas.to_excel(writer, sheet_name="Cotas")
        df_ln.to_excel(writer, sheet_name="Retorno_LN")
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="cotas_retorno_ln.xlsx"'
    return response


def job_status(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    return JsonResponse({
        "id": job.id,
        "tipo": job.tipo,
        "status": job.status,
        "detalhe": job.detalhe,
        "erro": job.erro,
        "criado_em": job.criado_em.isoformat(),
        "concluido_em": job.concluido_em.isoformat() if job.concluido_em else None,
    })
```

- [ ] **Step 2: Verificar que o Django carrega as views/URLs**

Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 3: Commit**

```bash
git add scrapper/views.py
git commit -m "refactor(views): views magras delegando ao QuantumService"
```

---

### Task 10: Templates — atualizar referências de campos do ORM

**Files:**
- Modify: `scrapper/templates/scrapper/index.html`
- Modify: `scrapper/templates/scrapper/ativos.html`
- Modify: `scrapper/templates/scrapper/relatorio.html`

O contexto agora entrega `Ativo` direto (não mais `AtivoQuantum` com `.ativo`/`.quantum`). Atualizar só as referências de campo (sem redesign).

- [ ] **Step 1: index.html — `aq.ativo.nome` → `aq.nome`**

Em `scrapper/templates/scrapper/index.html`, substituir a linha 93:
```
                {{ aq.ativo.nome }}
```
por:
```
                {{ aq.nome }}
```
(A linha 94 `{{ aq.tipo }}` já funciona — `tipo` é campo direto do `Ativo`.)

- [ ] **Step 2: relatorio.html — `aq.ativo.nome` → `aq.nome`**

Em `scrapper/templates/scrapper/relatorio.html`, substituir as duas ocorrências (linhas 69 e 97):
```
                {{ aq.ativo.nome }}
```
por:
```
                {{ aq.nome }}
```
(A linha 70 `{{ aq.tipo }}` já funciona.)

- [ ] **Step 3: ativos.html — remover o nível `.quantum`**

Em `scrapper/templates/scrapper/ativos.html`, fazer as substituições:
- `{% if ativo.quantum %}` → `{% if ativo.id_quantum %}`
- `{{ ativo.quantum.id_quantum }}` → `{{ ativo.id_quantum }}`
- `{{ ativo.quantum.tipo }}` → `{{ ativo.tipo }}`
- `{{ ativo.quantum.gestora|default:"—" }}` → `{{ ativo.gestora|default:"—" }}`
- `{% if ativo.quantum.primeira_cota %}{{ ativo.quantum.primeira_cota|date:"d/m/Y" }}{% else %}—{% endif %}` → `{% if ativo.primeira_cota %}{{ ativo.primeira_cota|date:"d/m/Y" }}{% else %}—{% endif %}`
- `{{ ativo.quantum.atualizado_em|date:"d/m/Y H:i" }}` → `{{ ativo.atualizado_em|date:"d/m/Y H:i" }}`

(As linhas 30-31 `{{ ativo.nome }}` e `{{ ativo.cnpj }}` já funcionam — campos diretos.)

- [ ] **Step 4: Confirmar que não restam referências antigas**

Run: `grep -rn "\.ativo\.nome\|\.quantum\." scrapper/templates`
Expected: nenhuma saída (todas removidas).

- [ ] **Step 5: Subir o servidor e checar smoke**

Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 6: Commit**

```bash
git add scrapper/templates/scrapper/
git commit -m "refactor(templates): referências de campo para o Ativo unificado"
```

---

### Task 11: Remover o client legado e o teste antigo; verificação final

**Files:**
- Delete: `tests/test_quantum_scrapper.py`
- Modify (opcional): `quantum_scrapper.py`

> `quantum_scrapper.py` não é mais importado por nenhuma view (Task 9 removeu os imports). Ele permanece como script standalone (`__main__`) e referência, mas seu antigo teste cobre uma API que não usamos mais no app. O novo conjunto de testes (`tests/quantum/*`, `tests/test_services.py`) cobre a fundação refatorada.

- [ ] **Step 1: Confirmar que nada no app importa quantum_scrapper**

Run: `grep -rn "import quantum_scrapper\|from quantum_scrapper" scrapper/`
Expected: nenhuma saída.

- [ ] **Step 2: Remover o teste legado**

```bash
git rm tests/test_quantum_scrapper.py
```

> Motivo: testa `QuantumScrapper` (HTTP+parsing acoplados, `id_quantum` int, validação de 24 medidas) — comportamento substituído. As regressões equivalentes (id string, medidas por tipo, série) estão em `tests/quantum/test_parsers.py` e `tests/quantum/test_client.py`.

- [ ] **Step 3: Rodar a suíte completa**

Run: `uv run pytest -q`
Expected: PASS — `tests/quantum/test_catalogo.py`, `test_schemas.py`, `test_parsers.py`, `test_client.py` e `tests/test_services.py` passam; nenhum erro de coleta.

- [ ] **Step 4: Check final do Django**

Run: `uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run`
Expected: sem issues e **sem migrations pendentes** (modelos e migrações em sincronia).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remover teste do client legado; fundação refatorada coberta por novos testes"
```

---

## Notas e divergências resolvidas durante o planejamento

1. **Catálogo de índices:** o `_INDICES_QUANTUM` hard-coded em `views.py` (antigo) divergia do capturado em `/api/benchmarks/...` (ex.: associava IPCA=7, IMA-B=114, IRF-M=31). O plano segue **`docs/api-quantum.md`** (a captura real): IPCA=31, IMA-B=51, IRF-M=15, Dólar=7, IDA-DI=114. O mapeamento antigo das views é descartado.
2. **FI tem 24 medidas, não 25:** o spec dizia "25"; a captura de 2026-05-26 confirma **24** (igual ao `ordem_medidas` do código atual). O plano usa 24.
3. **`MEDIDAS_POR_TIPO` em `catalogo.py`** (e não em `parsers.py`): client e parsers dependem dela e o client não pode importar parsers.
4. **INDICE/RENDA_FIXA sem card de medidas:** metadados tolerantes/mínimos (só `NOME`). Séries funcionam normalmente.
5. **`quantum_scrapper.py` preservado** como script standalone; só deixou de ser dependência do app.

## Cobertura do spec (self-review)

| Requisito do spec | Task |
|-------------------|------|
| Pacote `scrapper/quantum/` | 2–5 |
| Enums + catálogo de índices | 2 |
| Schemas Pydantic (domínio + metadados por tipo, tolerantes) | 3 |
| Parsers puros (busca/série/metadados) substituindo os métodos quebrados | 4 |
| Client HTTP puro (Bearer, dict cru) | 5 |
| `Ativo` unificado, chave natural `(tipo, id_quantum)`, `id_quantum` string | 6 |
| Migração limpa (reset) + seed de índices via RunPython | 6, 7 |
| `QuantumService` (login lazy, busca, import idempotente, coleta, índices) | 7 |
| Admin do Ativo unificado | 8 |
| Views magras delegando aos services; threading + Job mantidos | 9 |
| Templates alinhados ao modelo unificado | 10 |
| Testes por camada (parsers/schemas/client/services) + regressões | 2–7, 11 |
| Regressão: RENDA_FIXA id string | 4 (`test_renda_fixa_id_string_nao_quebra`) |
| Regressão: medidas FII(22)/ACAO(14) não quebram | 4 (`test_acao_14_valores_nao_quebra`) |
| Regressão: série equivalente | 4 (`TestParseSerie`) |
