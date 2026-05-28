from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from scrapper.models import Ativo, CarteiraFundo, CotacaoDiaria, PosicaoCarteira


@pytest.mark.django_db
class TestCarteiraFundo:
    def _ativo(self):
        return Ativo.objects.create(tipo="FI", id_quantum="612014", nome="AMW")

    def test_unique_ativo_competencia(self):
        ativo = self._ativo()
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        with pytest.raises(IntegrityError):
            CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))

    def test_ordena_por_competencia_desc(self):
        ativo = self._ativo()
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 3, 1))
        CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        assert ativo.carteiras.first().competencia == date(2026, 4, 1)

    def test_cascade_apaga_posicoes(self):
        ativo = self._ativo()
        carteira = CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        PosicaoCarteira.objects.create(carteira=carteira, nome="LFT 2030", participacao=12.3, ordem=0)
        carteira.delete()
        assert PosicaoCarteira.objects.count() == 0

    def test_posicoes_ordenadas_por_ordem(self):
        ativo = self._ativo()
        carteira = CarteiraFundo.objects.create(ativo=ativo, competencia=date(2026, 4, 1))
        PosicaoCarteira.objects.create(carteira=carteira, nome="B", participacao=5.0, ordem=1)
        PosicaoCarteira.objects.create(carteira=carteira, nome="A", participacao=9.0, ordem=0)
        assert [p.nome for p in carteira.posicoes.all()] == ["A", "B"]


@pytest.mark.django_db
class TestCotacaoDiariaDecimal:
    def test_valor_aceita_decimal_e_retornos_default_zero(self):
        ativo = Ativo.objects.create(tipo="FI", id_quantum="1", nome="X")
        c = CotacaoDiaria.objects.create(
            ativo=ativo, data="2024-01-02", valor=Decimal("100.12345678")
        )
        c.refresh_from_db()
        assert c.valor == Decimal("100.12345678")
        assert c.retorno == Decimal("0")
        assert c.retorno_ln == Decimal("0")
