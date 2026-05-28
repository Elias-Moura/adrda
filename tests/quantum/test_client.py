import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapper.quantum.catalogo import TipoAtivo
from scrapper.quantum.client import QuantumClient


def _make_client(token: str = "Bearer fake") -> QuantumClient:
    c = object.__new__(QuantumClient)
    c.token = token
    c._client = MagicMock()
    return c


class TestCicloDeVida:
    def test_close_fecha_a_sessao(self):
        c = _make_client()
        c.close()
        c._client.close.assert_called_once()

    def test_context_manager_fecha_ao_sair(self):
        c = _make_client()
        with c as ctx:
            assert ctx is c
        c._client.close.assert_called_once()


class TestBuscar:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.get.return_value.status_code = 200
        self.c._client.get.return_value.json.return_value = [{"codigoGrupo": 0}]

    def test_busca_por_texto_usa_iscnpj_false(self):
        self.c.buscar("HASH11", is_cnpj=False)
        url = self.c._client.get.call_args[0][0]
        assert "isCNPJ=false" in url

    def test_busca_por_cnpj_usa_iscnpj_true(self):
        self.c.buscar("42.550.188/0001-91", is_cnpj=True)
        url = self.c._client.get.call_args[0][0]
        assert "isCNPJ=true" in url

    def test_devolve_dict_cru(self):
        assert self.c.buscar("X") == [{"codigoGrupo": 0}]

    def test_erro_http_levanta_value_error(self):
        self.c._client.get.return_value.status_code = 500
        self.c._client.get.return_value.text = "erro"
        with pytest.raises(ValueError, match="500"):
            self.c.buscar("X")


class TestDadosComplementares:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.post.return_value.status_code = 200
        self.c._client.post.return_value.json.return_value = {"responseList": [{"body": "[]"}]}

    def test_envia_ordem_de_medidas_do_tipo_acao(self):
        self.c.dados_complementares(TipoAtivo.ACAO, "700")
        payload = self.c._client.post.call_args[1]["content"]
        assert "TICKER" in payload
        assert "SETOR_QUANTUM" in payload

    def test_relative_url_contem_tipo_e_id(self):
        self.c.dados_complementares(TipoAtivo.FI, "612014")
        payload = self.c._client.post.call_args[1]["content"]
        assert "/api/ativos/FI/612014/medidas/valor" in payload

    def test_token_no_header(self):
        self.c.dados_complementares(TipoAtivo.FI, "1")
        headers = self.c._client.post.call_args[1]["headers"]
        assert headers["authorization"] == self.c.token

    def test_devolve_dict_cru(self):
        assert self.c.dados_complementares(TipoAtivo.FI, "1") == {"responseList": [{"body": "[]"}]}


class TestSerie:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.post.return_value.status_code = 200
        self.c._client.post.return_value.json.return_value = {"responseList": [{"body": '{"serie":[]}'}]}

    def test_payload_contem_datas_e_medida(self):
        self.c.serie(TipoAtivo.FI, "1", date(2024, 1, 1), date(2024, 12, 31))
        payload = self.c._client.post.call_args[1]["content"]
        assert "2024-01-01" in payload
        assert "2024-12-31" in payload
        assert "EVOLUCAO_DO_ATIVO" in payload

    def test_relative_url_serie(self):
        self.c.serie(TipoAtivo.FI, "612014", date(2024, 1, 1), date(2024, 12, 31))
        payload = self.c._client.post.call_args[1]["content"]
        assert "/api/ativos/FI/612014/medidas/serie" in payload

    def test_devolve_dict_cru(self):
        out = self.c.serie(TipoAtivo.FI, "1", date(2024, 1, 1), date(2024, 12, 31))
        assert out == {"responseList": [{"body": '{"serie":[]}'}]}


class TestCarteira:
    def setup_method(self):
        self.c = _make_client()
        self.c._client.post.return_value.status_code = 200
        self.c._client.post.return_value.json.return_value = {"responseList": [{"body": "[]"}]}

    def test_monta_relative_url_de_carteira(self):
        self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1))
        enviado = self.c._client.post.call_args.kwargs["content"]
        assert "/api/ativos/FI/612014/carteira" in enviado
        assert "tipoCarteira=INDIVIDUAL" in enviado
        assert "quantidade=100" in enviado
        assert "dataCompetencia=2026-04-01" in enviado

    def test_usa_metodo_get_no_multiplex(self):
        # A API rejeita POST no request interno com 405 (Allow: GET) — travado aqui.
        self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1))
        enviado = self.c._client.post.call_args.kwargs["content"]
        assert '"method": "GET"' in enviado

    def test_devolve_dict_cru(self):
        assert self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1)) == {
            "responseList": [{"body": "[]"}]
        }

    def test_erro_http_levanta_value_error(self):
        self.c._client.post.return_value.status_code = 500
        self.c._client.post.return_value.text = "erro"
        with pytest.raises(ValueError, match="500"):
            self.c.carteira(TipoAtivo.FI, "612014", date(2026, 4, 1))
