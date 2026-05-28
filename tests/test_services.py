import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapper.models import Ativo, CarteiraFundo, CotacaoDiaria
from scrapper.quantum.catalogo import TipoAtivo
from scrapper.services import QuantumService, parece_cnpj, seed_indices


def _multiplex_valor(valores: list) -> dict:
    body = json.dumps([{"valor": v} for v in valores])
    return {"responseList": [{"body": body}]}


def _multiplex_serie(pontos: list[tuple[str, str]]) -> dict:
    serie = [{"data": d, "valor": v} for d, v in pontos]
    return {"responseList": [{"body": json.dumps({"serie": serie})}]}


def _multiplex_carteira(itens: list) -> dict:
    return {"responseList": [{"body": json.dumps(itens)}]}


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

_FI_24 = [
    "AMW CASH", "FI", "42.550.188/0001-91", "Amw Asset", "Renda Fixa", "IRF-M",
    "Sim", "Investidores", "0.17", "2.0", "10.0", "100% do CDI", "100.00",
    "D+0", "D+0", "D+0", "Tx: 0%", "2021-09-10", "0.00", "D",
    "Não informado", "Não possui", "FI_LONGO_PRAZO", "true",
]


@pytest.mark.django_db
class TestImportarAtivos:
    def _service(self) -> QuantumService:
        client = MagicMock()
        client.buscar.return_value = _GRUPOS_FI
        client.dados_complementares.return_value = _multiplex_valor(_FI_24)
        svc = QuantumService(client=client)
        svc._logged_in = True
        return svc

    def test_cria_ativo_unico(self):
        svc = self._service()
        resultados = svc.buscar_por_cnpj("42.550.188/0001-91")
        ativos = svc.importar_ativos(resultados)
        assert len(ativos) == 1
        assert Ativo.objects.filter(tipo="FI").count() == 1

    def test_promove_colunas(self):
        svc = self._service()
        resultados = svc.buscar_por_cnpj("42.550.188/0001-91")
        ativo = svc.importar_ativos(resultados)[0]
        assert ativo.cnpj == "42.550.188/0001-91"
        assert ativo.gestora == "Amw Asset"
        assert ativo.primeira_cota == date(2021, 9, 10)
        assert ativo.tipo == "FI"
        assert ativo.id_quantum == "612014"

    def test_idempotente_por_chave_natural(self):
        svc = self._service()
        resultados = svc.buscar_por_cnpj("42.550.188/0001-91")
        svc.importar_ativos(resultados)
        svc.importar_ativos(resultados)
        assert Ativo.objects.filter(tipo="FI").count() == 1


@pytest.mark.django_db
class TestColetarSerie:
    def test_salva_cotacoes(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([
            ("2024-01-02", "100.0"), ("2024-01-03", "100.5"),
        ])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")
        n = svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        assert n == 2
        assert CotacaoDiaria.objects.filter(ativo=ativo).count() == 2

    def test_upsert_nao_duplica(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([("2024-01-02", "100.0")])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        assert CotacaoDiaria.objects.filter(ativo=ativo).count() == 1

    def test_clamp_usa_primeira_cota_quando_posterior_ao_inicio(self):
        # primeira_cota > data_inicio: a coleta começa na primeira_cota.
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(
            tipo="FI", id_quantum="1", nome="X", primeira_cota=date(2024, 6, 1),
        )
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        di_chamado = client.serie.call_args[0][2]
        assert di_chamado == date(2024, 6, 1)

    def test_clamp_usa_data_inicio_quando_sem_primeira_cota(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="2", nome="Y")
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        di_chamado = client.serie.call_args[0][2]
        assert di_chamado == date(2024, 1, 1)


@pytest.mark.django_db
class TestColetarCarteira:
    def test_rejeita_tipo_nao_fi(self):
        client = MagicMock()
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FII", id_quantum="1", nome="FII X")
        with pytest.raises(ValueError, match="apenas para fundos"):
            svc.coletar_carteira(ativo)

    def test_persiste_posicoes(self):
        client = MagicMock()
        client.carteira.return_value = _multiplex_carteira([
            {"ativo": "LFT 2030", "participacao": "12.3"},
            {"ativo": "NTN-B 2028", "participacao": "9.8"},
        ])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")
        carteira = svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        assert carteira.posicoes.count() == 2
        assert carteira.posicoes.first().nome == "LFT 2030"
        assert carteira.posicoes.first().ordem == 0

    def test_upsert_substitui_posicoes_antigas(self):
        client = MagicMock()
        client.carteira.return_value = _multiplex_carteira([{"ativo": "A", "participacao": "1"}])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        client.carteira.return_value = _multiplex_carteira([
            {"ativo": "B", "participacao": "2"}, {"ativo": "C", "participacao": "3"},
        ])
        carteira = svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        assert CarteiraFundo.objects.filter(ativo=ativo).count() == 1
        assert [p.nome for p in carteira.posicoes.all()] == ["B", "C"]


@pytest.mark.django_db
class TestSeedIndices:
    def test_cria_nove_indices(self):
        seed_indices()
        assert Ativo.objects.filter(tipo="INDICE").count() == 9

    def test_cdi_presente(self):
        seed_indices()
        cdi = Ativo.objects.get(tipo="INDICE", id_quantum="1")
        assert cdi.nome == "CDI"

    def test_idempotente(self):
        seed_indices()
        seed_indices()
        assert Ativo.objects.filter(tipo="INDICE").count() == 9


class TestPareceCnpj:
    @pytest.mark.parametrize("termo", [
        "42.550.188/0001-91",  # mascarado
        "42550188000191",      # 14 dígitos crus
        " 42550188000191 ",    # com espaços
    ])
    def test_reconhece_cnpj(self, termo):
        assert parece_cnpj(termo) is True

    @pytest.mark.parametrize("termo", [
        "HASH11",          # ETF
        "PETR4",           # ação
        "Fundo XP",        # nome
        "IVVB11",          # FII/ETF
        "",                # vazio
    ])
    def test_rejeita_texto(self, termo):
        assert parece_cnpj(termo) is False


@pytest.mark.django_db
class TestBuscarTermo:
    def test_ticker_usa_busca_por_texto(self):
        client = MagicMock()
        client.buscar.return_value = []
        svc = QuantumService(client=client)
        svc._logged_in = True
        svc.buscar_termo("HASH11")
        # texto: is_cnpj=False na primeira (e única) tentativa após fallback vazio
        chamadas = [c.kwargs.get("is_cnpj") for c in client.buscar.call_args_list]
        assert chamadas[0] is False

    def test_cnpj_usa_busca_por_cnpj(self):
        client = MagicMock()
        client.buscar.return_value = []
        svc = QuantumService(client=client)
        svc._logged_in = True
        svc.buscar_termo("42.550.188/0001-91")
        chamadas = [c.kwargs.get("is_cnpj") for c in client.buscar.call_args_list]
        assert chamadas[0] is True

    def test_fallback_para_texto_quando_cnpj_vazio(self):
        client = MagicMock()
        client.buscar.side_effect = [[], _GRUPOS_FI]  # cnpj vazio -> texto
        svc = QuantumService(client=client)
        svc._logged_in = True
        resultados = svc.buscar_termo("42.550.188/0001-91")
        assert resultados  # achou no fallback
        chamadas = [c.kwargs.get("is_cnpj") for c in client.buscar.call_args_list]
        assert chamadas == [True, False]


@pytest.mark.django_db
class TestLoginLazy:
    def test_login_chamado_na_primeira_rede(self):
        client = MagicMock()
        client.buscar.return_value = []
        svc = QuantumService(client=client)
        svc.buscar_por_texto("X")
        client.login.assert_called_once()

    def test_login_nao_repetido(self):
        client = MagicMock()
        client.buscar.return_value = []
        svc = QuantumService(client=client)
        svc.buscar_por_texto("X")
        svc.buscar_por_texto("Y")
        client.login.assert_called_once()


@pytest.mark.django_db
class TestImportarSemMedidas:
    """Tipos sem card de medidas (INDICE/RENDA_FIXA) não disparam a chamada
    de dados_complementares — evita um POST inútil com corpo vazio."""

    _GRUPOS_RF = [{
        "codigoGrupo": 0,
        "primeirosResultados": [{
            "itemSelecionavel": {
                "label": "VALE38", "identificador": "VALE38",
                "tipoItemSelecionavel": "RENDA_FIXA",
            },
            "informacaoAdicional": "Type: Debênture",
            "codigoGrupo": 0,
        }],
    }]

    def test_renda_fixa_nao_chama_dados_complementares(self):
        client = MagicMock()
        client.buscar.return_value = self._GRUPOS_RF
        svc = QuantumService(client=client)
        svc._logged_in = True
        resultados = svc.buscar_por_texto("VALE38")
        ativos = svc.importar_ativos(resultados)
        assert len(ativos) == 1
        assert ativos[0].tipo == "RENDA_FIXA"
        assert ativos[0].id_quantum == "VALE38"
        client.dados_complementares.assert_not_called()
