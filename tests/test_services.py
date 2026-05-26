import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapper.models import Ativo, CotacaoDiaria
from scrapper.quantum.catalogo import TipoAtivo
from scrapper.services import QuantumService, seed_indices


def _multiplex_valor(valores: list) -> dict:
    body = json.dumps([{"valor": v} for v in valores])
    return {"responseList": [{"body": body}]}


def _multiplex_serie(pontos: list[tuple[str, str]]) -> dict:
    serie = [{"data": d, "valor": v} for d, v in pontos]
    return {"responseList": [{"body": json.dumps({"serie": serie})}]}


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
