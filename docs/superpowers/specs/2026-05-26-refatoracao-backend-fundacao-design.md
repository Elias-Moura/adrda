# Refatoração do back-end — Fase 1 (Fundação) — Design

**Data:** 2026-05-26
**Status:** Aprovado para planejamento (3 perguntas em aberto resolvidas em 2026-05-26)
**Escopo:** Fase 1 de um trabalho maior. Esta fase cobre **modelos + relacionamentos,
camada de parsers Pydantic, refatoração do client e camada de services**. A
composição de carteira investida e o front-end (templates Django) ficam para
specs seguintes.

## Contexto

O projeto coleta dados do Quantum Comparador de Ativos e persiste em banco
(Django ORM). Sessões de engenharia reversa (ver `docs/api-quantum.md`) mapearam:

- Busca por texto retorna **múltiplos grupos** de tipos diferentes; `identificador`
  pode ser **string** (tipo `RENDA_FIXA`, ex.: `"VALE38"`).
- Ação/BDR/ETF são todos `tipoItemSelecionavel=ACAO`; o subtipo só aparece em
  `informacaoAdicional` (`Type: Stocks|BDR|ETF`).
- `medidas/valor` (dados complementares) usa **conjuntos de medidas distintos por
  tipo** (FI=25, FII=22, ACAO=14).
- Benchmarks são ativos do tipo `INDICE` (CDI=1, IPCA=31, ...).

**Problemas no código atual que esta fase resolve:**
- `quantum_scrapper.py` mistura HTTP e parsing; views fazem mais parsing inline.
- `_parsear_resultados_busca` faz `int(item["identificador"])` → quebra em `RENDA_FIXA`.
- `_simplificar_retorno_multiplex` tem a lista de 25 medidas do FI hard-coded e
  valida o tamanho → quebra para FII (22) e ACAO (14).
- Metadados num único JSON sem validação; chave de unicidade só por CNPJ (frágil
  para ativos sem CNPJ: ação, BDR, ETF, índice, renda fixa).
- Lista de índices hard-coded nas views.

## Decisões (definidas no brainstorming)

1. **Escopo:** Fase 1 = fundação (modelos, parsers, client, services). Carteira e
   front-end são fases seguintes.
2. **Metadados:** Pydantic + JSON validado + **colunas promovidas** (campos comuns
   viram colunas reais; o resto fica no JSON validado).
3. **Identidade:** **um modelo `Ativo` unificado** (colapsa `Ativo`+`AtivoQuantum`),
   chave natural **`(tipo, id_quantum)`**. CNPJ vira coluna opcional indexada.
4. **Camadas:** `client` (HTTP puro) → `parsers` (cru→pydantic) → `schemas`
   (pydantic) → `services` (orquestra + ORM) → views magras.
5. **Dados:** banco pode ser **resetado/re-populado** → migração limpa, sem data
   migration.
6. **Pacote:** subpacote `scrapper/quantum/`.
7. **Metadados tolerantes:** campos opcionais (`extra="ignore"`); não falha se o
   Quantum mudar/adicionar medidas.
8. **Login lazy:** `QuantumService` autentica na primeira chamada de rede.

**Perguntas em aberto resolvidas (2026-05-26):**
- **Colunas promovidas:** confirmadas como `cnpj`, `ticker`, `setor`, `gestora`,
  `primeira_cota`, `subtipo` (sem ajustes).
- **Jobs:** mantém `threading.Thread` + `Job` nesta fase (sem Celery).
- **`PORTFOLIO`:** **removido** do enum `TipoAtivo` nesta fase; volta junto com a
  feature de carteira investida.

## Estrutura de pacotes e camadas

```
scrapper/
  quantum/
    __init__.py        # API pública do pacote
    client.py          # QuantumClient — só HTTP/sessão/token. Devolve dict cru.
    schemas.py         # modelos Pydantic v2 (domínio + metadados por tipo)
    parsers.py         # funções puras: dict cru → schemas Pydantic
    catalogo.py        # enums (TipoAtivo, SubtipoAcao) + catálogo de índices
  services.py          # orquestra client+parsers+ORM (com @transaction)
  models.py            # ORM Django (Ativo unificado, CotacaoDiaria, Job)
  views.py             # magras: validam request → chamam services → render/JSON
```

Fluxo unidirecional:
```
views → services → client (HTTP cru)
                 → parsers (cru→pydantic) → schemas
        services persiste pydantic → ORM
```

Regras de dependência (cada camada só conhece a de baixo):
- `client` não importa Django nem ORM (transporte puro).
- `parsers` e `schemas` são puro-Python (sem Django).
- `services` é a única camada que toca o ORM e converte pydantic → models.
- `views` não instanciam client nem fazem parsing.

## Modelos ORM (`models.py`)

```python
class Ativo(models.Model):
    tipo          = CharField(choices=TipoAtivo)   # FI, FII, ACAO, INDICE, RENDA_FIXA  (PORTFOLIO entra na fase de carteira)
    id_quantum    = CharField(max_length=100)      # string (cobre RENDA_FIXA "VALE38")
    subtipo       = CharField(blank=True)          # Stocks/BDR/ETF (só p/ ACAO)
    nome          = CharField()
    # colunas promovidas (consultáveis/indexadas)
    cnpj          = CharField(blank=True, db_index=True)   # opcional
    ticker        = CharField(blank=True, db_index=True)
    setor         = CharField(blank=True)
    gestora       = CharField(blank=True)
    primeira_cota = DateField(null=True, blank=True)
    # resto dos metadados, já validado por pydantic
    metadados     = JSONField(default=dict)
    criado_em     = DateTimeField(auto_now_add=True)
    atualizado_em = DateTimeField(auto_now=True)

    class Meta:
        constraints = [UniqueConstraint(fields=["tipo", "id_quantum"], name="ativo_natural_key")]

class CotacaoDiaria(models.Model):
    ativo = ForeignKey(Ativo, on_delete=CASCADE, related_name="cotacoes")
    data  = DateField(db_index=True)
    valor = FloatField()
    class Meta:
        ordering = ["data"]
        unique_together = [("ativo", "data")]

class Job(models.Model):   # mantido como está hoje (tipo/status/detalhe/erro/timestamps)
    ...
```

## Schemas Pydantic (`schemas.py`)

```python
class ResultadoBusca(BaseModel):       # saída da busca por texto
    label: str
    tipo: TipoAtivo
    id_quantum: str                    # str! corrige bug do int()
    subtipo: str | None = None
    cnpj: str | None = None
    codigo_grupo: int = 0

class PontoSerie(BaseModel):
    data: date
    valor: float

class SerieDiaria(BaseModel):
    pontos: list[PontoSerie]

class MetaBase(BaseModel):
    model_config = ConfigDict(extra="ignore")   # tolerante

class MetaFI(MetaBase):       ...   # 25 medidas (todas Optional)
class MetaFII(MetaBase):      ...   # 22 medidas
class MetaACAO(MetaBase):     ...   # 14 medidas (ticker, bolsa, setor_quantum, ...)
class MetaIndice(MetaBase):   ...
class MetaRendaFixa(MetaBase): ...

class AtivoQuantum(BaseModel):       # objeto de domínio que services persiste
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

Notas:
- `id_quantum` é **string** em ORM e pydantic.
- Metadados **tolerantes**: campos `Optional`, `extra="ignore"`.
- Colunas promovidas derivam dos metadados validados; `metadados` JSON guarda
  `meta.model_dump()`.

## Parsers (`parsers.py`) — funções puras

```python
def parse_resultados_busca(grupos: list[dict]) -> list[ResultadoBusca]:
    # achata todos os grupos; id_quantum como str;
    # extrai subtipo e cnpj de informacaoAdicional
    #   ("Type: Stocks|BDR|ETF|Debênture", "CNPJ: 00.000.000/0000-00")

def parse_serie(raw_multiplex: dict) -> SerieDiaria:
    # responseList[0].body → {"serie":[{data,valor}]} → SerieDiaria

_MEDIDAS_POR_TIPO: dict[TipoAtivo, list[str]]   # ordem das medidas por tipo
_META_CLASS: dict[TipoAtivo, type[MetaBase]]    # FI→MetaFI, FII→MetaFII, ...

def parse_metadados(tipo: TipoAtivo, raw_multiplex: dict) -> MetaBase:
    # zip(ordem_medidas[tipo], valores) → dict → MetaClass(**dict)  (tolerante)

def montar_ativo(resultado: ResultadoBusca, meta: MetaBase) -> AtivoQuantum
```

Substitui `_parsear_resultados_busca`, `_simplificar_retorno_multiplex` (incluindo
a validação de tamanho que quebrava) e `_extrair_serie`. Testável com dicts fixos,
sem mocks de rede.

## Services (`services.py`)

```python
class QuantumService:
    def __init__(self):
        self._client = QuantumClient()      # login lazy

    def _ensure_login(self): ...            # autentica na 1ª chamada de rede

    # busca
    def buscar_por_texto(self, termo) -> list[ResultadoBusca]
    def buscar_por_cnpj(self, cnpj) -> list[ResultadoBusca]

    # import (rede → pydantic → ORM); idempotente via chave natural
    def importar_ativos(self, resultados: list[ResultadoBusca], *, rate=10) -> list[Ativo]
    def _persistir(self, aq: AtivoQuantum) -> Ativo   # pydantic→ORM + colunas promovidas

    # cotas
    def coletar_serie(self, ativo: Ativo, di, df) -> int   # bulk upsert CotacaoDiaria
    def coletar_indices(self, di, df) -> int               # usa catalogo

def seed_indices() -> None    # cria Ativos tipo INDICE a partir de quantum.catalogo
```

Decisões da camada:
- `_persistir` faz `update_or_create(tipo=..., id_quantum=...)`, preenche colunas
  promovidas a partir do pydantic e grava `metadados = meta.model_dump()`.
- Índices/benchmarks saem do hard-code nas views → `quantum/catalogo.py`
  (CDI=1, IPCA=31, Ibovespa=4, IMA-B=51, IRF-M=15, Dólar=7, IDA-DI=114,
  Poupança-Selic=453, Poupança=8), semeados como `Ativo` tipo INDICE.
- Jobs/threading: mantém `threading.Thread` + `Job`, mas o corpo do thread vira
  uma chamada a `services`. Celery fica fora desta fase (YAGNI).
- Seleção de tipo na busca: `importar_ativos` recebe `ResultadoBusca` já escolhido
  (resolve o `dados[0][0]` cego); preferência de tipo explícita e testável.

## Client (`client.py`)

`QuantumClient` = só transporte:
- `login()` / token Bearer / sessão (cookie JSESSIONID).
- Métodos que devolvem **dict cru** (sem parsing): `buscar(termo, is_cnpj)`,
  `dados_complementares(tipo, id)`, `serie(tipo, id, di, df)`.
- `/b` envia o header `authorization: Bearer` (necessário; só cookie dá 401).
  Busca global e endpoints `webaxis2/*` usam só o cookie.
- Sem dependência de Django/ORM.

## Migração e dependências

- `pyproject.toml`: `+ pydantic>=2.7`.
- Banco pode resetar: **apagar migrations antigas do app e recriar** `0001_initial`;
  `migrate` em banco limpo. Sem data migration.
- Migration de dados (`RunPython`) para **seed dos índices** a partir de `catalogo.py`.
- `admin.py` atualizado para o `Ativo` unificado (list_display: tipo, subtipo,
  ticker, cnpj, gestora).

## Testes (pytest)

| Camada | Como testar | Sem… |
|--------|-------------|------|
| `parsers.py` | dicts crus fixos (HASH11, VALE3+RENDA_FIXA, série, metadados FI/FII/ACAO) → asserts nos pydantic | sem rede, sem banco |
| `schemas.py` | tolera campo faltante; `id_quantum="VALE38"` ok; coerção de tipos | sem rede, sem banco |
| `client.py` | HTTP mockado (respx/MagicMock): monta URL/headers/Bearer corretos | sem banco |
| `services.py` | `@pytest.mark.django_db`, client mockado, parsers reais → asserta ORM | sem rede real |

Casos de regressão obrigatórios (bugs revelados nesta sessão):
- busca com resultado `RENDA_FIXA` (id string) **não** quebra;
- metadados de `FII` (22) e `ACAO` (14) **não** quebram;
- série `EVOLUCAO_DO_ATIVO` parseada de forma equivalente ao retorno validado de hoje.

Migrar `tests/test_quantum_scrapper.py` para a nova estrutura
(`tests/quantum/test_parsers.py`, `test_client.py`, `test_services.py`), com
fixtures dos JSONs reais capturados.

## Fora de escopo (fases seguintes)

- Composição de carteira investida (REST JSON `/api/ativos/{tipo}/{id}/carteira`
  para FI; extrato `.qt` via `laminaFundo` para FII; agregações tipo/setor/risco/classe).
- Telas/templates Django para as novas funcionalidades.
- Cálculo local de métricas de risco (volatilidade, Sharpe, janela móvel) a partir
  da série diária.
