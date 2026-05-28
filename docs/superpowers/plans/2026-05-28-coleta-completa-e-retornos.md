# Coleta automática desde a primeira cota + retornos persistidos — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ao adicionar um ativo, coletar automaticamente a série diária da primeira cota até hoje e persistir cota + retorno diário (simples e log) em precisão Decimal.

**Architecture:** `valor`/`retorno`/`retorno_ln` viram `DecimalField` em `CotacaoDiaria`. Uma função pura `calcular_retornos_serie` computa os retornos de uma série de Decimals; `recalcular_retornos(ativo)` aplica isso à série inteira do ativo no banco após cada upsert de cotas. `coletar_serie_completa` ancora a coleta na `primeira_cota` (piso `2000-01-01`) e é disparada nos dois fluxos de adição. A fronteira Decimal↔float fica nos pontos onde o banco vira `pd.Series`.

**Tech Stack:** Python 3.11, Django 5, pandas/numpy, pytest + pytest-django, loguru, `decimal` (stdlib).

---

## Arquivos afetados

- Modify: `scrapper/models.py` — campos Decimal em `CotacaoDiaria`.
- Create: `scrapper/migrations/0006_cotacao_decimal_e_retornos.py` — schema + backfill.
- Modify: `scrapper/services.py` — `calcular_retornos_serie`, `recalcular_retornos`, `coletar_serie` (Decimal + recálculo), `coletar_serie_completa`.
- Modify: `scrapper/views.py` — disparo da coleta em `adicionar_ativo` e `buscar_ativos`; cast float em `_serie_completa`, `_serie_do_banco_range`, `exportar_cotas_excel`.
- Modify: `tests/test_models.py`, `tests/test_services.py`, `tests/test_views.py`.

Convenção de teste do projeto: `@pytest.mark.django_db`, client mockado via `MagicMock`, threads tornadas síncronas com `_SyncThread`, `QuantumService` injetado/patchado.

---

## Task 1: Campos Decimal em `CotacaoDiaria`

**Files:**
- Modify: `scrapper/models.py:46-62`
- Test: `tests/test_models.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicione ao final de `tests/test_models.py`:

```python
from decimal import Decimal

import pytest

from scrapper.models import Ativo, CotacaoDiaria


@pytest.mark.django_db
class TestCotacaoDiariaDecimal:
    def test_valor_aceita_decimal_e_retornos_default_zero(self):
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        c = CotacaoDiaria.objects.create(
            ativo=ativo, data="2024-01-02", valor=Decimal("100.12345678")
        )
        c.refresh_from_db()
        assert c.valor == Decimal("100.12345678")
        assert c.retorno == Decimal("0")
        assert c.retorno_ln == Decimal("0")
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest tests/test_models.py::TestCotacaoDiariaDecimal -v`
Expected: FAIL — `CotacaoDiaria` não tem `retorno`/`retorno_ln` (AttributeError/FieldError) ou `valor` rejeita Decimal.

- [ ] **Step 3: Alterar o modelo**

Em `scrapper/models.py`, substitua o corpo de `CotacaoDiaria` (campos) por:

```python
class CotacaoDiaria(models.Model):
    """Série de valor base-100 por ativo e data, com retorno diário persistido."""

    ativo = models.ForeignKey(
        Ativo, on_delete=models.CASCADE, related_name="cotacoes"
    )
    data = models.DateField(db_index=True)
    # Índice canônico base-100 ancorado na primeira cota do ativo.
    valor = models.DecimalField(max_digits=20, decimal_places=8)
    # Retornos diários NÃO acumulados; primeiro ponto da série = 0 (sem anterior).
    retorno = models.DecimalField(max_digits=18, decimal_places=12, default=0)
    retorno_ln = models.DecimalField(max_digits=18, decimal_places=12, default=0)

    class Meta:
        ordering = ["data"]
        unique_together = [("ativo", "data")]
        verbose_name = "Cotação Diária"
        verbose_name_plural = "Cotações Diárias"

    def __str__(self):
        return f"{self.ativo.nome} {self.data}: {self.valor:.4f}"
```

- [ ] **Step 4: Gerar a migração de schema**

Run: `python manage.py makemigrations scrapper`
Expected: cria `scrapper/migrations/0006_*.py` com `AlterField(valor)`, `AddField(retorno)`, `AddField(retorno_ln)`. Renomeie o arquivo para `0006_cotacao_decimal_e_retornos.py` (mantenha o `name=` em `Migration` coerente; o nome do arquivo é o que importa).

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `pytest tests/test_models.py::TestCotacaoDiariaDecimal -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapper/models.py scrapper/migrations/0006_cotacao_decimal_e_retornos.py tests/test_models.py
git commit -m "feat(cotacao): valor/retorno/retorno_ln em DecimalField

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `calcular_retornos_serie` (função pura)

**Files:**
- Modify: `scrapper/services.py` (novo bloco de funções no topo, após os imports)
- Test: `tests/test_services.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicione em `tests/test_services.py` (no topo, ajuste o import existente de `services`):

```python
from decimal import Decimal

from scrapper.services import calcular_retornos_serie


class TestCalcularRetornosSerie:
    def test_serie_vazia(self):
        assert calcular_retornos_serie([]) == []

    def test_primeiro_ponto_zero(self):
        r = calcular_retornos_serie([Decimal("100")])
        assert r == [(Decimal(0), Decimal(0))]

    def test_retorno_simples_e_log(self):
        r = calcular_retornos_serie([Decimal("100"), Decimal("110")])
        assert r[0] == (Decimal(0), Decimal(0))
        retorno, retorno_ln = r[1]
        assert retorno == Decimal("0.1")  # 110/100 - 1
        # ln(1.1) ≈ 0.0953101798...
        assert abs(retorno_ln - Decimal("0.09531017980432486")) < Decimal("1e-15")

    def test_valor_anterior_zero_nao_quebra(self):
        r = calcular_retornos_serie([Decimal("0"), Decimal("100")])
        assert r == [(Decimal(0), Decimal(0)), (Decimal(0), Decimal(0))]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_services.py::TestCalcularRetornosSerie -v`
Expected: FAIL — `ImportError: cannot import name 'calcular_retornos_serie'`.

- [ ] **Step 3: Implementar a função pura**

Em `scrapper/services.py`, adicione o import e a função (após os imports, antes de `class QuantumService`):

```python
from decimal import Decimal, localcontext
```

```python
def calcular_retornos_serie(valores: list[Decimal]) -> list[tuple[Decimal, Decimal]]:
    """Retornos diários (simples e log) de uma série ordenada de valores.

    Função pura (sem ORM/rede). O primeiro ponto e qualquer ponto cujo anterior
    seja zero recebem (0, 0). Usa contexto Decimal de alta precisão para o ln.
    """
    resultado: list[tuple[Decimal, Decimal]] = []
    anterior: Decimal | None = None
    with localcontext() as ctx:
        ctx.prec = 50
        for valor in valores:
            if anterior is None or anterior == 0:
                resultado.append((Decimal(0), Decimal(0)))
            else:
                razao = valor / anterior
                resultado.append((razao - 1, razao.ln()))
            anterior = valor
    return resultado
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_services.py::TestCalcularRetornosSerie -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/services.py tests/test_services.py
git commit -m "feat(services): calcular_retornos_serie (retorno simples e log em Decimal)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `recalcular_retornos(ativo)`

**Files:**
- Modify: `scrapper/services.py` (nova função de módulo, após `calcular_retornos_serie`)
- Test: `tests/test_services.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicione em `tests/test_services.py`:

```python
from scrapper.models import CotacaoDiaria
from scrapper.services import recalcular_retornos


@pytest.mark.django_db
class TestRecalcularRetornos:
    def _ativo_com_serie(self, valores):
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        for i, v in enumerate(valores, start=2):
            CotacaoDiaria.objects.create(
                ativo=ativo, data=f"2024-01-{i:02d}", valor=Decimal(v)
            )
        return ativo

    def test_grava_retornos_da_serie(self):
        ativo = self._ativo_com_serie(["100", "110", "121"])
        n = recalcular_retornos(ativo)
        assert n == 3
        cotas = list(ativo.cotacoes.order_by("data"))
        assert cotas[0].retorno == Decimal("0")
        assert cotas[1].retorno == Decimal("0.1")
        assert cotas[2].retorno == Decimal("0.1")  # 121/110 - 1

    def test_idempotente(self):
        ativo = self._ativo_com_serie(["100", "110"])
        recalcular_retornos(ativo)
        antes = [(c.retorno, c.retorno_ln) for c in ativo.cotacoes.order_by("data")]
        recalcular_retornos(ativo)
        depois = [(c.retorno, c.retorno_ln) for c in ativo.cotacoes.order_by("data")]
        assert antes == depois

    def test_sem_cotas_retorna_zero(self):
        ativo = Ativo.objects.create(tipo="FI", id_quantum="2", nome="Y")
        assert recalcular_retornos(ativo) == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_services.py::TestRecalcularRetornos -v`
Expected: FAIL — `ImportError: cannot import name 'recalcular_retornos'`.

- [ ] **Step 3: Implementar**

Em `scrapper/services.py`, após `calcular_retornos_serie`:

```python
def recalcular_retornos(ativo: "Ativo") -> int:
    """Recomputa retorno/retorno_ln da série inteira do ativo a partir de `valor`.

    Idempotente. Lê a série ordenada por data, delega o cálculo a
    `calcular_retornos_serie` e grava via bulk_update. Devolve o nº de cotas.
    """
    cotacoes = list(CotacaoDiaria.objects.filter(ativo=ativo).order_by("data"))
    if not cotacoes:
        return 0
    retornos = calcular_retornos_serie([c.valor for c in cotacoes])
    for cotacao, (retorno, retorno_ln) in zip(cotacoes, retornos):
        cotacao.retorno = retorno
        cotacao.retorno_ln = retorno_ln
    CotacaoDiaria.objects.bulk_update(cotacoes, ["retorno", "retorno_ln"])
    return len(cotacoes)
```

Obs.: `CotacaoDiaria` já está importado no topo de `services.py`.

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_services.py::TestRecalcularRetornos -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/services.py tests/test_services.py
git commit -m "feat(services): recalcular_retornos recomputa a série inteira do ativo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `coletar_serie` persiste Decimal e dispara o recálculo

**Files:**
- Modify: `scrapper/services.py:93-111` (método `coletar_serie`)
- Test: `tests/test_services.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicione em `tests/test_services.py`, dentro da classe `TestColetarSerie` existente:

```python
    def test_persiste_decimal_e_calcula_retornos(self):
        from decimal import Decimal
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([
            ("2024-01-02", "100.0"), ("2024-01-03", "110.0"),
        ])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="9", nome="Z")
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        cotas = list(ativo.cotacoes.order_by("data"))
        assert isinstance(cotas[0].valor, Decimal)
        assert cotas[0].retorno == Decimal("0")
        assert cotas[1].retorno == Decimal("0.1")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest "tests/test_services.py::TestColetarSerie::test_persiste_decimal_e_calcula_retornos" -v`
Expected: FAIL — `retorno` é `Decimal("0")` para o 2º ponto (recálculo ainda não chamado) ou `valor` não é Decimal.

- [ ] **Step 3: Implementar**

Substitua o método `coletar_serie` em `scrapper/services.py` por:

```python
    def coletar_serie(self, ativo: Ativo, data_inicio: date, data_fim: date) -> int:
        """Coleta a série diária do ativo, faz upsert de `valor` (Decimal) e
        recomputa os retornos da série inteira."""
        self._ensure_login()
        di = ativo.primeira_cota if (ativo.primeira_cota and ativo.primeira_cota > data_inicio) else data_inicio
        raw = self._client.serie(TipoAtivo(ativo.tipo), ativo.id_quantum, di, data_fim)
        serie = parsers.parse_serie(raw)
        if not serie.pontos:
            return 0
        objs = [
            CotacaoDiaria(ativo=ativo, data=p.data, valor=Decimal(str(p.valor)))
            for p in serie.pontos
        ]
        with transaction.atomic():
            CotacaoDiaria.objects.bulk_create(
                objs,
                update_conflicts=True,
                unique_fields=["ativo", "data"],
                update_fields=["valor"],
            )
            recalcular_retornos(ativo)
        return len(objs)
```

Obs.: `transaction` já está importado no topo de `services.py`.

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_services.py::TestColetarSerie -v`
Expected: PASS (todos os testes da classe, incluindo os antigos).

- [ ] **Step 5: Commit**

```bash
git add scrapper/services.py tests/test_services.py
git commit -m "feat(services): coletar_serie grava Decimal e recomputa retornos

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Backfill na migração

**Files:**
- Modify: `scrapper/migrations/0006_cotacao_decimal_e_retornos.py`

A migração de schema da Task 1 já adicionou as colunas com `default=0`. Agora acrescentamos o backfill dos retornos das cotas pré-existentes na MESMA migração (roda após as operações de campo).

- [ ] **Step 1: Adicionar o backfill à migração**

No topo de `scrapper/migrations/0006_cotacao_decimal_e_retornos.py`, adicione os imports e a função (a lógica espelha `calcular_retornos_serie`; migrações de dados são auto-contidas por convenção Django):

```python
from decimal import Decimal, localcontext


def _backfill_retornos(apps, schema_editor):
    Ativo = apps.get_model("scrapper", "Ativo")
    CotacaoDiaria = apps.get_model("scrapper", "CotacaoDiaria")
    for ativo_id in Ativo.objects.values_list("id", flat=True):
        cotacoes = list(
            CotacaoDiaria.objects.filter(ativo_id=ativo_id).order_by("data")
        )
        if not cotacoes:
            continue
        anterior = None
        with localcontext() as ctx:
            ctx.prec = 50
            for cotacao in cotacoes:
                if anterior is None or anterior == 0:
                    cotacao.retorno = Decimal(0)
                    cotacao.retorno_ln = Decimal(0)
                else:
                    razao = cotacao.valor / anterior
                    cotacao.retorno = razao - 1
                    cotacao.retorno_ln = razao.ln()
                anterior = cotacao.valor
        CotacaoDiaria.objects.bulk_update(cotacoes, ["retorno", "retorno_ln"])


def _noop(apps, schema_editor):
    pass
```

Em seguida, adicione ao final da lista `operations` da `Migration`:

```python
        migrations.RunPython(_backfill_retornos, _noop),
```

- [ ] **Step 2: Verificar que a migração aplica sem erro**

Run: `python manage.py migrate scrapper`
Expected: aplica `0006_cotacao_decimal_e_retornos` sem erro. (Se já aplicada, reverta com `python manage.py migrate scrapper 0005` e reaplique para exercitar o backfill.)

- [ ] **Step 3: Verificar a suíte completa**

Run: `pytest -q`
Expected: todos os testes passam (o banco de teste recria as migrações do zero).

- [ ] **Step 4: Commit**

```bash
git add scrapper/migrations/0006_cotacao_decimal_e_retornos.py
git commit -m "feat(migration): backfill de retorno/retorno_ln das cotas existentes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `coletar_serie_completa(ativo)`

**Files:**
- Modify: `scrapper/services.py` (novo método em `QuantumService`, após `coletar_serie`)
- Test: `tests/test_services.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicione em `tests/test_services.py`:

```python
@pytest.mark.django_db
class TestColetarSerieCompleta:
    def test_usa_primeira_cota_como_inicio(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([("2021-09-10", "100.0")])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(
            tipo="FI", id_quantum="1", nome="X", primeira_cota=date(2021, 9, 10),
        )
        svc.coletar_serie_completa(ativo)
        di_chamado = client.serie.call_args[0][2]
        assert di_chamado == date(2021, 9, 10)

    def test_sem_primeira_cota_usa_piso_2000(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="RENDA_FIXA", id_quantum="VALE38", nome="V")
        svc.coletar_serie_completa(ativo)
        di_chamado = client.serie.call_args[0][2]
        assert di_chamado == date(2000, 1, 1)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_services.py::TestColetarSerieCompleta -v`
Expected: FAIL — `AttributeError: 'QuantumService' object has no attribute 'coletar_serie_completa'`.

- [ ] **Step 3: Implementar**

Em `scrapper/services.py`, dentro de `QuantumService`, logo após `coletar_serie`:

```python
    def coletar_serie_completa(self, ativo: Ativo) -> int:
        """Coleta a série da primeira cota (ou piso 2000-01-01) até hoje."""
        data_inicio = ativo.primeira_cota or date(2000, 1, 1)
        return self.coletar_serie(ativo, data_inicio, date.today())
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_services.py::TestColetarSerieCompleta -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add scrapper/services.py tests/test_services.py
git commit -m "feat(services): coletar_serie_completa (primeira_cota -> hoje, piso 2000)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Disparar a coleta ao adicionar ativo (views)

**Files:**
- Modify: `scrapper/views.py` — import do logger; `adicionar_ativo._run` (linhas ~356-363); `buscar_ativos._run` (linhas ~253-262)
- Test: `tests/test_views.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicione em `tests/test_views.py`:

```python
@pytest.mark.django_db
class TestAdicionarAtivoColeta:
    def _setup(self, monkeypatch):
        fake = MagicMock()
        fake.importar_ativos.return_value = [
            Ativo(tipo="FI", id_quantum="612014", nome="AMW")
        ]
        monkeypatch.setattr("scrapper.views.QuantumService", lambda: fake)
        monkeypatch.setattr("scrapper.views.threading.Thread", _SyncThread)
        return fake

    def test_coleta_serie_completa_apos_importar(self, client, monkeypatch):
        fake = self._setup(monkeypatch)
        resp = client.post("/adicionar-ativo/", {
            "id_quantum": "612014", "tipo": "FI", "nome": "AMW",
        })
        assert resp.status_code == 200
        fake.coletar_serie_completa.assert_called_once()

    def test_falha_na_coleta_nao_derruba_job(self, client, monkeypatch):
        fake = self._setup(monkeypatch)
        fake.coletar_serie_completa.side_effect = RuntimeError("boom")
        resp = client.post("/adicionar-ativo/", {
            "id_quantum": "612014", "tipo": "FI", "nome": "AMW",
        })
        job_id = resp.json()["job_id"]
        job = Job.objects.get(id=job_id)
        assert job.status == "done"  # ativo importado mesmo com coleta falha


@pytest.mark.django_db
class TestBuscarAtivosColeta:
    def test_coleta_cada_ativo_importado(self, client, monkeypatch, tmp_path):
        import pandas as pd
        fake = MagicMock()
        fake.buscar_por_cnpj.return_value = ["r"]
        fake.importar_ativos.return_value = [
            Ativo(tipo="FI", id_quantum="1", nome="A")
        ]
        monkeypatch.setattr("scrapper.views.QuantumService", lambda: fake)
        monkeypatch.setattr("scrapper.views.threading.Thread", _SyncThread)

        xlsx = tmp_path / "ativos.xlsx"
        pd.DataFrame({"cnpj": ["42550188000191"]}).to_excel(xlsx, index=False)
        with open(xlsx, "rb") as fh:
            resp = client.post("/buscar/", {"arquivo": fh})
        assert resp.status_code == 200
        fake.coletar_serie_completa.assert_called_once()
```

Paths confirmados em `scrapper/urls.py`: `adicionar_ativo` → `/adicionar-ativo/`; `buscar_ativos` → `/buscar/`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_views.py::TestAdicionarAtivoColeta tests/test_views.py::TestBuscarAtivosColeta -v`
Expected: FAIL — `coletar_serie_completa` nunca é chamado (`AssertionError: Expected 'coletar_serie_completa' to have been called once`).

- [ ] **Step 3: Adicionar o import do logger**

No bloco de imports de `scrapper/views.py`, adicione:

```python
from loguru import logger
```

- [ ] **Step 4: Disparar a coleta em `adicionar_ativo`**

Em `scrapper/views.py`, dentro de `adicionar_ativo._run`, substitua:

```python
            ativo = QuantumService().importar_ativos([resultado])[0]
            job.status = "done"
            job.detalhe = f"Ativo '{ativo.nome}' adicionado"
```

por:

```python
            service = QuantumService()
            ativo = service.importar_ativos([resultado])[0]
            try:
                service.coletar_serie_completa(ativo)
            except Exception as exc:  # coleta de cotas não derruba a importação
                logger.warning(f"Falha ao coletar cotas de {ativo.nome}: {exc}")
            job.status = "done"
            job.detalhe = f"Ativo '{ativo.nome}' adicionado"
```

- [ ] **Step 5: Disparar a coleta em `buscar_ativos`**

Em `scrapper/views.py`, dentro de `buscar_ativos._run`, substitua:

```python
                if resultados:
                    service.importar_ativos(resultados[:1])  # 1º candidato
                    total += 1
```

por:

```python
                if resultados:
                    for ativo in service.importar_ativos(resultados[:1]):  # 1º candidato
                        try:
                            service.coletar_serie_completa(ativo)
                        except Exception as exc:  # coleta não derruba o lote
                            logger.warning(
                                f"Falha ao coletar cotas de {ativo.nome}: {exc}"
                            )
                    total += 1
```

- [ ] **Step 6: Rodar e ver passar**

Run: `pytest tests/test_views.py::TestAdicionarAtivoColeta tests/test_views.py::TestBuscarAtivosColeta -v`
Expected: PASS (3 testes).

- [ ] **Step 7: Commit**

```bash
git add scrapper/views.py tests/test_views.py
git commit -m "feat(views): coleta automática da série ao adicionar ativo (individual e lote)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Fronteira Decimal→float (pandas)

**Files:**
- Modify: `scrapper/views.py:24-42` (`_serie_do_banco_range`, `_serie_completa`), `scrapper/views.py:566-574` (`exportar_cotas_excel`)
- Test: `tests/test_views.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicione em `tests/test_views.py`:

```python
@pytest.mark.django_db
class TestSerieFloat:
    def test_serie_completa_dtype_float(self):
        from decimal import Decimal
        import numpy as np
        from scrapper.models import CotacaoDiaria
        from scrapper.views import _serie_completa
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        CotacaoDiaria.objects.create(ativo=ativo, data="2024-01-02", valor=Decimal("100.5"))
        serie = _serie_completa(ativo)
        assert serie.dtype == np.float64
        assert serie.iloc[0] == 100.5
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_views.py::TestSerieFloat -v`
Expected: FAIL — `serie.dtype` é `object` (Decimal), não `float64`.

- [ ] **Step 3: Cast para float nos pontos de montagem da Series**

Em `scrapper/views.py`, em `_serie_do_banco_range`, troque:

```python
    return pd.Series({pd.Timestamp(d): v for d, v in cotacoes}, name=ativo.nome)
```

por:

```python
    return pd.Series({pd.Timestamp(d): float(v) for d, v in cotacoes}, name=ativo.nome)
```

Em `_serie_completa`, troque:

```python
    return pd.Series({pd.Timestamp(d): v for d, v in pts}, name=ativo.nome)
```

por:

```python
    return pd.Series({pd.Timestamp(d): float(v) for d, v in pts}, name=ativo.nome)
```

Em `exportar_cotas_excel`, troque:

```python
            cotas[ativo.nome] = pd.Series({pd.Timestamp(d): v for d, v in pts})
```

por:

```python
            cotas[ativo.nome] = pd.Series({pd.Timestamp(d): float(v) for d, v in pts})
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_views.py::TestSerieFloat -v`
Expected: PASS.

- [ ] **Step 5: Suíte completa**

Run: `pytest -q`
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add scrapper/views.py tests/test_views.py
git commit -m "fix(views): cast Decimal->float ao montar pd.Series (pandas/quantstats)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Verificação final

- [ ] `pytest -q` — toda a suíte verde.
- [ ] `python manage.py makemigrations --check --dry-run` — sem migrações pendentes não commitadas.
- [ ] Verificação manual (opcional): com `.env` configurado, adicionar um ativo pela UI e conferir na tela de detalhe que as cotas foram coletadas desde a primeira_cota e que `retorno`/`retorno_ln` estão preenchidos (`CotacaoDiaria.objects.filter(ativo=...).values("data","valor","retorno","retorno_ln")`).
