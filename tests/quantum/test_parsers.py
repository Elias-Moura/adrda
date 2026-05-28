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

    def test_entrada_invalida_nao_derruba_o_lote(self):
        # Tipo desconhecido e id ausente são descartados; os válidos permanecem.
        grupos = [{
            "codigoGrupo": 0,
            "primeirosResultados": [
                {"itemSelecionavel": {
                    "label": "Tipo novo", "identificador": 9,
                    "tipoItemSelecionavel": "CRIPTO"}},
                {"itemSelecionavel": {
                    "label": "Sem id", "identificador": None,
                    "tipoItemSelecionavel": "FI"}},
                {"itemSelecionavel": {
                    "label": "Válido", "identificador": "612014",
                    "tipoItemSelecionavel": "FI"}},
            ],
        }]
        resultados = parse_resultados_busca(grupos)
        assert len(resultados) == 1
        assert resultados[0].id_quantum == "612014"


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

    def test_ponto_malformado_nao_descarta_a_serie_inteira(self):
        body = json.dumps({"serie": [
            {"data": "2025-05-26", "valor": "100.0"},
            {"data": "data-invalida", "valor": "100.5"},  # data malformada
            {"valor": "100.7"},                            # sem "data"
            {"data": "2025-05-29", "valor": "101.0"},
        ]})
        serie = parse_serie({"responseList": [{"body": body}]})
        assert len(serie.pontos) == 2
        assert serie.pontos[0].data == date(2025, 5, 26)
        assert serie.pontos[1].data == date(2025, 5, 29)


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
