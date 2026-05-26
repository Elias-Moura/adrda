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

    def test_e_comparavel_a_string(self):
        assert SubtipoAcao.STOCKS == "Stocks"


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
