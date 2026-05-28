# Tela de Detalhes do Ativo (com carteira do fundo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar uma página dedicada de detalhes do ativo (`/ativos/<id>/`) com ficha, estatísticas, gráfico Plotly da série base-100 e composição da carteira (FI) persistida no banco.

**Architecture:** Mantém a separação em camadas do projeto: `quantum/client.py` (HTTP cru) → `quantum/parsers.py` (pydantic puro) → `services.py` (orquestra + ORM) → `views.py` (magras) → templates. Carteira é coletada sob demanda via endpoint REST `/carteira` do multiplex `/b` e gravada em dois modelos novos (`CarteiraFundo` + `PosicaoCarteira`). O gráfico reaproveita o padrão Plotly de `analise.py`.

**Tech Stack:** Python 3.11, Django 5, httpx, pydantic v2, pandas, Plotly, pytest + pytest-django.

---

## Arquivos

- **Modificar:** `scrapper/models.py` — adiciona `CarteiraFundo` e `PosicaoCarteira`.
- **Criar:** `scrapper/migrations/0003_*.py` — via `makemigrations` (nome exato gerado pelo Django).
- **Modificar:** `scrapper/quantum/schemas.py` — adiciona `PosicaoCarteira` e `Carteira` (pydantic).
- **Modificar:** `scrapper/quantum/parsers.py` — adiciona `parse_carteira`.
- **Modificar:** `scrapper/quantum/client.py` — adiciona método `carteira`.
- **Modificar:** `scrapper/services.py` — adiciona `coletar_carteira`.
- **Modificar:** `scrapper/analise.py` — adiciona `gerar_grafico_ativo_html`.
- **Modificar:** `scrapper/views.py` — adiciona `detalhe_ativo` e `atualizar_carteira`.
- **Modificar:** `scrapper/urls.py` — duas rotas novas.
- **Criar:** `scrapper/templates/scrapper/detalhe.html`.
- **Modificar:** `scrapper/templates/scrapper/ativos.html` — linha clicável.
- **Testes:** `tests/quantum/test_parsers.py`, `tests/quantum/test_client.py`, `tests/test_services.py`, `tests/test_views.py`, `tests/test_models.py` (novo).

> **Nota de verificação (do spec):** o método HTTP exato do endpoint de carteira (GET vs POST dentro do multiplex) e se `dataCompetencia` pode ser omitido não estão 100% confirmados. O plano usa `method="GET"` no item do multiplex e `dataCompetencia` = 1º dia do mês corrente. Ao executar a Task 4, valide contra a API real (login + chamada) e ajuste a URL/método se a resposta vier vazia ou com erro.

---

### Task 1: Modelos `CarteiraFundo` e `PosicaoCarteira`

**Files:**
- Modify: `scrapper/models.py`
- Create (gerado): `scrapper/migrations/0003_*.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_models.py`:

```python
from datetime import date

import pytest

from scrapper.models import Ativo, CarteiraFundo, PosicaoCarteira


@pytest.mark.django_db
class TestCarteiraFundo:
    def _ativo(self):
        return Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")

    def test_unique_ativo_competencia(self):
        ativo = self._ativo()
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))

    def test_ordena_por_competencia_desc(self):
        ativo = self._ativo()
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 3, 1))
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        assert ativo.carteiras.first().competencia == date(2026, 4, 1)

    def test_cascade_apaga_posicoes(self):
        ativo = self._ativo()
        carteira = CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        PosicaoCarteira.objects.create(carteira=carteira, nome="LFT 2030", participacao=12.3, ordem=0)
        carteira.delete()
        assert PosicaoCarteira.objects.count() == 0

    def test_posicoes_ordenadas_por_ordem(self):
        ativo = self._ativo()
        carteira = CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        PosicaoCarteira.objects.create(carteira=carteira, nome="B", participacao=5.0, ordem=1)
        PosicaoCarteira.objects.create(carteira=carteira, nome="A", participacao=9.0, ordem=0)
        assert [p.nome for p in carteira.posicoes.all()] == ["A", "B"]
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'CarteiraFundo'`.

- [ ] **Step 3: Adicionar os modelos**

No fim de `scrapper/models.py` (após `Job`):

```python
class CarteiraFundo(models.Model):
    """Composição da carteira de um fundo numa competência (mês de referência)."""

    ativo = models.ForeignKey(
        Ativo, on_delete=models.CASCADE, related_name="carteiras"
    )
    competencia = models.DateField()
    importada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-competencia"]
        verbose_name = "Carteira de Fundo"
        verbose_name_plural = "Carteiras de Fundo"
        constraints = [
            models.UniqueConstraint(
                fields=["ativo", "competencia"], name="carteira_ativo_competencia"
            )
        ]

    def __str__(self):
        return f"{self.ativo.nome} — {self.competencia:%m/%Y}"


class PosicaoCarteira(models.Model):
    """Uma posição (ativo investido) dentro de uma CarteiraFundo."""

    carteira = models.ForeignKey(
        CarteiraFundo, on_delete=models.CASCADE, related_name="posicoes"
    )
    nome = models.CharField(max_length=255)
    participacao = models.FloatField()
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem"]
        verbose_name = "Posição da Carteira"
        verbose_name_plural = "Posições da Carteira"

    def __str__(self):
        return f"{self.nome}: {self.participacao:.2f}%"
```

- [ ] **Step 4: Gerar a migração**

Run: `python manage.py makemigrations scrapper`
Expected: cria `scrapper/migrations/0003_*.py` com os dois modelos.

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 testes).

- [ ] **Step 6: Commit**

```bash
git add scrapper/models.py scrapper/migrations/ tests/test_models.py
git commit -m "feat(carteira): modelos CarteiraFundo e PosicaoCarteira"
```

---

### Task 2: Schemas pydantic `PosicaoCarteira` e `Carteira`

**Files:**
- Modify: `scrapper/quantum/schemas.py`
- Test: `tests/quantum/test_schemas.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar ao fim de `tests/quantum/test_schemas.py`:

```python
class TestCarteiraSchema:
    def test_posicao_aceita_participacao_float(self):
        from scrapper.quantum.schemas import PosicaoCarteira as PosicaoSchema
        p = PosicaoSchema(nome="LFT 2030", participacao=12.34)
        assert p.participacao == 12.34

    def test_posicao_coage_participacao_string(self):
        from scrapper.quantum.schemas import PosicaoCarteira as PosicaoSchema
        p = PosicaoSchema(nome="LFT 2030", participacao="12.3351017")
        assert round(p.participacao, 4) == 12.3351

    def test_carteira_vazia_por_padrao(self):
        from scrapper.quantum.schemas import Carteira
        c = Carteira()
        assert c.posicoes == []
        assert c.competencia is None
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/quantum/test_schemas.py::TestCarteiraSchema -v`
Expected: FAIL — `ImportError: cannot import name 'PosicaoCarteira'`.

- [ ] **Step 3: Adicionar os schemas**

Em `scrapper/quantum/schemas.py`, após a classe `SerieDiaria` (antes de `MetaBase`):

```python
class PosicaoCarteira(BaseModel):
    """Uma posição da carteira investida (nome do ativo + participação %)."""

    nome: str
    participacao: float


class Carteira(BaseModel):
    competencia: date | None = None
    posicoes: list[PosicaoCarteira] = []
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `pytest tests/quantum/test_schemas.py::TestCarteiraSchema -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/quantum/schemas.py tests/quantum/test_schemas.py
git commit -m "feat(carteira): schemas pydantic PosicaoCarteira e Carteira"
```

---

### Task 3: Parser `parse_carteira`

**Files:**
- Modify: `scrapper/quantum/parsers.py`
- Test: `tests/quantum/test_parsers.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar ao fim de `tests/quantum/test_parsers.py`:

```python
import json
from datetime import date


def _multiplex_carteira(itens: list[dict]) -> dict:
    return {"responseList": [{"body": json.dumps(itens)}]}


class TestParseCarteira:
    def test_extrai_posicoes_com_participacao_float(self):
        from scrapper.quantum.parsers import parse_carteira
        raw = _multiplex_carteira([
            {"ativo": "LFT - Venc.: 01/03/2030", "participacao": "12.33510179"},
            {"ativo": "Outros Ativos", "participacao": "29.7519"},
        ])
        carteira = parse_carteira(raw, competencia=date(2026, 4, 1))
        assert carteira.competencia == date(2026, 4, 1)
        assert len(carteira.posicoes) == 2
        assert carteira.posicoes[0].nome == "LFT - Venc.: 01/03/2030"
        assert round(carteira.posicoes[0].participacao, 2) == 12.34

    def test_item_malformado_e_descartado(self):
        from scrapper.quantum.parsers import parse_carteira
        raw = _multiplex_carteira([
            {"ativo": "LFT 2030", "participacao": "12.3"},
            {"ativo": "Quebrado"},  # sem participacao
        ])
        carteira = parse_carteira(raw)
        assert len(carteira.posicoes) == 1

    def test_body_ausente_carteira_vazia(self):
        from scrapper.quantum.parsers import parse_carteira
        carteira = parse_carteira({"responseList": []})
        assert carteira.posicoes == []
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/quantum/test_parsers.py::TestParseCarteira -v`
Expected: FAIL — `ImportError: cannot import name 'parse_carteira'`.

- [ ] **Step 3: Implementar o parser**

Em `scrapper/quantum/parsers.py`: adicionar `Carteira` e `PosicaoCarteira` ao import do `.schemas` (junto dos demais), e acrescentar a função após `parse_serie`:

```python
def parse_carteira(raw_multiplex: dict, competencia: date | None = None) -> Carteira:
    """responseList[0].body -> [{ativo, participacao}] -> Carteira.

    participacao vem como string com ponto decimal; itens malformados são
    descartados (logados), no mesmo estilo de parse_serie.
    """
    body = _body_multiplex(raw_multiplex)
    if not body:
        return Carteira(competencia=competencia)
    try:
        itens = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return Carteira(competencia=competencia)
    posicoes: list[PosicaoCarteira] = []
    for item in itens:
        try:
            posicoes.append(
                PosicaoCarteira(nome=item["ativo"], participacao=float(item["participacao"]))
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(f"Posição de carteira ignorada ({item!r}): {exc}")
    return Carteira(competencia=competencia, posicoes=posicoes)
```

Garantir o import (linha de import dos schemas no topo do arquivo):

```python
from .schemas import (
    AtivoQuantum,
    Carteira,
    MetaACAO,
    MetaBase,
    MetaFI,
    MetaFII,
    MetaIndice,
    MetaRendaFixa,
    PontoSerie,
    PosicaoCarteira,
    ResultadoBusca,
    SerieDiaria,
)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `pytest tests/quantum/test_parsers.py::TestParseCarteira -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/quantum/parsers.py tests/quantum/test_parsers.py
git commit -m "feat(carteira): parse_carteira"
```

---

### Task 4: Método `QuantumClient.carteira`

**Files:**
- Modify: `scrapper/quantum/client.py`
- Test: `tests/quantum/test_client.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar ao fim de `tests/quantum/test_client.py`:

```python
class TestCarteira:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.post.return_value.status_code = 200
        self.c._client.post.return_value.json.return_value = {"responseList": [{"body": "[]"}]}

    def test_monta_relative_url_de_carteira(self):
        self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1))
        enviado = self.c._client.post.call_args.kwargs["content"]
        assert "/api/ativos/FI/612014/carteira" in enviado
        assert "tipoCarteira=INDIVIDUAL" in enviado
        assert "quantidade=100" in enviado
        assert "dataCompetencia=2026-04-01" in enviado

    def test_devolve_dict_cru(self):
        assert self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1)) == {
            "responseList": [{"body": "[]"}]
        }

    def test_erro_http_levanta_value_error(self):
        self.c._client.post.return_value.status_code = 500
        self.c._client.post.return_value.text = "erro"
        with pytest.raises(ValueError, match="500"):
            self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1))
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/quantum/test_client.py::TestCarteira -v`
Expected: FAIL — `AttributeError: 'QuantumClient' object has no attribute 'carteira'`.

- [ ] **Step 3: Implementar o método**

Em `scrapper/quantum/client.py`, após o método `serie`:

```python
def carteira(
    self, tipo: TipoAtivo, id_quantum: str, competencia: date,
    quantidade: int = 100, tipo_carteira: str = "INDIVIDUAL",
) -> dict:
    """Composição da carteira investida (FI) via multiplex /b. Dict cru.

    Endpoint REST `/api/ativos/{tipo}/{id}/carteira` — só FI retorna dados
    (FII vem vazio). Exige o Bearer token (já em _headers_api).
    """
    relative_url = (
        f"/api/ativos/{TipoAtivo(tipo).value}/{id_quantum}/carteira"
        f"?identificador={id_quantum}&tipoItemQuantum={TipoAtivo(tipo).value}"
        f"&tipoCarteira={tipo_carteira}"
        f"&dataCompetencia={competencia.strftime('%Y-%m-%d')}"
        f"&quantidade={quantidade}&exibirSomatorioOutros=true"
    )
    payload = json.dumps({
        "commonHeader": {
            "Content-Type": "application/json",
            "Accept-Language": "pt-BR",
            "x-Moeda": "BRL",
            "x-Retorno": "Fechamento",
        },
        "requests": [{
            "method": "GET",
            "headers": {},
            "body": "",
            "relativeUrl": relative_url,
        }],
    })
    response = self._client.post(self._API_URL, headers=self._headers_api(), content=payload)
    if response.status_code != 200:
        raise ValueError(f"{response.status_code=} {response.text}")
    return self._decode_json(response)
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `pytest tests/quantum/test_client.py::TestCarteira -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Validar contra a API real (manual)**

Com `.env` configurado, rodar um teste manual no shell para confirmar método/URL:

```bash
python -c "from datetime import date; from scrapper.quantum.client import QuantumClient; c=QuantumClient(); c.login(); import json; print(json.dumps(c.carteira('FI','612014',date.today().replace(day=1)), ensure_ascii=False)[:500])"
```
Expected: imprime `responseList` com `body` contendo uma lista `[{"ativo":...,"participacao":...}]` não-vazia. Se vier vazio/erro, ajustar `method` (tentar `POST`) ou recuar a competência (mês anterior) e reexecutar antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add scrapper/quantum/client.py tests/quantum/test_client.py
git commit -m "feat(carteira): QuantumClient.carteira"
```

---

### Task 5: Serviço `coletar_carteira`

**Files:**
- Modify: `scrapper/services.py`
- Test: `tests/test_services.py`

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_services.py`, adicionar o helper (junto dos `_multiplex_*` no topo):

```python
def _multiplex_carteira(itens: list) -> dict:
    return {"responseList": [{"body": json.dumps(itens)}]}
```

E a classe de teste (importar `CarteiraFundo` e `PosicaoCarteira` de `scrapper.models`):

```python
@pytest.mark.django_db
class TestColetarCarteira:
    def test_rejeita_tipo_nao_fi(self):
        client = MagicMock()
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FII", id_quantum="1", nome="FII X")
        with pytest.raises(ValueError, match="apenas para fundos"):
            svc.coletar_carteira(ativo)

    def test_persiste_posicoes(self):
        client = MagicMock()
        client.carteira.return_value = _multiplex_carteira([
            {"ativo": "LFT 2030", "participacao": "12.3"},
            {"ativo": "NTN-B 2028", "participacao": "9.8"},
        ])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")
        carteira = svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        assert carteira.posicoes.count() == 2
        assert carteira.posicoes.first().nome == "LFT 2030"
        assert carteira.posicoes.first().ordem == 0

    def test_upsert_substitui_posicoes_antigas(self):
        client = MagicMock()
        client.carteira.return_value = _multiplex_carteira([{"ativo": "A", "participacao": "1"}])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        client.carteira.return_value = _multiplex_carteira([
            {"ativo": "B", "participacao": "2"}, {"ativo": "C", "participacao": "3"},
        ])
        carteira = svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        assert CarteiraFundo.objects.filter(ativo=ativo).count() == 1
        assert [p.nome for p in carteira.posicoes.all()] == ["B", "C"]
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/test_services.py::TestColetarCarteira -v`
Expected: FAIL — `AttributeError: 'QuantumService' object has no attribute 'coletar_carteira'`.

- [ ] **Step 3: Implementar o serviço**

Em `scrapper/services.py`: importar `date` (já importado), `CarteiraFundo`, `PosicaoCarteira` de `scrapper.models`, e `PosicaoCarteira as PosicaoSchema` não é necessário. Adicionar o método à classe `QuantumService`, após `coletar_serie`:

```python
def coletar_carteira(self, ativo: Ativo, competencia: date | None = None) -> CarteiraFundo:
    """Coleta a composição da carteira do fundo (FI) e persiste por competência.

    Disponível apenas para FI; FII/Ação levantam ValueError. Idempotente por
    (ativo, competencia): substitui as posições anteriores.
    """
    if ativo.tipo != TipoAtivo.FI:
        raise ValueError("Carteira disponível apenas para fundos (FI).")
    if competencia is None:
        competencia = date.today().replace(day=1)
    self._ensure_login()
    raw = self._client.carteira(TipoAtivo(ativo.tipo), ativo.id_quantum, competencia)
    carteira_dom = parsers.parse_carteira(raw, competencia=competencia)
    with transaction.atomic():
        carteira, _ = CarteiraFundo.objects.update_or_create(
            ativo=ativo, competencia=competencia
        )
        carteira.posicoes.all().delete()
        PosicaoCarteira.objects.bulk_create([
            PosicaoCarteira(
                carteira=carteira, nome=p.nome, participacao=p.participacao, ordem=i
            )
            for i, p in enumerate(carteira_dom.posicoes)
        ])
    return carteira
```

Atualizar o import dos modelos no topo de `services.py`:

```python
from scrapper.models import Ativo, CarteiraFundo, CotacaoDiaria, PosicaoCarteira
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `pytest tests/test_services.py::TestColetarCarteira -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/services.py tests/test_services.py
git commit -m "feat(carteira): QuantumService.coletar_carteira"
```

---

### Task 6: Helper de gráfico `gerar_grafico_ativo_html`

**Files:**
- Modify: `scrapper/analise.py`
- Test: `tests/test_analise.py` (novo)

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_analise.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/test_analise.py -v`
Expected: FAIL — `ImportError: cannot import name 'gerar_grafico_ativo_html'`.

- [ ] **Step 3: Implementar o helper**

Em `scrapper/analise.py`, adicionar no fim do arquivo:

```python
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
```

- [ ] **Step 4: Rodar os testes e ver passar**

Run: `pytest tests/test_analise.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/analise.py tests/test_analise.py
git commit -m "feat(detalhe): gerar_grafico_ativo_html (Plotly base-100)"
```

---

### Task 7: View `detalhe_ativo` + rota + template mínimo

**Files:**
- Modify: `scrapper/views.py`, `scrapper/urls.py`
- Create: `scrapper/templates/scrapper/detalhe.html`
- Test: `tests/test_views.py`

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_views.py`, adicionar (importar `CarteiraFundo`, `PosicaoCarteira` de `scrapper.models`):

```python
@pytest.mark.django_db
class TestDetalheAtivo:
    def test_404_para_id_inexistente(self, client):
        assert client.get("/ativos/99999/").status_code == 404

    def test_200_e_contexto(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="1", nome="AMW")
        CotacaoDiaria.objects.create(ativo=a, data=date(2024, 1, 2), valor=100.0)
        CotacaoDiaria.objects.create(ativo=a, data=date(2024, 1, 3), valor=101.0)
        ctx = client.get(f"/ativos/{a.id}/").context
        assert ctx["ativo"].id == a.id
        assert ctx["num_cotas"] == 2
        assert ctx["pode_ter_carteira"] is True

    def test_acao_nao_pode_ter_carteira(self, client):
        a = Ativo.objects.create(tipo="ACAO", id_quantum="2", nome="PETR4")
        ctx = client.get(f"/ativos/{a.id}/").context
        assert ctx["pode_ter_carteira"] is False

    def test_carteira_atual_no_contexto(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="3", nome="X")
        c = CarteiraFundo.objects.create(ativo=a, competencia=date(2026, 4, 1))
        PosicaoCarteira.objects.create(carteira=c, nome="LFT", participacao=10.0, ordem=0)
        ctx = client.get(f"/ativos/{a.id}/").context
        assert ctx["carteira"].id == c.id
        assert ctx["carteira"].posicoes.count() == 1
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/test_views.py::TestDetalheAtivo -v`
Expected: FAIL — 404 (rota inexistente) na maioria dos casos / `Resolver404`.

- [ ] **Step 3: Implementar a view**

Em `scrapper/views.py`, importar o helper de gráfico e adicionar a view (após `ativos_list`):

```python
def detalhe_ativo(request, ativo_id):
    ativo = get_object_or_404(Ativo, id=ativo_id)

    agg = CotacaoDiaria.objects.filter(ativo=ativo).aggregate(
        num=Count("id"), primeira=Min("data"), ultima=Max("data")
    )
    valor_atual = (
        CotacaoDiaria.objects.filter(ativo=ativo).order_by("-data")
        .values_list("valor", flat=True).first()
    )

    serie = _serie_completa(ativo)
    from .analise import gerar_grafico_ativo_html
    grafico_html = gerar_grafico_ativo_html(ativo.nome, serie)

    carteira = (
        ativo.carteiras.prefetch_related("posicoes").first()
        if ativo.tipo == TipoAtivo.FI else None
    )

    return render(request, "scrapper/detalhe.html", {
        "ativo": ativo,
        "num_cotas": agg["num"],
        "primeira_cotacao": agg["primeira"],
        "ultima_cotacao": agg["ultima"],
        "valor_atual": valor_atual,
        "grafico_html": grafico_html,
        "pode_ter_carteira": ativo.tipo == TipoAtivo.FI,
        "carteira": carteira,
    })
```

Adicionar o import de `Min` em `views.py` (linha do django.db.models):

```python
from django.db.models import Count, Max, Min
```

E o helper `_serie_completa` (na seção Helpers, perto de `_serie_do_banco_range`):

```python
def _serie_completa(ativo: Ativo) -> pd.Series:
    pts = list(
        CotacaoDiaria.objects.filter(ativo=ativo)
        .values_list("data", "valor").order_by("data")
    )
    if not pts:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(d): v for d, v in pts}, name=ativo.nome)
```

- [ ] **Step 4: Adicionar a rota**

Em `scrapper/urls.py`, dentro de `urlpatterns`, após a linha de `ativos/`:

```python
    path("ativos/<int:ativo_id>/", views.detalhe_ativo, name="detalhe_ativo"),
```

- [ ] **Step 5: Criar o template mínimo**

Criar `scrapper/templates/scrapper/detalhe.html` (versão mínima só p/ a view responder; layout completo vem na Task 9):

```html
{% extends "scrapper/base.html" %}
{% block title %}{{ ativo.nome }} — Detalhes{% endblock %}
{% block content %}
<h4>{{ ativo.nome }}</h4>
<p class="text-muted">{{ ativo.tipo }} · {{ num_cotas }} cotações</p>
{% endblock %}
```

- [ ] **Step 6: Rodar os testes e ver passar**

Run: `pytest tests/test_views.py::TestDetalheAtivo -v`
Expected: PASS (4 testes).

- [ ] **Step 7: Commit**

```bash
git add scrapper/views.py scrapper/urls.py scrapper/templates/scrapper/detalhe.html tests/test_views.py
git commit -m "feat(detalhe): view detalhe_ativo + rota + template mínimo"
```

---

### Task 8: View `atualizar_carteira` + rota

**Files:**
- Modify: `scrapper/views.py`, `scrapper/urls.py`
- Test: `tests/test_views.py`

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_views.py`, adicionar:

```python
@pytest.mark.django_db
class TestAtualizarCarteira:
    def test_400_para_nao_fi(self, client):
        a = Ativo.objects.create(tipo="FII", id_quantum="1", nome="FII X")
        resp = client.post(f"/ativos/{a.id}/carteira/atualizar/")
        assert resp.status_code == 400

    def test_200_para_fi(self, client, monkeypatch):
        a = Ativo.objects.create(tipo="FI", id_quantum="2", nome="AMW")

        def fake_coletar(self, ativo, competencia=None):
            from scrapper.models import CarteiraFundo
            from datetime import date as d
            return CarteiraFundo.objects.create(ativo=ativo, competencia=d(2026, 4, 1))

        monkeypatch.setattr("scrapper.views.QuantumService.coletar_carteira", fake_coletar)
        resp = client.post(f"/ativos/{a.id}/carteira/atualizar/")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_erro_de_rede_502(self, client, monkeypatch):
        a = Ativo.objects.create(tipo="FI", id_quantum="3", nome="X")

        def fake_coletar(self, ativo, competencia=None):
            raise RuntimeError("falha de rede")

        monkeypatch.setattr("scrapper.views.QuantumService.coletar_carteira", fake_coletar)
        resp = client.post(f"/ativos/{a.id}/carteira/atualizar/")
        assert resp.status_code == 502
        assert "erro" in resp.json()
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/test_views.py::TestAtualizarCarteira -v`
Expected: FAIL — 404 (rota inexistente).

- [ ] **Step 3: Implementar a view**

Em `scrapper/views.py`, após `detalhe_ativo`:

```python
@require_POST
def atualizar_carteira(request, ativo_id):
    """Coleta sob demanda a carteira do fundo (FI) e persiste. Síncrono."""
    ativo = get_object_or_404(Ativo, id=ativo_id)
    if ativo.tipo != TipoAtivo.FI:
        return JsonResponse(
            {"erro": "Carteira disponível apenas para fundos (FI)."}, status=400
        )
    try:
        carteira = QuantumService().coletar_carteira(ativo)
    except ValueError as exc:
        return JsonResponse({"erro": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"erro": f"Falha ao coletar carteira: {exc}"}, status=502)
    return JsonResponse({
        "ok": True,
        "competencia": carteira.competencia.isoformat(),
        "posicoes": carteira.posicoes.count(),
    })
```

- [ ] **Step 4: Adicionar a rota**

Em `scrapper/urls.py`, após a rota de `detalhe_ativo`:

```python
    path("ativos/<int:ativo_id>/carteira/atualizar/", views.atualizar_carteira, name="atualizar_carteira"),
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `pytest tests/test_views.py::TestAtualizarCarteira -v`
Expected: PASS (3 testes).

- [ ] **Step 6: Commit**

```bash
git add scrapper/views.py scrapper/urls.py tests/test_views.py
git commit -m "feat(carteira): view atualizar_carteira + rota"
```

---

### Task 9: Template completo `detalhe.html`

**Files:**
- Modify: `scrapper/templates/scrapper/detalhe.html`

> Sem teste automatizado novo (template). Verificação é visual + os testes da view (Task 7/8) continuam passando.

- [ ] **Step 1: Substituir o template mínimo pelo completo**

Sobrescrever `scrapper/templates/scrapper/detalhe.html`:

```html
{% extends "scrapper/base.html" %}
{% block title %}{{ ativo.nome }} — Detalhes{% endblock %}
{% block nav_ativos %}fw-bold text-white{% endblock %}

{% block content %}
{% csrf_token %}

<!-- Cabeçalho -->
<div class="d-flex justify-content-between align-items-start mb-4 flex-wrap gap-2">
  <div>
    <div class="text-muted small"><a href="{% url 'ativos' %}" class="text-decoration-none">Ativos</a> › Detalhes</div>
    <h4 class="mb-0 mt-1">
      {{ ativo.nome }}
      {% if ativo.tipo == 'FI' %}<span class="badge tipo-fi">Fundo</span>
      {% elif ativo.tipo == 'FII' %}<span class="badge tipo-fii">FII</span>
      {% elif ativo.tipo == 'ACAO' %}<span class="badge tipo-acao">Ação</span>
      {% elif ativo.tipo == 'RENDA_FIXA' %}<span class="badge tipo-rf">Renda Fixa</span>
      {% else %}<span class="badge bg-secondary">{{ ativo.tipo }}</span>{% endif %}
    </h4>
  </div>
  <div class="d-flex gap-2">
    <a href="{% url 'ativos' %}" class="btn btn-sm btn-outline-secondary"><i class="bi bi-arrow-left me-1"></i>Voltar</a>
    <a href="{% url 'relatorio' %}?ids={{ ativo.id }}" target="_blank" class="btn btn-sm btn-dark"><i class="bi bi-bar-chart-line me-1"></i>Relatório</a>
    {% if num_cotas %}
    <a href="{% url 'exportar_cotas_excel' %}?ids={{ ativo.id }}" class="btn btn-sm btn-success"><i class="bi bi-file-earmark-excel me-1"></i>Cotas</a>
    {% endif %}
    <button class="btn btn-sm btn-outline-danger" id="btn-excluir" data-id="{{ ativo.id }}"><i class="bi bi-trash"></i></button>
  </div>
</div>

<!-- Estatísticas -->
<div class="row g-3 mb-4">
  <div class="col-6 col-lg-4">
    <div class="card h-100"><div class="card-body py-3">
      <div class="resumo-label">Cotações</div>
      <div class="fs-3 fw-bold text-primary">{{ num_cotas }}</div>
    </div></div>
  </div>
  <div class="col-6 col-lg-4">
    <div class="card h-100"><div class="card-body py-3">
      <div class="resumo-label">Período coberto</div>
      <div class="fw-semibold mt-1">
        {% if primeira_cotacao %}{{ primeira_cotacao|date:"d/m/Y" }} → {{ ultima_cotacao|date:"d/m/Y" }}{% else %}—{% endif %}
      </div>
    </div></div>
  </div>
  <div class="col-12 col-lg-4">
    <div class="card h-100"><div class="card-body py-3">
      <div class="resumo-label">Valor base-100 atual</div>
      <div class="fs-3 fw-bold text-success">{% if valor_atual %}{{ valor_atual|floatformat:2 }}{% else %}—{% endif %}</div>
    </div></div>
  </div>
</div>

<div class="row g-3 mb-4">
  <!-- Ficha -->
  <div class="col-lg-4">
    <div class="card h-100"><div class="card-body">
      <div class="secao-titulo mb-3">Ficha do ativo</div>
      <table class="table table-sm ficha mb-0">
        <tr><td class="text-muted">CNPJ</td><td class="text-end font-monospace">{{ ativo.cnpj|default:"—" }}</td></tr>
        <tr><td class="text-muted">Ticker</td><td class="text-end">{{ ativo.ticker|default:"—" }}</td></tr>
        <tr><td class="text-muted">Gestora</td><td class="text-end">{{ ativo.gestora|default:"—" }}</td></tr>
        <tr><td class="text-muted">Setor</td><td class="text-end">{{ ativo.setor|default:"—" }}</td></tr>
        <tr><td class="text-muted">1ª cota</td><td class="text-end">{% if ativo.primeira_cota %}{{ ativo.primeira_cota|date:"d/m/Y" }}{% else %}—{% endif %}</td></tr>
        <tr><td class="text-muted">ID Quantum</td><td class="text-end font-monospace">{{ ativo.id_quantum }}</td></tr>
        <tr><td class="text-muted">Atualizado</td><td class="text-end">{{ ativo.atualizado_em|date:"d/m/Y H:i" }}</td></tr>
      </table>
      {% if ativo.metadados %}
      <button class="btn btn-sm btn-link px-0 mt-2" data-bs-toggle="collapse" data-bs-target="#meta-extra">
        <i class="bi bi-chevron-down me-1"></i>Metadados extras
      </button>
      <div class="collapse" id="meta-extra">
        <pre class="small bg-light p-2 rounded mb-0" style="max-height:240px;overflow:auto">{{ ativo.metadados }}</pre>
      </div>
      {% endif %}
    </div></div>
  </div>

  <!-- Gráfico -->
  <div class="col-lg-8">
    <div class="card h-100"><div class="card-body">
      <div class="secao-titulo mb-3">Evolução das cotas (Base 100)</div>
      {% if grafico_html %}
        {{ grafico_html|safe }}
      {% else %}
        <div class="text-center text-muted py-5">
          <i class="bi bi-graph-up fs-1 d-block mb-3 opacity-50"></i>
          Sem cotações para este ativo. Rode o scrap no
          <a href="{% url 'index' %}">Dashboard</a> para ver a evolução.
        </div>
      {% endif %}
    </div></div>
  </div>
</div>

<!-- Carteira do fundo -->
<div class="card mb-4"><div class="card-body">
  <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
    <div class="secao-titulo mb-0">
      Carteira do fundo
      {% if carteira %}<span class="text-muted fw-normal small">· competência {{ carteira.competencia|date:"m/Y" }} · {{ carteira.posicoes.count }} posições · importada {{ carteira.importada_em|date:"d/m H:i" }}</span>{% endif %}
    </div>
    {% if pode_ter_carteira %}
    <button class="btn btn-sm btn-primary" id="btn-carteira">
      <i class="bi bi-arrow-repeat me-1"></i>{% if carteira %}Atualizar carteira{% else %}Buscar carteira{% endif %}
    </button>
    {% endif %}
  </div>

  {% if not pode_ter_carteira %}
    <p class="text-muted mb-0"><i class="bi bi-info-circle me-1"></i>Composição de carteira disponível apenas para fundos (FI).</p>
  {% elif carteira %}
    <div class="table-responsive">
      <table class="table table-sm table-hover align-middle mb-0">
        <thead class="table-light"><tr><th>Posição</th><th class="text-end" style="width:160px">Participação</th></tr></thead>
        <tbody>
          {% for p in carteira.posicoes.all %}
          <tr>
            <td>{{ p.nome }}</td>
            <td class="text-end fw-semibold">{{ p.participacao|floatformat:2 }}%</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% else %}
    <p class="text-muted mb-0">Nenhuma carteira importada ainda. Clique em <strong>Buscar carteira</strong>.</p>
  {% endif %}
</div></div>

<!-- Modal de confirmação de exclusão -->
<div class="modal fade" id="modal-excluir" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered"><div class="modal-content">
    <div class="modal-header">
      <h6 class="modal-title"><i class="bi bi-exclamation-triangle text-danger me-2"></i>Excluir ativo</h6>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body">
      <p class="mb-2">Excluir <strong>{{ ativo.nome }}</strong>?</p>
      <p class="text-muted small mb-0">{% if num_cotas %}Isso também apagará {{ num_cotas }} cotação(ões). {% endif %}Esta ação não pode ser desfeita.</p>
    </div>
    <div class="modal-footer">
      <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Cancelar</button>
      <button type="button" class="btn btn-danger btn-sm" id="btn-confirmar-excluir"><i class="bi bi-trash me-1"></i>Excluir</button>
    </div>
  </div></div>
</div>
{% endblock %}

{% block scripts %}
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
(function () {
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;

  // Atualizar/buscar carteira (síncrono; recarrega ao concluir)
  const btnCarteira = document.getElementById("btn-carteira");
  btnCarteira?.addEventListener("click", async () => {
    const original = btnCarteira.innerHTML;
    btnCarteira.disabled = true;
    btnCarteira.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Buscando…';
    try {
      const resp = await fetch(`/ativos/{{ ativo.id }}/carteira/atualizar/`, {
        method: "POST", headers: { "X-CSRFToken": csrf },
      });
      if (resp.ok) { location.reload(); return; }
      const data = await resp.json().catch(() => ({}));
      alert(data.erro || "Falha ao buscar carteira.");
    } catch (e) {
      alert("Falha ao buscar carteira.");
    }
    btnCarteira.disabled = false;
    btnCarteira.innerHTML = original;
  });

  // Excluir (redireciona para a lista ao concluir)
  const modal = new bootstrap.Modal(document.getElementById("modal-excluir"));
  const btnConfirmar = document.getElementById("btn-confirmar-excluir");
  document.getElementById("btn-excluir")?.addEventListener("click", () => modal.show());
  btnConfirmar?.addEventListener("click", async () => {
    btnConfirmar.disabled = true;
    try {
      const resp = await fetch(`/ativos/{{ ativo.id }}/excluir/`, {
        method: "POST", headers: { "X-CSRFToken": csrf },
      });
      if (resp.ok) { window.location.href = "{% url 'ativos' %}"; return; }
    } catch (e) { /* cai no reset abaixo */ }
    btnConfirmar.disabled = false;
  });
})();
</script>

<style>
  .secao-titulo { font-weight:700; font-size:.95rem; border-left:3px solid #0d6efd; padding-left:10px; }
  .resumo-label { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:#6c757d; }
  .ficha td { padding:.4rem .25rem; }
  .badge.tipo-fi  { background:#0d6efd; }
  .badge.tipo-fii { background:#0dcaf0; color:#04323a; }
  .badge.tipo-acao{ background:#198754; }
  .badge.tipo-rf  { background:#6f42c1; }
</style>
{% endblock %}
```

- [ ] **Step 2: Rodar os testes da view e ver passar**

Run: `pytest tests/test_views.py::TestDetalheAtivo tests/test_views.py::TestAtualizarCarteira -v`
Expected: PASS (continuam verdes; o template renderiza com o contexto).

- [ ] **Step 3: Verificação visual manual**

Run: `python manage.py runserver` e abrir `/ativos/<id>/` de um FI com cotações.
Expected: cabeçalho, stats, ficha, gráfico Plotly interativo e seção de carteira (botão "Buscar carteira" se vazia).

- [ ] **Step 4: Commit**

```bash
git add scrapper/templates/scrapper/detalhe.html
git commit -m "feat(detalhe): template completo da tela de detalhes"
```

---

### Task 10: Linha clicável em `ativos.html`

**Files:**
- Modify: `scrapper/templates/scrapper/ativos.html`

> Sem teste automatizado (comportamento de JS no template). Verificação é manual.

- [ ] **Step 1: Marcar a linha com a URL de destino e cursor**

Em `scrapper/templates/scrapper/ativos.html`, na abertura da `<tr class="ativo-row" ...>` (linha ~93), adicionar `data-url` e a classe de cursor:

De:
```html
        <tr class="ativo-row"
            data-grupo="..."
            data-busca="...">
```
Para (acrescentar `data-url` usando a rota nova):
```html
        <tr class="ativo-row linha-clicavel"
            data-url="{% url 'detalhe_ativo' ativo.id %}"
            data-grupo="..."
            data-busca="...">
```
(Manter os valores de `data-grupo` e `data-busca` exatamente como já estão.)

- [ ] **Step 2: Garantir que a célula de ações não dispare a navegação**

Na `<td class="text-end pe-3 text-nowrap">` das ações (linha ~125), adicionar a classe `td-acoes`:
```html
          <td class="text-end pe-3 text-nowrap td-acoes">
```

- [ ] **Step 3: Adicionar o handler de clique no bloco de scripts**

Em `ativos.html`, dentro do IIFE `(function () { ... })();` (antes do `aplicarFiltros();` final), adicionar:

```javascript
  // ── Navegação para a tela de detalhes ─────────────────────────────────
  document.querySelectorAll(".linha-clicavel").forEach(tr => {
    tr.addEventListener("click", (e) => {
      // Ignora cliques nos botões/links de ação da última coluna.
      if (e.target.closest(".td-acoes")) return;
      const url = tr.dataset.url;
      if (url) window.location.href = url;
    });
  });
```

- [ ] **Step 4: Adicionar o cursor no bloco `<style>`**

No `<style>` de `ativos.html`, adicionar:
```css
  .linha-clicavel { cursor: pointer; }
```

- [ ] **Step 5: Verificação visual manual**

Run: `python manage.py runserver`, abrir `/ativos/`.
Expected: clicar na linha (fora dos botões) navega para `/ativos/<id>/`; clicar nos botões de ação (relatório, excel, copiar, excluir) continua funcionando sem navegar.

- [ ] **Step 6: Rodar toda a suíte**

Run: `pytest`
Expected: todos os testes passam (suíte anterior + novos).

- [ ] **Step 7: Commit**

```bash
git add scrapper/templates/scrapper/ativos.html
git commit -m "feat(ativos): linha da tabela navega para a tela de detalhes"
```

---

## Resumo de cobertura do spec

| Requisito do spec | Task |
|---|---|
| Modelos `CarteiraFundo` + `PosicaoCarteira` + migração | 1 |
| Schemas pydantic da carteira | 2 |
| `parse_carteira` | 3 |
| `client.carteira` (+ verificação contra API real) | 4 |
| `coletar_carteira` (valida FI, upsert por competência) | 5 |
| Gráfico Plotly base-100 (padrão `analise.py`) | 6 |
| View `detalhe_ativo` + rota + ficha/stats/gráfico/carteira no contexto | 7, 9 |
| View `atualizar_carteira` síncrona (FI; 400/502) | 8 |
| Template completo (cabeçalho, stats, ficha, gráfico, carteira, estados) | 9 |
| Estados: sem cotações / sem carteira / não-FI | 9 |
| Excluir pela página → redireciona à lista | 9 |
| Linha clicável em `ativos.html` (ignora botões de ação) | 10 |
```
