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
# Nota: INDICE e RENDA_FIXA não têm card de medidas/valor na API do Quantum;
# são semeados por catálogo ou ignorados no parser, e por isso não constam aqui
# (parsers usam .get(tipo, []) e tratam a ausência como lista vazia).
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
