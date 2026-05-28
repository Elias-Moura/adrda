# Redesign da Tela de Ativos — Design

**Data:** 2026-05-28
**Escopo:** Página `/ativos/` (`scrapper/templates/scrapper/ativos.html` + view `ativos_list`)

## Objetivo

Transformar a tela de Ativos — hoje uma tabela estática somente-leitura — em uma
interface de consulta útil: resumo no topo, busca, filtro por tipo, ordenação por
coluna e ações por linha. Sem mudanças de modelo, migrações ou novas dependências
(Bootstrap 5.3 + Bootstrap Icons já carregados na `base.html`).

## Direção de layout

**Layout A — Toolbar no topo (full width)**, escolhido por consistência com o
Dashboard e melhor aproveitamento da largura para a tabela. Estrutura de cima
para baixo:

1. **Cabeçalho** — título "Ativos no Banco" + botão "Voltar ao Dashboard".
2. **Cards de resumo** — Total · Fundos (FI+FII) · Ações · Portfolios/Renda Fixa.
   Cada card de tipo também funciona como atalho de filtro (clicar filtra a tabela).
3. **Toolbar** — campo de busca (nome/CNPJ/ticker) + dropdown de filtro por tipo.
   Exibe contador "X de Y ativos" conforme filtra.
4. **Tabela aprimorada** — cabeçalhos clicáveis para ordenar, badges de tipo
   coloridos, nova coluna "Cotas" (nº + última data) e coluna "Ações".

## Camadas e responsabilidades

### View `ativos_list` (scrapper/views.py)

Permanece magra. Além do queryset de ativos (excluindo `INDICE`, como hoje):

- **Anotação por ativo** (uma query, sem N+1):
  ```python
  ativos = (
      Ativo.objects.exclude(tipo=TipoAtivo.INDICE)
      .annotate(num_cotas=Count("cotacoes"), ultima_cota=Max("cotacoes__data"))
      .order_by("nome")
  )
  ```
- **Resumo por tipo** (uma query agregada):
  ```python
  contagem = dict(
      Ativo.objects.exclude(tipo=TipoAtivo.INDICE)
      .values_list("tipo").annotate(n=Count("id"))
  )
  ```
  A partir daí derivam-se os números dos cards (Fundos = FI+FII, Ações = ACAO,
  Portfolios/RF = RENDA_FIXA, etc.) e o total.

Contexto adicionado ao template: `resumo` (total + contagem por grupo de tipo).

### Template `ativos.html`

Redesenhado conforme layout A. Toda a interatividade — busca, filtro por tipo,
ordenação de colunas, copiar para área de transferência — é **client-side em JS
puro** no bloco `{% block scripts %}`. A lista já vem renderizada e é pequena;
não há novos endpoints para essas operações.

Detalhes visuais:
- **Badges por tipo** com cores consistentes (Fundo=azul, FII=teal, Ação=verde,
  Portfolio/RF=roxo). Rótulo amigável via `get_tipo_display` / catálogo.
- **Coluna "Cotas"** mostra `num_cotas` e `ultima_cota` (ou "—" quando zero),
  sinalizando quais ativos já têm série coletada.
- **Responsivo**: cards empilham, tabela com scroll horizontal no mobile.

### Ações por linha (reaproveitam endpoints existentes)

- **📈 Gerar relatório** → abre `/relatorio/?ids=<id>` em nova aba, com este ativo
  pré-selecionado (ver mudança em `relatorio` abaixo).
- **📄 Exportar cotas** → link direto para `/exportar-cotas/?ids=<id>` (endpoint já
  aceita `ids`). Baixa o Excel apenas deste ativo.
- **⧉ Copiar** → copia CNPJ (ou ID Quantum se não houver CNPJ) via
  `navigator.clipboard`, com feedback visual breve ("copiado!").

### Mudança em `relatorio` (view + relatorio.html)

Hoje a página de seleção do relatório renderiza todos os checkboxes de carteiras
com `checked`. Passa a respeitar pré-seleção via GET:

- A view `relatorio` (ramo de seleção) lê `request.GET.getlist("ids")` e passa um
  conjunto `preselecionados` ao contexto.
- No `relatorio.html`, o atributo `checked` da carteira torna-se condicional:
  marca apenas os ids em `preselecionados` **quando houver algum**; sem `ids` no
  GET, mantém o comportamento atual (todos marcados). A pré-seleção via `ids`
  aplica-se **apenas às carteiras**; os checkboxes de **índices permanecem todos
  marcados** (preserva o comportamento atual — benchmarks são desejáveis no
  relatório por padrão).

## Estados e bordas

- **Vazio** — ilustração + "Nenhum ativo importado" com link para o Dashboard
  (estilizado, no espírito do `relatorio.html`).
- **Busca/filtro sem resultado** — linha "Nenhum ativo corresponde ao filtro".
- **Ativo sem dados Quantum** (`id_quantum` ausente) — degrada como hoje.

## Testes (tests/test_views.py)

- `ativos_list` retorna `resumo` com contagens por tipo corretas.
- `ativos_list` anota `num_cotas` e `ultima_cota` corretamente (incl. zero cotas).
- `ativos_list` exclui `INDICE`.
- `relatorio` (seleção) marca apenas os `ids` passados via GET e mantém todos
  marcados quando `ids` ausente.

## Fora de escopo (YAGNI)

- Paginação (lista pequena; revisar se passar de ~algumas centenas).
- Nova view de detalhe de cotações por ativo.
- Edição/exclusão de ativos pela tela.
- Mudanças de modelo ou migrações.
