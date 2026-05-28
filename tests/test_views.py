from datetime import date
from unittest.mock import MagicMock

import pytest

from scrapper.models import Ativo, CarteiraFundo, CotacaoDiaria, Job, PosicaoCarteira
from scrapper.quantum.schemas import ResultadoBusca
from scrapper.views import _candidato_para_json, _resultado_de_request


class TestCandidatoParaJson:
    def test_fi_com_cnpj(self):
        r = ResultadoBusca(
            label="AMW CASH", tipo="FI", id_quantum="612014",
            cnpj="42.550.188/0001-91",
        )
        payload = _candidato_para_json(r)
        assert payload == {
            "id_quantum": "612014",
            "tipo": "FI",
            "tipo_label": "Fundo de Investimento",
            "nome": "AMW CASH",
            "cnpj": "42.550.188/0001-91",
            "subtipo": "",
            "ja_cadastrado": False,
        }

    def test_acao_etf_sem_cnpj(self):
        r = ResultadoBusca(
            label="HASH11", tipo="ACAO", id_quantum="999", subtipo="ETF",
        )
        payload = _candidato_para_json(r)
        assert payload["tipo_label"] == "ETF"
        assert payload["cnpj"] == ""
        assert payload["subtipo"] == "ETF"

    def test_marca_ja_cadastrado(self):
        r = ResultadoBusca(label="X", tipo="FI", id_quantum="1")
        assert _candidato_para_json(r, ja_cadastrado=True)["ja_cadastrado"] is True


class TestResultadoDeRequest:
    def test_reconstroi_resultado(self):
        r = _resultado_de_request({
            "id_quantum": "612014", "tipo": "FI",
            "nome": "AMW CASH", "cnpj": "42.550.188/0001-91", "subtipo": "",
        })
        assert isinstance(r, ResultadoBusca)
        assert r.id_quantum == "612014"
        assert r.tipo == "FI"
        assert r.label == "AMW CASH"
        assert r.cnpj == "42.550.188/0001-91"
        assert r.subtipo is None

    def test_subtipo_vazio_vira_none(self):
        r = _resultado_de_request({
            "id_quantum": "1", "tipo": "ACAO", "nome": "X", "subtipo": "BDR",
        })
        assert r.subtipo == "BDR"


@pytest.mark.django_db
class TestBuscarCandidatosView:
    def _mock_service(self, monkeypatch, resultados):
        fake = MagicMock()
        fake.buscar_termo.return_value = resultados
        monkeypatch.setattr("scrapper.views.QuantumService", lambda: fake)
        return fake

    def test_retorna_candidatos(self, client, monkeypatch):
        self._mock_service(monkeypatch, [
            ResultadoBusca(label="AMW", tipo="FI", id_quantum="612014",
                           cnpj="42.550.188/0001-91"),
        ])
        resp = client.post("/buscar-candidatos/", {"termo": "amw"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["candidatos"]) == 1
        assert data["candidatos"][0]["tipo_label"] == "Fundo de Investimento"

    def test_termo_vazio_400(self, client, monkeypatch):
        self._mock_service(monkeypatch, [])
        resp = client.post("/buscar-candidatos/", {"termo": "  "})
        assert resp.status_code == 400

    def test_sem_resultados_lista_vazia(self, client, monkeypatch):
        self._mock_service(monkeypatch, [])
        resp = client.post("/buscar-candidatos/", {"termo": "zzz"})
        assert resp.status_code == 200
        assert resp.json()["candidatos"] == []

    def test_marca_candidato_ja_cadastrado(self, client, monkeypatch):
        Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")
        self._mock_service(monkeypatch, [
            ResultadoBusca(label="AMW", tipo="FI", id_quantum="612014"),
            ResultadoBusca(label="Outro", tipo="FI", id_quantum="999"),
        ])
        resp = client.post("/buscar-candidatos/", {"termo": "amw"})
        por_id = {c["id_quantum"]: c for c in resp.json()["candidatos"]}
        assert por_id["612014"]["ja_cadastrado"] is True
        assert por_id["999"]["ja_cadastrado"] is False

    def test_mesmo_id_tipo_diferente_nao_marca(self, client, monkeypatch):
        # A chave natural é (tipo, id_quantum): id igual em tipo diferente não colide.
        Ativo.objects.create(tipo="ACAO", id_quantum="612014", nome="X")
        self._mock_service(monkeypatch, [
            ResultadoBusca(label="AMW", tipo="FI", id_quantum="612014"),
        ])
        resp = client.post("/buscar-candidatos/", {"termo": "amw"})
        assert resp.json()["candidatos"][0]["ja_cadastrado"] is False


@pytest.mark.django_db
class TestAdicionarAtivoView:
    def _setup(self, monkeypatch):
        fake = MagicMock()
        fake.importar_ativos.return_value = [
            Ativo(tipo="FI", id_quantum="612014", nome="AMW CASH"),
        ]
        monkeypatch.setattr("scrapper.views.QuantumService", lambda: fake)
        # Executa a thread de forma síncrona para inspecionar o efeito.
        monkeypatch.setattr(
            "scrapper.views.threading.Thread",
            lambda target, daemon=None: MagicMock(start=target),
        )
        return fake

    def test_importa_candidato_selecionado(self, client, monkeypatch):
        fake = self._setup(monkeypatch)
        resp = client.post("/adicionar-ativo/", {
            "id_quantum": "612014", "tipo": "FI", "nome": "AMW CASH",
            "cnpj": "42.550.188/0001-91", "subtipo": "",
        })
        assert resp.status_code == 200
        assert "job_id" in resp.json()
        # Importou exatamente o candidato reconstruído.
        (resultados,), _ = fake.importar_ativos.call_args
        assert resultados[0].id_quantum == "612014"
        assert resultados[0].tipo == "FI"
        assert Job.objects.filter(tipo="buscar_ativos", status="done").exists()

    def test_sem_id_quantum_400(self, client, monkeypatch):
        self._setup(monkeypatch)
        resp = client.post("/adicionar-ativo/", {"tipo": "FI", "nome": "X"})
        assert resp.status_code == 400

    def test_sem_tipo_400(self, client, monkeypatch):
        self._setup(monkeypatch)
        resp = client.post("/adicionar-ativo/", {"id_quantum": "1", "nome": "X"})
        assert resp.status_code == 400

    def test_nao_reimporta_ativo_ja_cadastrado(self, client, monkeypatch):
        fake = self._setup(monkeypatch)
        Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")
        resp = client.post("/adicionar-ativo/", {
            "id_quantum": "612014", "tipo": "FI", "nome": "AMW", "subtipo": "",
        })
        assert resp.status_code == 200
        assert "job_id" not in resp.json()
        assert "cadastrado" in resp.json()["mensagem"].lower()
        fake.importar_ativos.assert_not_called()


@pytest.mark.django_db
class TestAtivosListView:
    def test_resumo_conta_por_grupo_excluindo_indice(self, client):
        Ativo.objects.create(tipo="FI", id_quantum="1", nome="A")
        Ativo.objects.create(tipo="FII", id_quantum="2", nome="B")
        Ativo.objects.create(tipo="ACAO", id_quantum="3", nome="C")
        Ativo.objects.create(tipo="RENDA_FIXA", id_quantum="4", nome="D")
        Ativo.objects.create(tipo="INDICE", id_quantum="5", nome="CDI")

        resumo = client.get("/ativos/").context["resumo"]

        assert resumo["total"] == 4  # INDICE não conta
        assert resumo["fundos"] == 2  # FI + FII
        assert resumo["acoes"] == 1
        assert resumo["renda_fixa"] == 1

    def test_anota_num_cotas_e_ultima_cota(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="1", nome="A")
        CotacaoDiaria.objects.create(ativo=a, data=date(2026, 1, 1), valor=100.0)
        CotacaoDiaria.objects.create(ativo=a, data=date(2026, 1, 2), valor=101.0)
        Ativo.objects.create(tipo="FI", id_quantum="2", nome="B")  # sem cotas

        por_nome = {x.nome: x for x in client.get("/ativos/").context["ativos"]}

        assert por_nome["A"].num_cotas == 2
        assert por_nome["A"].ultima_cota == date(2026, 1, 2)
        assert por_nome["B"].num_cotas == 0
        assert por_nome["B"].ultima_cota is None

    def test_exclui_indice_da_listagem(self, client):
        Ativo.objects.create(tipo="INDICE", id_quantum="5", nome="CDI")
        assert list(client.get("/ativos/").context["ativos"]) == []


@pytest.mark.django_db
class TestRelatorioPreselecao:
    def test_preseleciona_apenas_ids_do_get(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="1", nome="A")
        Ativo.objects.create(tipo="FI", id_quantum="2", nome="B")

        # Só ids, sem datas: cai no ramo de seleção (renderiza relatorio.html).
        ctx = client.get(f"/relatorio/?ids={a.id}").context

        assert ctx["preselecionados"] == {a.id}

    def test_sem_ids_preselecao_vazia(self, client):
        ctx = client.get("/relatorio/").context
        assert ctx["preselecionados"] == set()


@pytest.mark.django_db
class TestDetalheAtivo:
    def test_404_para_id_inexistente(self, client):
        assert client.get("/ativos/99999/").status_code == 404

    def test_200_e_contexto(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="1", nome="AMW")
        CotacaoDiaria.objects.create(ativo=a, data=date(2024, 1, 2), valor=100.0)
        CotacaoDiaria.objects.create(ativo=a, data=date(2024, 1, 3), valor=101.0)
        ctx = client.get(f"/ativos/{a.id}/").context
        assert ctx["ativo"].id == a.id
        assert ctx["num_cotas"] == 2
        assert ctx["pode_ter_carteira"] is True

    def test_acao_nao_pode_ter_carteira(self, client):
        a = Ativo.objects.create(tipo="ACAO", id_quantum="2", nome="PETR4")
        ctx = client.get(f"/ativos/{a.id}/").context
        assert ctx["pode_ter_carteira"] is False

    def test_carteira_atual_no_contexto(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="3", nome="X")
        c = CarteiraFundo.objects.create(ativo=a, competencia=date(2026, 4, 1))
        PosicaoCarteira.objects.create(carteira=c, nome="LFT", participacao=10.0, ordem=0)
        ctx = client.get(f"/ativos/{a.id}/").context
        assert ctx["carteira"].id == c.id
        assert ctx["carteira"].posicoes.count() == 1


@pytest.mark.django_db
class TestExcluirAtivoView:
    def test_exclui_ativo_e_cotacoes_em_cascata(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="1", nome="A")
        CotacaoDiaria.objects.create(ativo=a, data=date(2026, 1, 1), valor=100.0)
        CotacaoDiaria.objects.create(ativo=a, data=date(2026, 1, 2), valor=101.0)

        resp = client.post(f"/ativos/{a.id}/excluir/")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert not Ativo.objects.filter(id=a.id).exists()
        assert CotacaoDiaria.objects.filter(ativo_id=a.id).count() == 0

    def test_id_inexistente_404(self, client):
        assert client.post("/ativos/99999/excluir/").status_code == 404

    def test_get_nao_permitido(self, client):
        a = Ativo.objects.create(tipo="FI", id_quantum="1", nome="A")
        assert client.get(f"/ativos/{a.id}/excluir/").status_code == 405


@pytest.mark.django_db
class TestAtualizarCarteira:
    def test_400_para_nao_fi(self, client):
        a = Ativo.objects.create(tipo="FII", id_quantum="1", nome="FII X")
        resp = client.post(f"/ativos/{a.id}/carteira/atualizar/")
        assert resp.status_code == 400

    def test_200_para_fi(self, client, monkeypatch):
        a = Ativo.objects.create(tipo="FI", id_quantum="2", nome="AMW")

        def fake_coletar(self, ativo, competencia=None):
            from scrapper.models import CarteiraFundo
            from datetime import date as d
            return CarteiraFundo.objects.create(ativo=ativo, competencia=d(2026, 4, 1))

        monkeypatch.setattr("scrapper.views.QuantumService.coletar_carteira", fake_coletar)
        resp = client.post(f"/ativos/{a.id}/carteira/atualizar/")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_erro_de_rede_502(self, client, monkeypatch):
        a = Ativo.objects.create(tipo="FI", id_quantum="3", nome="X")

        def fake_coletar(self, ativo, competencia=None):
            raise RuntimeError("falha de rede")

        monkeypatch.setattr("scrapper.views.QuantumService.coletar_carteira", fake_coletar)
        resp = client.post(f"/ativos/{a.id}/carteira/atualizar/")
        assert resp.status_code == 502
        assert "erro" in resp.json()
