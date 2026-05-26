"""
Testes unitários para quantum_scrapper.py (versão refatorada — sem selenium, sem hub_k1).

Funções cobertas:
  - parseFloat
  - AtivoQuantum.avalia_data_inicio
  - QuantumScrapper.resolve_relative_url
  - QuantumScrapper._simplificar_retorno_multiplex
  - QuantumScrapper.monta_df_rentabilidade_diaria
  - QuantumScrapper.req_cnpj
  - QuantumScrapper._get_dados_complementares
  - QuantumScrapper.get_retorno_carteira
  - QuantumScrapper.trabalha_novos_ativos
  - QuantumScrapper.raspar_dados
  - QuantumScrapper.scrap
  - QuantumScrapper.salvar_retonos
"""
import json
import pytest
import trio
import pandas as pd
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from quantum_scrapper import QuantumScrapper, AtivoQuantum, Ativo, parseFloat, _RateLimiter


# ── Factory: cria instância sem __init__ (não precisa de credenciais/rede) ──
def _make_qs(**kwargs) -> QuantumScrapper:
    qs = object.__new__(QuantumScrapper)
    qs.token = kwargs.get("token", "Bearer fake-jwt-token")
    qs._client = MagicMock()           # mock do httpx.Client
    qs.data_inicio = kwargs.get("data_inicio", date(2024, 1, 1))
    qs.data_fim = kwargs.get("data_fim", date(2024, 12, 31))
    qs.ativos = kwargs.get("ativos", [])
    qs.dfs_rentabilidades = kwargs.get("dfs_rentabilidades", [])
    return qs


# ════════════════════════════════════════════════════════════════════════════
# parseFloat
# ════════════════════════════════════════════════════════════════════════════
class TestParseFloat:
    def test_numero_com_separador_de_milhar_e_decimal_br(self):
        assert parseFloat("1.234,56") == pytest.approx(1234.56)

    def test_numero_sem_milhar(self):
        assert parseFloat("100,00") == pytest.approx(100.0)

    def test_numero_com_prefixo_reais(self):
        assert parseFloat("R$ 1.500,00") == pytest.approx(1500.0)

    def test_numero_com_multiplos_separadores_de_milhar(self):
        assert parseFloat("1.000.000,00") == pytest.approx(1_000_000.0)

    def test_retorno_e_do_tipo_float(self):
        assert isinstance(parseFloat("10,00"), float)


# ════════════════════════════════════════════════════════════════════════════
# AtivoQuantum.avalia_data_inicio
# ════════════════════════════════════════════════════════════════════════════
class TestAvaliaDataInicio:
    def test_retorna_data_solicitada_quando_fundo_e_mais_antigo(self):
        ativo = AtivoQuantum(nome="F", tipo="FI", primeira_cota=date(2019, 1, 1))
        assert ativo.avalia_data_inicio(date(2022, 1, 1)) == date(2022, 1, 1)

    def test_retorna_primeira_cota_quando_fundo_e_mais_novo(self):
        ativo = AtivoQuantum(nome="F", tipo="FI", primeira_cota=date(2023, 6, 1))
        assert ativo.avalia_data_inicio(date(2022, 1, 1)) == date(2023, 6, 1)

    def test_retorna_data_solicitada_quando_datas_sao_iguais(self):
        d = date(2022, 1, 1)
        ativo = AtivoQuantum(nome="F", tipo="FI", primeira_cota=d)
        assert ativo.avalia_data_inicio(d) == d

    def test_retorna_data_solicitada_quando_primeira_cota_e_none(self):
        ativo = AtivoQuantum(nome="F", tipo="FI", primeira_cota=None)
        assert ativo.avalia_data_inicio(date(2022, 1, 1)) == date(2022, 1, 1)

    def test_retorna_data_solicitada_sem_primeira_cota(self):
        ativo = AtivoQuantum(nome="F", tipo="FI")
        assert ativo.avalia_data_inicio(date(2020, 5, 10)) == date(2020, 5, 10)


# ════════════════════════════════════════════════════════════════════════════
# resolve_relative_url
# ════════════════════════════════════════════════════════════════════════════
class TestResolveRelativeUrl:
    def setup_method(self):
        self.qs = _make_qs()

    def test_tipo_fi_usa_id_quantum(self):
        ativo = AtivoQuantum(nome="Fundo X", tipo="FI", id_quantum=123456)
        assert self.qs.resolve_relative_url(ativo) == "/api/ativos/FI/123456/medidas/serie"

    def test_tipo_indice_usa_id_quantum(self):
        ativo = AtivoQuantum(nome="CDI", tipo="INDICE", id_quantum=1)
        assert self.qs.resolve_relative_url(ativo) == "/api/ativos/INDICE/1/medidas/serie"

    def test_tipo_portfolio_usa_nome_url_encodado(self):
        ativo = AtivoQuantum(nome="CDI__", tipo="PORTFOLIO")
        assert self.qs.resolve_relative_url(ativo) == "/api/ativos/PORTFOLIO/CDI__/medidas/serie"

    def test_tipo_portfolio_encoda_espacos_e_acentos(self):
        ativo = AtivoQuantum(nome="Carteira nível 1 2024", tipo="PORTFOLIO")
        url = self.qs.resolve_relative_url(ativo)
        assert "PORTFOLIO" in url
        assert " " not in url       # espaços devem ser encodados
        assert "nível" not in url   # acento deve ser encodado

    def test_sufixo_padrao_e_serie(self):
        ativo = AtivoQuantum(nome="X", tipo="FI", id_quantum=1)
        assert self.qs.resolve_relative_url(ativo).endswith("/medidas/serie")

    def test_sufixo_valor(self):
        ativo = AtivoQuantum(nome="X", tipo="FI", id_quantum=999)
        assert self.qs.resolve_relative_url(ativo, sufixo="valor").endswith("/medidas/valor")

    def test_estrutura_completa_da_url(self):
        ativo = AtivoQuantum(nome="X", tipo="FI", id_quantum=42)
        partes = self.qs.resolve_relative_url(ativo).split("/")
        assert partes[1] == "api"
        assert partes[2] == "ativos"
        assert partes[3] == "FI"
        assert partes[4] == "42"


# ════════════════════════════════════════════════════════════════════════════
# _simplificar_retorno_multiplex
# ════════════════════════════════════════════════════════════════════════════
class TestSimplificarRetornoMultiplex:
    _ORDEM = [
        "NOME", "CLASSIFICACAO_LEGAL", "CNPJ", "GESTAO", "CLASSIFICACAO_ANBIMA",
        "BENCHMARK", "ABERTO_PARA_CAPTACAO", "PUBLICO_ALVO",
        "TAXA_ADMINISTRACAO_E_GESTAO", "TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA",
        "TAXA_DE_PERFORMANCE", "TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA",
        "APLICACAO_MINIMA", "CONVERSAO_DA_COTA_PARA_APLICACAO",
        "CONVERSAO_DA_COTA_PARA_RESGATE", "DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS",
        "TAXAS_INFORMACOES_ADICIONAIS_EXTRA", "INICIO_DO_FUNDO",
        "MOVIMENTACAO_MINIMA", "DIVULGACAO", "PORCENTAGEM_RENDA_VARIAVEL_FIE",
        "TAXA_DE_RESGATE_EXTRA", "TRIBUTACAO", "POSSUI_SERIE",
    ]

    def setup_method(self):
        self.qs = _make_qs()

    def _resposta(self, valores: list) -> dict:
        body = json.dumps([{"valor": v} for v in valores])
        return {"responseList": [{"body": body}]}

    def test_retorna_exatamente_24_chaves(self):
        resultado = self.qs._simplificar_retorno_multiplex(
            self._resposta([f"v{i}" for i in range(24)])
        )
        assert len(resultado) == 24

    def test_chaves_correspondem_a_ordem_de_medidas(self):
        resultado = self.qs._simplificar_retorno_multiplex(
            self._resposta([f"v{i}" for i in range(24)])
        )
        assert set(resultado.keys()) == set(self._ORDEM)

    def test_mapeia_nome_no_indice_0(self):
        valores = [f"v{i}" for i in range(24)]
        valores[0] = "AMW CASH CLASH"
        resultado = self.qs._simplificar_retorno_multiplex(self._resposta(valores))
        assert resultado["NOME"] == "AMW CASH CLASH"

    def test_mapeia_cnpj_no_indice_2(self):
        valores = [f"v{i}" for i in range(24)]
        valores[2] = "42.550.188/0001-91"
        resultado = self.qs._simplificar_retorno_multiplex(self._resposta(valores))
        assert resultado["CNPJ"] == "42.550.188/0001-91"

    def test_mapeia_inicio_do_fundo_no_indice_17(self):
        valores = [f"v{i}" for i in range(24)]
        valores[17] = "2021-09-10"
        resultado = self.qs._simplificar_retorno_multiplex(self._resposta(valores))
        assert resultado["INICIO_DO_FUNDO"] == "2021-09-10"

    def test_preserva_valores_none(self):
        resultado = self.qs._simplificar_retorno_multiplex(
            self._resposta([None] * 24)
        )
        assert all(v is None for v in resultado.values())

    def test_levanta_excecao_quando_body_e_none(self):
        with pytest.raises(Exception):
            self.qs._simplificar_retorno_multiplex(
                {"responseList": [{"body": None}]}
            )

    def test_levanta_excecao_quando_body_json_invalido(self):
        with pytest.raises(Exception):
            self.qs._simplificar_retorno_multiplex(
                {"responseList": [{"body": "nao-e-json"}]}
            )

    def test_levanta_excecao_quando_numero_de_valores_diferente_de_24(self):
        with pytest.raises(Exception, match="Inconsistência"):
            self.qs._simplificar_retorno_multiplex(
                self._resposta([f"v{i}" for i in range(10)])
            )

    def test_levanta_excecao_quando_lista_maior_que_24(self):
        with pytest.raises(Exception, match="Inconsistência"):
            self.qs._simplificar_retorno_multiplex(
                self._resposta([f"v{i}" for i in range(30)])
            )


# ════════════════════════════════════════════════════════════════════════════
# monta_df_rentabilidade_diaria
# ════════════════════════════════════════════════════════════════════════════
class TestMontaDfRentabilidadeDiaria:
    """
    Lógica de negócio:
      - cota base de referência = 100 (hardcoded)
      - rentabilidade_i = (cota_i - cota_{i-1}) / cota_{i-1}
      - coluna '%' = 1 + rentabilidade_i
      - última linha extra: rentabilidade acumulada via produto das colunas '%'
    """

    def setup_method(self):
        self.qs = _make_qs()

    def _response(self, cotacoes: list[tuple]) -> dict:
        serie = [{"data": d, "valor": str(v)} for d, v in cotacoes]
        return {"responseList": [{"body": json.dumps({"serie": serie})}]}

    def test_retorna_df_vazio_quando_chave_serie_ausente(self):
        resp = {"responseList": [{"body": json.dumps({"outro": []})}]}
        assert self.qs.monta_df_rentabilidade_diaria(resp).empty

    def test_colunas_presentes(self):
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 101.0)])
        )
        assert {"hoje", "valor", "rentabilidade", "%"}.issubset(df.columns)

    def test_numero_de_linhas_e_n_cotacoes_mais_um(self):
        cotacoes = [("2024-01-0" + str(i), 100 + i) for i in range(2, 7)]
        df = self.qs.monta_df_rentabilidade_diaria(self._response(cotacoes))
        assert len(df) == len(cotacoes) + 1

    def test_primeira_rentabilidade_usa_base_100(self):
        # Base interna = 100; primeira cota = 105 → rent = +5%
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 105.0)])
        )
        assert df.iloc[0]["rentabilidade"] == pytest.approx(0.05)

    def test_rentabilidade_encadeada_entre_cotas(self):
        # 100→110 (+10%), 110→121 (+10%)
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 110.0), ("2024-01-03", 121.0)])
        )
        assert df.iloc[0]["rentabilidade"] == pytest.approx(0.10)
        assert df.iloc[1]["rentabilidade"] == pytest.approx(0.10)

    def test_coluna_porcentagem_e_um_mais_rentabilidade(self):
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 110.0)])
        )
        linha = df.iloc[0]
        assert linha["%"] == pytest.approx(1 + linha["rentabilidade"])

    def test_ultima_linha_label_e_rentabilidade_periodo(self):
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 110.0), ("2024-01-03", 121.0)])
        )
        assert df.iloc[-1]["rentabilidade"] == "Rentabilidade período:"

    def test_ultima_linha_data_e_valor_sao_string_vazia(self):
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 110.0)])
        )
        assert df.iloc[-1]["hoje"] == ""
        assert df.iloc[-1]["valor"] == ""

    def test_rentabilidade_acumulada_composta_corretamente(self):
        # 100→110 (+10%) e 110→121 (+10%) → acumulado = 1.1 × 1.1 − 1 = 21%
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 110.0), ("2024-01-03", 121.0)])
        )
        assert df.iloc[-1]["%"] == pytest.approx(0.21)

    def test_rentabilidade_acumulada_com_queda(self):
        # 100→90 (−10%) → acumulado = 0.9 − 1 = −10%
        df = self.qs.monta_df_rentabilidade_diaria(
            self._response([("2024-01-02", 90.0)])
        )
        assert df.iloc[-1]["%"] == pytest.approx(-0.10)


# ════════════════════════════════════════════════════════════════════════════
# req_cnpj  (mock httpx.Client)
# ════════════════════════════════════════════════════════════════════════════
class TestReqCnpj:
    _CNPJ = "45.823.918/0001-79"
    _PAYLOAD_OK = [
        {"primeirosResultados": [{"itemSelecionavel": {"label": "Fundo X"}}]}
    ]

    def setup_method(self):
        self.qs = _make_qs()
        # Configura o mock padrão de sucesso
        self.qs._client.get.return_value.status_code = 200
        self.qs._client.get.return_value.json.return_value = self._PAYLOAD_OK

    def test_retorna_json_da_api(self):
        assert self.qs.req_cnpj(self._CNPJ) == self._PAYLOAD_OK

    def test_usa_metodo_get(self):
        self.qs.req_cnpj(self._CNPJ)
        self.qs._client.get.assert_called_once()

    def test_cnpj_presente_na_url_chamada(self):
        self.qs.req_cnpj(self._CNPJ)
        url = self.qs._client.get.call_args[0][0]
        assert "45.823.918" in url or "45%2E823" in url

    def test_token_enviado_no_header_authorization(self):
        self.qs.req_cnpj(self._CNPJ)
        headers = self.qs._client.get.call_args[1]["headers"]
        assert headers["authorization"] == self.qs.token

    def test_levanta_value_error_em_status_401(self):
        self.qs._client.get.return_value.status_code = 401
        self.qs._client.get.return_value.text = "Unauthorized"
        with pytest.raises(ValueError, match="401"):
            self.qs.req_cnpj(self._CNPJ)

    def test_levanta_value_error_em_status_500(self):
        self.qs._client.get.return_value.status_code = 500
        self.qs._client.get.return_value.text = "Server Error"
        with pytest.raises(ValueError, match="500"):
            self.qs.req_cnpj(self._CNPJ)


# ════════════════════════════════════════════════════════════════════════════
# _get_dados_complementares  (mock httpx.Client)
# ════════════════════════════════════════════════════════════════════════════
class TestGetDadosComplementares:
    _VALORES_24 = [
        "AMW CASH", "FI", "42.550.188/0001-91", "Amw Asset", "Renda Fixa",
        "IRF-M", "Sim", "Investidores em geral", "0.17", "2.0",
        "10.0", "100% do CDI", "100.00", "D+0", "D+0",
        "D+0", "Tx.Custódia: 0%", "2021-09-10", "0.00", "D",
        "Não informado", "Não possui", "FI_LONGO_PRAZO", "true",
    ]

    def setup_method(self):
        self.qs = _make_qs()
        body = json.dumps([{"valor": v} for v in self._VALORES_24])
        self.qs._client.post.return_value.status_code = 200
        self.qs._client.post.return_value.json.return_value = {
            "responseList": [{"body": body}]
        }

    def test_retorna_cnpj_correto(self):
        result = self.qs._get_dados_complementares(tipo="FI", id=123456)
        assert result["CNPJ"] == "42.550.188/0001-91"

    def test_retorna_inicio_do_fundo_correto(self):
        result = self.qs._get_dados_complementares(tipo="FI", id=123456)
        assert result["INICIO_DO_FUNDO"] == "2021-09-10"

    def test_retorna_gestora_correta(self):
        result = self.qs._get_dados_complementares(tipo="FI", id=123456)
        assert result["GESTAO"] == "Amw Asset"

    def test_usa_metodo_post(self):
        self.qs._get_dados_complementares(tipo="FI", id=1)
        self.qs._client.post.assert_called_once()

    def test_payload_contem_tipo_e_id_na_relative_url(self):
        self.qs._get_dados_complementares(tipo="FI", id=999)
        payload = self.qs._client.post.call_args[1]["content"]
        assert "FI" in payload
        assert "999" in payload

    def test_token_no_header_authorization(self):
        self.qs._get_dados_complementares(tipo="FI", id=1)
        headers = self.qs._client.post.call_args[1]["headers"]
        assert headers["authorization"] == self.qs.token

    def test_levanta_value_error_em_status_403(self):
        self.qs._client.post.return_value.status_code = 403
        self.qs._client.post.return_value.text = "Forbidden"
        with pytest.raises(ValueError, match="403"):
            self.qs._get_dados_complementares(tipo="FI", id=1)

    def test_levanta_value_error_em_status_401(self):
        self.qs._client.post.return_value.status_code = 401
        self.qs._client.post.return_value.text = "Unauthorized"
        with pytest.raises(ValueError, match="401"):
            self.qs._get_dados_complementares(tipo="FI", id=1)


# ════════════════════════════════════════════════════════════════════════════
# get_retorno_carteira  (mock httpx.Client)
# ════════════════════════════════════════════════════════════════════════════
class TestGetRetornoCarteira:
    def setup_method(self):
        self.qs = _make_qs()
        self.ativo = AtivoQuantum(nome="CDI__", tipo="PORTFOLIO")
        self.di = date(2024, 1, 1)
        self.df_date = date(2024, 12, 31)
        self.expected = {"responseList": [{"body": '{"serie": []}'}]}
        self.qs._client.post.return_value.status_code = 200
        self.qs._client.post.return_value.json.return_value = self.expected

    def test_retorna_json_da_api(self):
        assert self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo) == self.expected

    def test_usa_metodo_post(self):
        self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo)
        self.qs._client.post.assert_called_once()

    def test_token_enviado_no_header_authorization(self):
        self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo)
        headers = self.qs._client.post.call_args[1]["headers"]
        assert headers["authorization"] == self.qs.token

    def test_payload_contem_data_inicial(self):
        self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo)
        payload = self.qs._client.post.call_args[1]["content"]
        assert "2024-01-01" in payload

    def test_payload_contem_data_final(self):
        self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo)
        payload = self.qs._client.post.call_args[1]["content"]
        assert "2024-12-31" in payload

    def test_payload_contem_medida_evolucao_do_ativo(self):
        self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo)
        payload = self.qs._client.post.call_args[1]["content"]
        assert "EVOLUCAO_DO_ATIVO" in payload

    def test_payload_contem_periodicidade_diaria(self):
        self.qs.get_retorno_carteira(self.di, self.df_date, self.ativo)
        payload = self.qs._client.post.call_args[1]["content"]
        assert "DIARIA" in payload


# ════════════════════════════════════════════════════════════════════════════
# trabalha_novos_ativos  (orquestração concorrente — mock em _processar_ativo_async)
# ════════════════════════════════════════════════════════════════════════════
class TestTrabalhaNovoAtivos:
    _ATIVO_QUANTUM = AtivoQuantum(
        nome="AMW CASH CLASH FI RENDA FIXA LP",
        tipo="FI",
        id_quantum="612014",
        cnpj="42.550.188/0001-91",
        primeira_cota=date(2021, 9, 10),
        gestora="Amw Asset Management",
        dados_complementares={
            "CNPJ": "42.550.188/0001-91",
            "GESTAO": "Amw Asset Management",
            "INICIO_DO_FUNDO": "2021-09-10",
        },
    )

    def setup_method(self):
        self.qs = _make_qs()
        expected = self._ATIVO_QUANTUM

        async def _fake_processar(ativo, client, limiter):
            await limiter.acquire()
            await limiter.acquire()
            return expected

        self.qs._processar_ativo_async = _fake_processar

    def test_retorna_lista_com_um_ativo_quantum(self):
        resultado = self.qs.trabalha_novos_ativos([Ativo(cnpj="42.550.188/0001-91")])
        assert len(resultado) == 1
        assert isinstance(resultado[0], AtivoQuantum)

    def test_ativo_retornado_tem_cnpj_correto(self):
        resultado = self.qs.trabalha_novos_ativos([Ativo(cnpj="42.550.188/0001-91")])
        assert resultado[0].cnpj == "42.550.188/0001-91"

    def test_ativo_retornado_tem_tipo_correto(self):
        resultado = self.qs.trabalha_novos_ativos([Ativo(cnpj="42.550.188/0001-91")])
        assert resultado[0].tipo == "FI"

    def test_ativo_retornado_tem_id_quantum_correto(self):
        resultado = self.qs.trabalha_novos_ativos([Ativo(cnpj="42.550.188/0001-91")])
        assert resultado[0].id_quantum == "612014"

    def test_ativo_retornado_tem_primeira_cota_como_date(self):
        resultado = self.qs.trabalha_novos_ativos([Ativo(cnpj="42.550.188/0001-91")])
        assert resultado[0].primeira_cota == date(2021, 9, 10)

    def test_lista_vazia_retorna_lista_vazia(self):
        assert self.qs.trabalha_novos_ativos([]) == []

    def test_processa_multiplos_ativos(self):
        resultado = self.qs.trabalha_novos_ativos([
            Ativo(cnpj="cnpj_a"),
            Ativo(cnpj="cnpj_b"),
            Ativo(cnpj="cnpj_c"),
        ])
        assert len(resultado) == 3

    def test_preserva_ordem_dos_ativos(self):
        """O resultado[i] deve corresponder ao ativo[i] de entrada."""
        nomes = ["FundoA", "FundoB", "FundoC"]
        por_cnpj = {
            f"cnpj_{i}": AtivoQuantum(
                nome=n, tipo="FI", id_quantum=str(i),
                cnpj=f"cnpj_{i}",
                primeira_cota=date(2020, 1, 1),
                gestora="G",
                dados_complementares={"CNPJ": f"cnpj_{i}", "GESTAO": "G", "INICIO_DO_FUNDO": "2020-01-01"},
            )
            for i, n in enumerate(nomes)
        }

        async def _fake_por_cnpj(ativo, client, limiter):
            await limiter.acquire()
            await limiter.acquire()
            return por_cnpj[ativo.cnpj]

        self.qs._processar_ativo_async = _fake_por_cnpj
        resultado = self.qs.trabalha_novos_ativos([Ativo(cnpj=f"cnpj_{i}") for i in range(3)])
        assert [r.nome for r in resultado] == nomes


# ════════════════════════════════════════════════════════════════════════════
# _processar_ativo_async  (lógica por ativo — mock em _req_cnpj_async e _get_dados_complementares_async)
# ════════════════════════════════════════════════════════════════════════════
class TestProcessarAtivoAsync:
    _CNPJ_RESP = [{
        "primeirosResultados": [{
            "itemSelecionavel": {
                "label": "AMW CASH CLASH FI RENDA FIXA LP",
                "identificador": "612014",
                "tipoItemSelecionavel": "FI",
            }
        }]
    }]
    _COMPLEMENTARES = {
        "CNPJ": "42.550.188/0001-91",
        "GESTAO": "Amw Asset Management",
        "INICIO_DO_FUNDO": "2021-09-10",
        "NOME": "AMW CASH CLASH",
    }

    def setup_method(self):
        self.qs = _make_qs()
        self.qs._req_cnpj_async = AsyncMock(return_value=self._CNPJ_RESP)
        self.qs._get_dados_complementares_async = AsyncMock(return_value=self._COMPLEMENTARES)

    def _run(self, coro):
        return trio.run(lambda: coro)

    def _make_limiter(self, n_tokens: int = 2) -> _RateLimiter:
        """Cria um rate limiter pré-carregado para testes síncronos."""
        limiter = _RateLimiter(rate=100)
        trio.run(limiter.fill, n_tokens)
        return limiter

    def test_retorna_ativo_quantum(self):
        limiter = self._make_limiter()
        async def _run():
            return await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        resultado = trio.run(_run)
        assert isinstance(resultado, AtivoQuantum)

    def test_cnpj_correto(self):
        limiter = self._make_limiter()
        async def _run():
            return await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        assert trio.run(_run).cnpj == "42.550.188/0001-91"

    def test_tipo_correto(self):
        limiter = self._make_limiter()
        async def _run():
            return await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        assert trio.run(_run).tipo == "FI"

    def test_id_quantum_correto(self):
        limiter = self._make_limiter()
        async def _run():
            return await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        assert trio.run(_run).id_quantum == "612014"

    def test_primeira_cota_como_date(self):
        limiter = self._make_limiter()
        async def _run():
            return await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        assert trio.run(_run).primeira_cota == date(2021, 9, 10)

    def test_chama_req_cnpj_async_com_cnpj_correto(self):
        limiter = self._make_limiter()
        async def _run():
            await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        trio.run(_run)
        self.qs._req_cnpj_async.assert_called_once()
        assert self.qs._req_cnpj_async.call_args[0][0] == "42.550.188/0001-91"

    def test_chama_get_dados_complementares_async_com_tipo_e_id_corretos(self):
        limiter = self._make_limiter()
        async def _run():
            await self.qs._processar_ativo_async(
                Ativo(cnpj="42.550.188/0001-91"), MagicMock(), limiter
            )
        trio.run(_run)
        self.qs._get_dados_complementares_async.assert_called_once()
        call_args = self.qs._get_dados_complementares_async.call_args[0]
        assert call_args[0] == "FI"
        assert call_args[1] == "612014"


# ════════════════════════════════════════════════════════════════════════════
# raspar_dados
# ════════════════════════════════════════════════════════════════════════════
class TestRasparDados:
    def setup_method(self):
        self.qs = _make_qs()
        self.ativo = AtivoQuantum(nome="Carteira 1", tipo="PORTFOLIO")
        self.df_rent = pd.DataFrame({"hoje": ["2024-01-02"], "valor": [100.5]})
        self.resposta_api = {"responseList": [{"body": '{"serie":[]}'}]}

        self.qs.get_retorno_carteira = MagicMock(return_value=self.resposta_api)
        self.qs.monta_df_rentabilidade_diaria = MagicMock(return_value=self.df_rent)

    def test_retorna_tupla_com_tres_elementos(self):
        resultado = self.qs.raspar_dados(date(2024, 1, 1), date(2024, 12, 31), self.ativo)
        assert len(resultado) == 3

    def test_primeiro_elemento_e_df_de_rentabilidade(self):
        rent, _, _ = self.qs.raspar_dados(date(2024, 1, 1), date(2024, 12, 31), self.ativo)
        pd.testing.assert_frame_equal(rent, self.df_rent)

    def test_segundo_e_terceiro_elementos_sao_dataframes_vazios(self):
        _, vol1, vol2 = self.qs.raspar_dados(date(2024, 1, 1), date(2024, 12, 31), self.ativo)
        assert isinstance(vol1, pd.DataFrame) and vol1.empty
        assert isinstance(vol2, pd.DataFrame) and vol2.empty

    def test_chama_get_retorno_carteira_com_datas_e_ativo_corretos(self):
        di, df = date(2024, 1, 1), date(2024, 12, 31)
        self.qs.raspar_dados(di, df, self.ativo)
        self.qs.get_retorno_carteira.assert_called_once_with(di, df, self.ativo)

    def test_repassa_resposta_da_api_para_monta_df(self):
        self.qs.raspar_dados(date(2024, 1, 1), date(2024, 12, 31), self.ativo)
        self.qs.monta_df_rentabilidade_diaria.assert_called_once_with(self.resposta_api)

    def test_df_rentabilidade_vazio_nao_levanta_excecao(self):
        self.qs.monta_df_rentabilidade_diaria.return_value = pd.DataFrame()
        rent, _, _ = self.qs.raspar_dados(date(2024, 1, 1), date(2024, 12, 31), self.ativo)
        assert rent.empty


# ════════════════════════════════════════════════════════════════════════════
# scrap
# ════════════════════════════════════════════════════════════════════════════
class TestScrap:
    def setup_method(self):
        self.qs = _make_qs()
        self.df_a = pd.DataFrame({"hoje": ["2024-01-02"], "valor": [100.0]})
        self.df_b = pd.DataFrame({"hoje": ["2024-01-02"], "valor": [200.0]})
        self.qs.raspar_dados = MagicMock(
            side_effect=[
                (self.df_a, pd.DataFrame(), pd.DataFrame()),
                (self.df_b, pd.DataFrame(), pd.DataFrame()),
                (self.df_a, pd.DataFrame(), pd.DataFrame()),
            ]
        )

    def test_define_data_inicio_e_data_fim_na_instancia(self):
        self.qs.scrap(
            [AtivoQuantum(nome="A", tipo="PORTFOLIO")],
            date(2023, 1, 1),
            date(2024, 12, 31),
        )
        assert self.qs.data_inicio == date(2023, 1, 1)
        assert self.qs.data_fim == date(2024, 12, 31)

    def test_popula_dfs_rentabilidades_para_cada_ativo(self):
        ativos = [
            AtivoQuantum(nome="A", tipo="PORTFOLIO"),
            AtivoQuantum(nome="B", tipo="PORTFOLIO"),
        ]
        self.qs.scrap(ativos, date(2023, 1, 1), date(2024, 12, 31))
        assert len(self.qs.dfs_rentabilidades) == 2

    def test_popula_lista_ativos_com_nomes(self):
        ativos = [
            AtivoQuantum(nome="FundoX", tipo="PORTFOLIO"),
            AtivoQuantum(nome="FundoY", tipo="PORTFOLIO"),
        ]
        self.qs.scrap(ativos, date(2023, 1, 1), date(2024, 12, 31))
        assert "FundoX" in self.qs.ativos
        assert "FundoY" in self.qs.ativos

    def test_chama_raspar_dados_uma_vez_por_ativo(self):
        ativos = [
            AtivoQuantum(nome="A", tipo="PORTFOLIO"),
            AtivoQuantum(nome="B", tipo="PORTFOLIO"),
        ]
        self.qs.scrap(ativos, date(2023, 1, 1), date(2024, 12, 31))
        assert self.qs.raspar_dados.call_count == 2

    def test_respeita_data_inicio_do_fundo_mais_novo(self):
        """primeira_cota > data_inicio → raspar_dados recebe a data do fundo."""
        ativo = AtivoQuantum(
            nome="FundoNovo", tipo="FI",
            primeira_cota=date(2023, 6, 1),
        )
        self.qs.scrap([ativo], date(2022, 1, 1), date(2024, 12, 31))
        data_usada = self.qs.raspar_dados.call_args[0][0]
        assert data_usada == date(2023, 6, 1)

    def test_usa_data_solicitada_quando_fundo_e_mais_antigo(self):
        ativo = AtivoQuantum(
            nome="FundoAntigo", tipo="FI",
            primeira_cota=date(2010, 1, 1),
        )
        self.qs.scrap([ativo], date(2022, 1, 1), date(2024, 12, 31))
        data_usada = self.qs.raspar_dados.call_args[0][0]
        assert data_usada == date(2022, 1, 1)


# ════════════════════════════════════════════════════════════════════════════
# salvar_retonos
# ════════════════════════════════════════════════════════════════════════════
class TestSalvarRetonos:
    def setup_method(self):
        self.qs = _make_qs()
        self.df1 = pd.DataFrame({"a": [1, 2]})
        self.df2 = pd.DataFrame({"a": [3, 4]})
        self.qs.dfs_rentabilidades = [self.df1, self.df2]

    def _setup_writer_mock(self, mock_writer):
        ctx = MagicMock()
        mock_writer.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_writer.return_value.__exit__ = MagicMock(return_value=False)
        self.df1.to_excel = MagicMock()
        self.df2.to_excel = MagicMock()
        return ctx

    @patch("quantum_scrapper.pd.ExcelWriter")
    def test_cria_arquivo_com_nome_correto(self, mock_writer):
        self._setup_writer_mock(mock_writer)
        self.qs.salvar_retonos(["Ativo A", "Ativo B"])
        mock_writer.assert_called_once_with("rentabilidade_diaria_ativos.xlsx")

    @patch("quantum_scrapper.pd.ExcelWriter")
    def test_escreve_uma_aba_por_ativo(self, mock_writer):
        self._setup_writer_mock(mock_writer)
        self.qs.salvar_retonos(["Ativo A", "Ativo B"])
        self.df1.to_excel.assert_called_once()
        self.df2.to_excel.assert_called_once()

    @patch("quantum_scrapper.pd.ExcelWriter")
    def test_nome_de_aba_truncado_em_31_caracteres(self, mock_writer):
        self._setup_writer_mock(mock_writer)
        nome_longo = "A" * 50
        self.qs.salvar_retonos([nome_longo, nome_longo])
        for df in [self.df1, self.df2]:
            sheet = df.to_excel.call_args[1]["sheet_name"]
            assert len(sheet) <= 31

    @patch("quantum_scrapper.pd.ExcelWriter")
    def test_nome_curto_nao_e_alterado(self, mock_writer):
        self._setup_writer_mock(mock_writer)
        self.qs.salvar_retonos(["Curto", "Outro"])
        sheet = self.df1.to_excel.call_args[1]["sheet_name"]
        assert sheet == "Curto"
