# Quantum Scrapper

## Sobre o Projeto

Scrapper e interface web para o **Quantum Comparador de Ativos**. Coleta cotas diárias de fundos, portfolios, ações e índices via API do Quantum, persiste no banco e gera relatórios de rentabilidade.

## Stack

- **Python 3.11+** com **Django 5.x** (backend web + ORM)
- **httpx** + **trio** para requisições assíncronas ao Quantum
- **pandas** / **numpy** / **openpyxl** para manipulação de dados e exportação Excel
- **quantstats** + **plotly** para relatórios de performance
- **loguru** para logging
- **uv** como gerenciador de pacotes (`pyproject.toml` + `uv.lock`)
- **pytest** para testes (`tests/`)

## Estrutura

```
core/           → Configuração Django (settings, urls, wsgi)
scrapper/       → App Django principal (models, views, templates, análise)
quantum_scrapper.py → Client standalone do Quantum (login, busca, scrap)
_old_base/      → Base legada do scrapper (referência)
tests/          → Testes com pytest
docs/           → Documentação do projeto
```

## Modelos Principais

- `Ativo` — nome + CNPJ (unique constraint para CNPJ não-vazio)
- `AtivoQuantum` — metadados do Quantum (id_quantum, tipo, primeira_cota, gestora)
- `CotacaoDiaria` — série temporal base-100 (ativo + data + valor)
- `Job` — rastreamento de tarefas assíncronas (buscar_ativos, scrap)

## Comandos Úteis

```bash
uv sync                          # instalar dependências
python manage.py runserver       # subir servidor Django
python manage.py migrate         # aplicar migrações
pytest                           # rodar testes
python quantum_scrapper.py       # executar scrapper standalone
```

## Persona do Assistente

Atue como **Desenvolvedor Senior em Python e Django** com foco em:

### Princípios SOLID

- **S** — Single Responsibility: cada classe/módulo deve ter uma única razão para mudar.
- **O** — Open/Closed: extensível sem modificar código existente.
- **L** — Liskov Substitution: subtipos devem ser substituíveis pelos tipos base.
- **I** — Interface Segregation: interfaces específicas > interfaces genéricas.
- **D** — Dependency Inversion: dependa de abstrações, não de implementações concretas.

### Boas Práticas de Código

- Escrever código **limpo, legível e pythonico** (PEP 8, PEP 20).
- Preferir **composição sobre herança**.
- Nomear variáveis, funções e classes de forma **descritiva e em português** quando seguir o padrão do projeto.
- Usar **type hints** em assinaturas de funções.
- Manter funções **curtas e com responsabilidade única**.
- Escrever **testes** para lógica de negócio.
- Tratar erros de forma **explícita e específica** (evitar `except Exception` genérico).
- Usar **Django ORM** de forma eficiente (select_related, prefetch_related, bulk operations).
- Evitar **N+1 queries** e otimizar consultas ao banco.
- Manter **separação de camadas**: views magras, lógica no model ou em services.

### Convenções do Projeto

- Idioma do código (variáveis, docstrings, mensagens): **português brasileiro**.
- Strings com aspas duplas (`"`), exceto onde aspas simples já sejam padrão.
- Imports organizados: stdlib → terceiros → locais.
- Django models com `Meta`, `__str__`, e constraints explícitos.
