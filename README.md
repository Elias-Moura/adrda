# Quantum Scrapper

Scraper e interface web para o **Quantum Comparador de Ativos** ([comparadordeativos.com.br](https://www.comparadordeativos.com.br)).

Importa fundos de investimento por CNPJ, coleta cotas diarias e gera relatorios de performance com metricas financeiras e graficos interativos.

## Funcionalidades

- **Importacao de ativos** via upload de Excel (colunas `nome` e `cnpj`) ou CNPJ individual
- **Coleta de cotas diarias** com inclusao automatica de indices de referencia (CDI, IBOVESPA, IPCA, IMA-B, IHFA, IRF-M, IFIX, BDRX, Dolar PTAX)
- **Relatorio de performance** com metricas (Retorno Total, CAGR, Volatilidade, Sharpe, Sortino, Max Drawdown, Calmar, VaR 95%) e 5 graficos interativos via Plotly
- **Exportacao para Excel** de metadados e cotas

## Pre-requisitos

- Python 3.11+
- Credenciais de acesso ao Quantum (usuario e senha)

## Instalacao

### Opcao 1: com uv (recomendado)

```bash
# Instale o uv caso ainda nao tenha
# Windows (PowerShell):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux/macOS:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone o repositorio e entre na pasta
git clone <url-do-repositorio>
cd quantum-scrapper

# Sincronize as dependencias (cria o ambiente virtual automaticamente)
uv sync

# Para incluir dependencias de desenvolvimento (pytest)
uv sync --group dev
```

### Opcao 2: com pip + venv

```bash
# Clone o repositorio e entre na pasta
git clone <url-do-repositorio>
cd quantum-scrapper

# Crie o ambiente virtual
python -m venv .venv

# Ative o ambiente virtual
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate

# Instale o projeto e suas dependencias
pip install -e .

# Para incluir dependencias de desenvolvimento
pip install -e ".[dev]" 2>/dev/null || pip install pytest>=8.0
```

## Configuracao

Crie um arquivo `.env` na raiz do projeto:

```env
QUANTUM_USERNAME=seu_email@exemplo.com
QUANTUM_PASSWORD=sua_senha
```

## Uso

### Interface web (Django)

```bash
# Aplique as migracoes do banco de dados (apenas na primeira vez)
# Com uv:
uv run python manage.py migrate
# Com pip/venv:
python manage.py migrate

# Inicie o servidor de desenvolvimento
# Com uv:
uv run python manage.py runserver
# Com pip/venv:
python manage.py runserver
```

Acesse [http://127.0.0.1:8000](http://127.0.0.1:8000) no navegador.

**Fluxo tipico:**

1. Na pagina inicial, faca upload de um Excel com ativos (colunas `nome` e `cnpj`) ou adicione um CNPJ individual
2. Selecione os ativos importados e o periodo desejado para coletar cotas
3. Gere o relatorio de performance com graficos e metricas

### Uso como biblioteca Python

```python
from datetime import date
from quantum_scrapper import QuantumScrapper, Ativo

qs = QuantumScrapper()
qs.login()  # le credenciais do .env

# Buscar ativos por CNPJ
ativos = qs.trabalha_novos_ativos([
    Ativo(nome="Fundo XYZ", cnpj="12.345.678/0001-90"),
])

# Coletar cotas diarias
df = qs.scrap(ativos, date(2024, 1, 1), date(2024, 12, 31))
```

## Testes

```bash
# Com uv:
uv run pytest

# Com pip/venv:
pytest
```

## Estrutura do projeto

```
quantum-scrapper/
├── quantum_scrapper.py   # Biblioteca de scraping (standalone)
├── manage.py             # Django management
├── pyproject.toml        # Dependencias e configuracao
├── .env                  # Credenciais (nao versionar)
├── core/                 # Configuracao Django
│   ├── settings.py
│   └── urls.py
├── scrapper/             # App Django principal
│   ├── models.py         # Modelos: Ativo, AtivoQuantum, CotacaoDiaria, Job
│   ├── views.py          # Endpoints da interface web
│   ├── analise.py        # Geracao de relatorios HTML com Plotly
│   └── templates/        # Templates HTML
└── tests/
    └── test_quantum_scrapper.py
```
