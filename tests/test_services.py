import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from scrapper.models import Ativo, CarteiraFundo, CotacaoDiaria
from scrapper.quantum.catalogo import TipoAtivo
from scrapper.services import QuantumService, calcular_retornos_serie, parece_cnpj, recalcular_retornos, seed_indices


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


class TestCalcularRetornosSerie:
    def test_serie_vazia(self):
        assert calcular_retornos_serie([]) == []

    def test_primeiro_ponto_zero(self):
        r = calcular_retornos_serie([Decimal("100")])
        assert r == [(Decimal(0), Decimal(0))]

    def test_retorno_simples_e_log(self):
        r = calcular_retornos_serie([Decimal("100"), Decimal("110")])
        assert r[0] == (Decimal(0), Decimal(0))
        retorno, retorno_ln = r[1]
        assert retorno == Decimal("0.1")  # 110/100 - 1
        # ln(1.1) ≈ 0.0953101798...
        assert abs(retorno_ln - Decimal("0.09531017980432486")) < Decimal("1e-15")

    def test_valor_anterior_zero_nao_quebra(self):
        r = calcular_retornos_serie([Decimal("0"), Decimal("100")])
        assert r == [(Decimal(0), Decimal(0)), (Decimal(0), Decimal(0))]


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

    def test_persiste_decimal_e_calcula_retornos(self):
        client = MagicMock()
        client.serie.return_value = _multiplex_serie([
            ("2024-01-02", "100.0"), ("2024-01-03", "110.0"),
        ])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="9", nome="Z")
        svc.coletar_serie(ativo, date(2024, 1, 1), date(2024, 12, 31))
        cotas = list(ativo.cotacoes.order_by("data"))
        assert isinstance(cotas[0].valor, Decimal)
        assert cotas[0].retorno == Decimal("0")
        assert cotas[1].retorno == Decimal("0.1")


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
        assert carteira.posicoes.first().participacao == 12.3
        assert carteira.posicoes.first().ordem == 0

    def test_carteira_vazia_persiste_sem_posicoes(self):
        # Fundo sem composição publicada: a API real retorna [] (caso válido).
        client = MagicMock()
        client.carteira.return_value = _multiplex_carteira([])
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="2", nome="Vazio")
        carteira = svc.coletar_carteira(ativo, competencia=date(2026, 4, 1))
        assert CarteiraFundo.objects.filter(ativo=ativo).count() == 1
        assert carteira.posicoes.count() == 0

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


def _html_carteira(competencia_sel: str, datas: list[str], posicoes: list[tuple]) -> str:
    """Monta um HTML .qt mínimo para mockar abrir/trocar competência."""
    opts = "".join(
        f'<option {"selected" if d == competencia_sel else ""} value="{d}">{d}</option>'
        for d in datas
    )
    linhas = "".join(
        f'<TR><TD><a href="javascript: exibirDetalhes(\'{i:08X}-0000-0000-0000-000000000000\')">'
        f'<font>{nome}</font></a></TD>'
        f'<TD><font> <font>{valor}</font> </font></TD>'
        f'<TD><font> <font>{pct} %</font> </font></TD></TR>'
        for i, (nome, valor, pct) in enumerate(posicoes)
    )
    return (
        '<script>"&chave=db5bed57-5b20-4f20-a164-9df8b9a9e22e&codigo=1"</script>'
        f'<select id="datas">{opts}</select>'
        '<td><font color="#004379">Asset Type</font></td>'
        '<td><font color="#004379">Government Bonds</font></td><td><font color="#004379">100.00 %</font></td>'
        '<td><font color="#004379">&nbsp;Portfolio Composition</font></td>'
        f'<table>{linhas}</table>'
    )


@pytest.mark.django_db
class TestSincronizarCarteiras:
    def test_rejeita_nao_fi(self):
        svc = QuantumService(client=MagicMock())
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="ACAO", id_quantum="1", nome="PETR4")
        with pytest.raises(ValueError, match="apenas para fundos"):
            svc.sincronizar_carteiras(ativo)

    def test_itera_todas_as_competencias(self):
        client = MagicMock()
        client.abrir_carteira_fundo.return_value = _html_carteira(
            "04/30/2026", ["04/30/2026", "03/31/2026"],
            [("LFT 2030", "85,517.91", "60.0000"), ("NTN-B", "50,000.00", "40.0000")],
        )
        client.trocar_competencia_carteira.return_value = _html_carteira(
            "03/31/2026", ["04/30/2026", "03/31/2026"],
            [("LFT 2029", "10,000.00", "100.0000")],
        )
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")

        competencias = svc.sincronizar_carteiras(ativo)

        assert competencias == [date(2026, 4, 30), date(2026, 3, 31)]
        assert CarteiraFundo.objects.filter(ativo=ativo).count() == 2
        recente = CarteiraFundo.objects.get(ativo=ativo, competencia=date(2026, 4, 30))
        assert recente.posicoes.count() == 2
        p0 = recente.posicoes.first()
        assert p0.nome == "LFT 2030" and p0.valor == 85517.91 and p0.participacao == 60.0
        assert recente.agregacoes["tipo"] == [["Government Bonds", 100.0]]
        # só uma troca de competência (a recente veio da abertura)
        client.trocar_competencia_carteira.assert_called_once()

    def test_incremental_pula_existentes(self):
        client = MagicMock()
        client.abrir_carteira_fundo.return_value = _html_carteira(
            "04/30/2026", ["04/30/2026", "03/31/2026"], [("LFT", "1.00", "100.0000")],
        )
        client.trocar_competencia_carteira.return_value = _html_carteira(
            "03/31/2026", ["04/30/2026", "03/31/2026"], [("LFT", "1.00", "100.0000")],
        )
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        svc.sincronizar_carteiras(ativo)
        client.trocar_competencia_carteira.reset_mock()
        # 2ª chamada: ambas já existem -> nenhuma troca
        svc.sincronizar_carteiras(ativo)
        client.trocar_competencia_carteira.assert_not_called()

    def test_remove_competencias_obsoletas(self):
        client = MagicMock()
        client.abrir_carteira_fundo.return_value = _html_carteira(
            "04/30/2026", ["04/30/2026"], [("LFT", "1.00", "100.0000")],
        )
        svc = QuantumService(client=client)
        svc._logged_in = True
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        # competência legada (bug do dia 1º) que não está no seletor atual
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 5, 1))
        svc.sincronizar_carteiras(ativo)
        comps = list(CarteiraFundo.objects.filter(ativo=ativo).values_list("competencia", flat=True))
        assert comps == [date(2026, 4, 30)]


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


@pytest.mark.django_db
class TestRecalcularRetornos:
    def _ativo_com_serie(self, valores):
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        for i, v in enumerate(valores, start=2):
            CotacaoDiaria.objects.create(
                ativo=ativo, data=f"2024-01-{i:02d}", valor=Decimal(v)
            )
        return ativo

    def test_grava_retornos_da_serie(self):
        ativo = self._ativo_com_serie(["100", "110", "121"])
        n = recalcular_retornos(ativo)
        assert n == 3
        cotas = list(ativo.cotacoes.order_by("data"))
        assert cotas[0].retorno == Decimal("0")
        assert cotas[1].retorno == Decimal("0.1")
        assert cotas[2].retorno == Decimal("0.1")  # 121/110 - 1

    def test_idempotente(self):
        ativo = self._ativo_com_serie(["100", "110"])
        recalcular_retornos(ativo)
        antes = [(c.retorno, c.retorno_ln) for c in ativo.cotacoes.order_by("data")]
        recalcular_retornos(ativo)
        depois = [(c.retorno, c.retorno_ln) for c in ativo.cotacoes.order_by("data")]
        assert antes == depois

    def test_sem_cotas_retorna_zero(self):
        ativo = Ativo.objects.create(tipo="FI", id_quantum="2", nome="Y")
        assert recalcular_retornos(ativo) == 0
