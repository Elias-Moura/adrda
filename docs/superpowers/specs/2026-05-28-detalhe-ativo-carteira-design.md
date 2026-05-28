# Tela de Detalhes do Ativo (com carteira do fundo)

**Data:** 2026-05-28
**Status:** Aprovado para implementação

## Objetivo

Criar uma página dedicada de detalhes de um ativo, aberta ao clicar na linha da
tabela em `ativos.html`. A página reúne a ficha do ativo, estatísticas da série
de cotações, um gráfico Plotly da evolução base-100 e — para fundos (FI) — a
composição da carteira investida, raspada do Quantum e persistida no banco.

## Decisões de design

- **Abertura:** página dedicada na rota `/ativos/<id>/` (não modal/drawer). URL
  compartilhável, espaço total para gráfico e carteira.
- **Gráfico:** Plotly server-side, reaproveitando o padrão de `analise.py`
  (`fig.to_html(full_html=False, include_plotlyjs=False)` + Plotly via CDN).
- **Carteira:** persistida em modelo próprio (não busca ao vivo a cada visita).
  Botão "Atualizar carteira" dispara a coleta sob demanda.
- **Cobertura da carteira:** apenas **FI** nesta versão. FII e Ação exibem aviso.

## Modelos (nova migração)

```python
class CarteiraFundo(models.Model):
    """Composição da carteira de um fundo numa competência (mês de referência)."""
    ativo = models.ForeignKey(Ativo, on_delete=models.CASCADE, related_name="carteiras")
    competencia = models.DateField()          # mês de referência (data de competência)
    importada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-competencia"]
        constraints = [
            models.UniqueConstraint(fields=["ativo", "competencia"], name="carteira_ativo_competencia")
        ]

class PosicaoCarteira(models.Model):
    """Uma posição (ativo investido) dentro de uma CarteiraFundo."""
    carteira = models.ForeignKey(CarteiraFundo, on_delete=models.CASCADE, related_name="posicoes")
    nome = models.CharField(max_length=255)   # ex.: "LFT - Venc.: 01/03/2030"
    participacao = models.FloatField()         # % (0–100)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem"]
```

- "Carteira atual" do fundo = `ativo.carteiras.first()` (ordering `-competencia`).
- `Outros Ativos` (somatório do resto, quando `quantidade < total`) é tratado como
  uma posição comum; com `quantidade=100` a carteira vem completa e a linha não aparece.

## Camada Quantum

Seguir a separação já existente: `client` (HTTP cru) → `parsers` (pydantic puro)
→ `services` (orquestra + ORM).

### `quantum/client.py`
Novo método:
```python
def carteira(self, tipo, id_quantum, competencia, quantidade=100,
             tipo_carteira="INDIVIDUAL") -> dict
```
- Monta `relativeUrl`:
  `/api/ativos/{tipo}/{id_quantum}/carteira?identificador={id_quantum}`
  `&tipoItemQuantum={tipo}&tipoCarteira={tipo_carteira}`
  `&dataCompetencia={YYYY-MM-DD}&quantidade={quantidade}&exibirSomatorioOutros=true`
- Envia pelo multiplex `/b` com `_headers_api()` (exige Bearer token).
- Devolve o dict cru (`responseList`), igual a `dados_complementares`/`serie`.

**A verificar contra a API real (documentado em `docs/api-quantum.md`):**
- método HTTP exato dentro do multiplex (GET vs POST) — `dados_complementares`
  usa POST; a carteira foi vista como request GET-like nos cards. Confirmar.
- se `dataCompetencia` pode ser omitido para obter a competência mais recente.
  Caso não possa, usar o mês corrente e, se vier vazio, recuar mês a mês até achar.

### `quantum/schemas.py`
```python
class PosicaoCarteira(BaseModel):
    nome: str
    participacao: float

class Carteira(BaseModel):
    competencia: date | None = None
    posicoes: list[PosicaoCarteira] = []
```

### `quantum/parsers.py`
```python
def parse_carteira(raw_multiplex: dict, competencia: date | None = None) -> Carteira
```
- Extrai `responseList[0].body` (string JSON) via `_body_multiplex`.
- Cada item: `{"ativo": str, "participacao": str}` → `participacao` em float
  (string com ponto decimal; ex. `"12.33510179..."`).
- Tolerante a itens malformados (descarta o item, loga warning), no mesmo estilo
  de `parse_serie`.

### `services.py`
```python
def coletar_carteira(self, ativo: Ativo, competencia: date | None = None) -> CarteiraFundo
```
- Valida `ativo.tipo == TipoAtivo.FI`; senão `raise ValueError("Carteira disponível apenas para fundos (FI).")`.
- `_ensure_login()`, chama `client.carteira(...)`, `parse_carteira(...)`.
- `@transaction.atomic`: `update_or_create` da `CarteiraFundo` por (ativo, competencia);
  apaga `posicoes` antigas e `bulk_create` das novas com `ordem` sequencial.
- Devolve a `CarteiraFundo` persistida.

## Views e rotas

```python
# urls.py
path("ativos/<int:ativo_id>/", views.detalhe_ativo, name="detalhe_ativo"),
path("ativos/<int:ativo_id>/carteira/atualizar/", views.atualizar_carteira, name="atualizar_carteira"),
```

### `detalhe_ativo(request, ativo_id)` — GET
- `get_object_or_404(Ativo, id=ativo_id)`.
- Stats da série: `num_cotas`, `primeira`/`ultima` data, `valor_atual` (última cotação),
  em consulta única agregada onde possível.
- Série base-100 do banco → figura Plotly (linha única do ativo, sem índices),
  embutida via `fig.to_html(full_html=False, include_plotlyjs=False)`. Se não há
  cotações, não gera gráfico (template mostra aviso).
- Carteira atual: `ativo.carteiras.prefetch_related("posicoes").first()`.
- Flags de contexto: `pode_ter_carteira = ativo.tipo == "FI"`.

### `atualizar_carteira(request, ativo_id)` — POST (síncrono)
- `@require_POST`. Valida tipo FI (senão 400 com mensagem).
- `QuantumService().coletar_carteira(ativo)`; em sucesso retorna
  `JsonResponse({"ok": True, "competencia": ..., "posicoes": N})`.
- Erro de rede/login → `JsonResponse({"erro": ...}, status=502)`, como `buscar_candidatos`.
- O JS na página recarrega (`location.reload()`) após sucesso.

## Template `scrapper/detalhe.html`

Estende `base.html`. Seções:
1. **Cabeçalho** — nome + badge do tipo; botões: Voltar (lista), Relatório
   (`/relatorio/?ids=`, nova aba), Exportar cotas (se houver), Excluir.
2. **Faixa de stats** — nº de cotações, período coberto (1ª → última), valor base-100 atual.
3. **Ficha** — CNPJ, ticker, gestora, setor, 1ª cota, ID Quantum, criado/atualizado;
   metadados extras (JSON) em bloco recolhível.
4. **Gráfico** — figura Plotly; ou aviso "Sem cotações — rode o scrap" quando vazio.
5. **Carteira do fundo** (só `pode_ter_carteira`):
   - Com carteira: competência + nº posições + importada_em; tabela
     `Posição | Participação %` (ordenada desc) + barras das top-5; botão "Atualizar carteira".
   - Sem carteira (FI): "Nenhuma carteira importada." + botão "Buscar carteira".
   - Não-FI: a seção exibe "Composição de carteira disponível apenas para fundos (FI)".
- Plotly CDN + JS de atualizar carteira / excluir vão em `{% block scripts %}`.

### Ajuste em `ativos.html`
- A `<tr class="ativo-row">` passa a navegar para `detalhe_ativo` ao ser clicada.
- Cliques dentro da célula de ações (botões existentes) **não** disparam a navegação
  (delegação de evento que ignora alvos dentro de `td` de ações / `button`/`a`).
- Cursor `pointer` na linha para indicar que é clicável.

## Exclusão pela página de detalhes
- Reutiliza o endpoint `excluir_ativo` existente (modal de confirmação igual ao de `ativos.html`).
- Após sucesso, redireciona para a lista (`/ativos/`) em vez de `location.reload()`.

## Estados de erro / borda
- Ativo inexistente → 404.
- Ativo sem cotações → ficha e stats normais; gráfico substituído por aviso.
- Carteira para FII/Ação → aviso, sem botão de busca.
- Falha de coleta da carteira (login/rede/competência vazia) → mensagem amigável na seção.

## Testes (pytest)
- `parse_carteira`: JSON válido → posições com float; item malformado descartado;
  body ausente → `Carteira` vazia.
- `coletar_carteira`: tipo não-FI levanta `ValueError`; upsert por competência
  substitui posições antigas (client e parser mockados).
- Modelos: unique (ativo, competencia); cascade ao excluir `CarteiraFundo`/`Ativo`.
- View `detalhe_ativo`: 200 com ativo existente; 404 com id inválido; contexto
  contém stats e carteira.
- View `atualizar_carteira`: 400 para não-FI; 200 para FI (service mockado).

## Fora de escopo (YAGNI)
- Carteira de FII (extrato `.qt`/Excel) e agregações por tipo/setor/risco/classe.
- Seletor de competência histórica na UI (modelo já suporta; UI fica para depois).
- Valor em milhares por posição (REST não fornece).
