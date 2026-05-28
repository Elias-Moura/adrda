from scrapper.quantum.catalogo import (
    INDICES,
    MEDIDAS_POR_TIPO,
    SubtipoAcao,
    TipoAtivo,
    rotulo_tipo,
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


class TestRotuloTipo:
    def test_fi(self):
        assert rotulo_tipo(TipoAtivo.FI) == "Fundo de Investimento"

    def test_fii(self):
        assert rotulo_tipo(TipoAtivo.FII) == "Fundo Imobiliário"

    def test_indice(self):
        assert rotulo_tipo(TipoAtivo.INDICE) == "Índice"

    def test_renda_fixa(self):
        assert rotulo_tipo(TipoAtivo.RENDA_FIXA) == "Renda Fixa"

    def test_acao_sem_subtipo(self):
        assert rotulo_tipo(TipoAtivo.ACAO) == "Ação"

    def test_acao_subtipo_stocks(self):
        assert rotulo_tipo(TipoAtivo.ACAO, "Stocks") == "Ação"

    def test_acao_subtipo_bdr(self):
        assert rotulo_tipo(TipoAtivo.ACAO, "BDR") == "BDR"

    def test_acao_subtipo_etf(self):
        assert rotulo_tipo(TipoAtivo.ACAO, "ETF") == "ETF"

    def test_aceita_tipo_como_string(self):
        assert rotulo_tipo("FI") == "Fundo de Investimento"

    def test_subtipo_desconhecido_cai_no_rotulo_base(self):
        assert rotulo_tipo(TipoAtivo.ACAO, "Outro") == "Ação"


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
