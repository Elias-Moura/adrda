from datetime import date

import pytest
from pydantic import ValidationError

from scrapper.quantum.catalogo import TipoAtivo
from scrapper.quantum.schemas import (
    AtivoQuantum,
    MetaACAO,
    MetaFI,
    PontoSerie,
    ResultadoBusca,
    SerieDiaria,
)


class TestResultadoBusca:
    def test_id_quantum_string_renda_fixa(self):
        r = ResultadoBusca(label="VALE38", tipo=TipoAtivo.RENDA_FIXA, id_quantum="VALE38")
        assert r.id_quantum == "VALE38"

    def test_id_quantum_numerico_coagido_para_string(self):
        r = ResultadoBusca(label="X", tipo=TipoAtivo.FI, id_quantum=612014)
        assert r.id_quantum == "612014"

    def test_campos_opcionais_default_none(self):
        r = ResultadoBusca(label="X", tipo=TipoAtivo.FI, id_quantum="1")
        assert r.cnpj is None and r.subtipo is None
        assert r.codigo_grupo == 0

    def test_id_quantum_none_e_rejeitado(self):
        with pytest.raises(ValidationError):
            ResultadoBusca(label="X", tipo=TipoAtivo.FI, id_quantum=None)


class TestMetadadosTolerantes:
    def test_meta_fi_aceita_campo_faltante(self):
        meta = MetaFI(NOME="Fundo X")
        assert meta.NOME == "Fundo X"
        assert meta.CNPJ is None

    def test_meta_fi_ignora_campo_extra(self):
        meta = MetaFI(NOME="X", CAMPO_NOVO_DO_QUANTUM="valor")
        assert not hasattr(meta, "CAMPO_NOVO_DO_QUANTUM")

    def test_meta_acao_tem_ticker_e_setor(self):
        meta = MetaACAO(TICKER="VALE3", SETOR_QUANTUM="Mineração")
        assert meta.TICKER == "VALE3"
        assert meta.SETOR_QUANTUM == "Mineração"


class TestSerieDiaria:
    def test_ponto_serie(self):
        p = PontoSerie(data=date(2025, 5, 26), valor=100.0)
        assert p.valor == 100.0

    def test_serie_vazia_default(self):
        assert SerieDiaria().pontos == []


class TestAtivoQuantum:
    def test_dominio_minimo(self):
        aq = AtivoQuantum(
            tipo=TipoAtivo.FI, id_quantum="612014", nome="Fundo X",
            metadados=MetaFI(NOME="Fundo X"),
        )
        assert aq.id_quantum == "612014"
        assert aq.primeira_cota is None


class TestCarteiraSchema:
    def test_posicao_aceita_participacao_float(self):
        from scrapper.quantum.schemas import PosicaoCarteira as PosicaoSchema
        p = PosicaoSchema(nome="LFT 2030", participacao=12.34)
        assert p.participacao == 12.34

    def test_posicao_coage_participacao_string(self):
        from scrapper.quantum.schemas import PosicaoCarteira as PosicaoSchema
        p = PosicaoSchema(nome="LFT 2030", participacao="12.3351017")
        assert round(p.participacao, 4) == 12.3351

    def test_carteira_vazia_por_padrao(self):
        from scrapper.quantum.schemas import Carteira
        c = Carteira()
        assert c.posicoes == []
        assert c.competencia is None
