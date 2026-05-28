"""Camada de orquestração: client (HTTP) + parsers (pydantic) + ORM.

Única camada que toca o Django ORM e converte pydantic -> models.
"""
from __future__ import annotations

import re
from datetime import date

from django.db import transaction
from loguru import logger

from scrapper.models import Ativo, CarteiraFundo, CotacaoDiaria, PosicaoCarteira
from scrapper.quantum import parsers
from scrapper.quantum.catalogo import INDICES, MEDIDAS_POR_TIPO, TipoAtivo
from scrapper.quantum.client import QuantumClient
from scrapper.quantum.schemas import AtivoQuantum as AtivoQuantumSchema
from scrapper.quantum.schemas import ResultadoBusca


def parece_cnpj(termo: str) -> bool:
    """Heurística: um CNPJ tem 14 dígitos e nenhuma letra (cru ou mascarado).
    Tickers (HASH11, PETR4) e nomes contêm letras -> busca por texto."""
    if any(c.isalpha() for c in termo):
        return False
    return len(re.sub(r"\D", "", termo)) == 14


class QuantumService:
    """Orquestra busca/import/coleta. Login lazy na primeira chamada de rede."""

    def __init__(self, client: QuantumClient | None = None) -> None:
        self._client = client or QuantumClient()
        self._logged_in = False

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self._client.login()
            self._logged_in = True

    # ── Busca ───────────────────────────────────────────────────────────────
    def buscar_por_texto(self, termo: str) -> list[ResultadoBusca]:
        self._ensure_login()
        return parsers.parse_resultados_busca(self._client.buscar(termo, is_cnpj=False))

    def buscar_por_cnpj(self, cnpj: str) -> list[ResultadoBusca]:
        self._ensure_login()
        return parsers.parse_resultados_busca(self._client.buscar(cnpj, is_cnpj=True))

    def buscar_termo(self, termo: str) -> list[ResultadoBusca]:
        """Busca avulsa por CNPJ ou código/nome. Detecta o tipo do termo e,
        se a busca preferencial vier vazia, tenta a outra como fallback."""
        if parece_cnpj(termo):
            return self.buscar_por_cnpj(termo) or self.buscar_por_texto(termo)
        return self.buscar_por_texto(termo) or self.buscar_por_cnpj(termo)

    # ── Import (rede -> pydantic -> ORM) ──────────────────────────────────────
    def importar_ativos(self, resultados: list[ResultadoBusca]) -> list[Ativo]:
        """Para cada resultado: busca metadados (quando o tipo os tem), monta o
        domínio e persiste. Idempotente via chave natural (tipo, id_quantum)."""
        self._ensure_login()
        ativos: list[Ativo] = []
        for resultado in resultados:
            if MEDIDAS_POR_TIPO.get(resultado.tipo):
                raw = self._client.dados_complementares(resultado.tipo, resultado.id_quantum)
            else:
                # INDICE/RENDA_FIXA não têm card de medidas: evita POST inútil.
                raw = {}
            meta = parsers.parse_metadados(resultado.tipo, raw)
            aq = parsers.montar_ativo(resultado, meta)
            ativos.append(self._persistir(aq))
        return ativos

    @transaction.atomic
    def _persistir(self, aq: AtivoQuantumSchema) -> Ativo:
        ativo, _ = Ativo.objects.update_or_create(
            tipo=aq.tipo.value,
            id_quantum=aq.id_quantum,
            defaults={
                "nome": aq.nome,
                "subtipo": aq.subtipo or "",
                "cnpj": aq.cnpj or "",
                "ticker": aq.ticker or "",
                "setor": aq.setor or "",
                "gestora": aq.gestora or "",
                "primeira_cota": aq.primeira_cota,
                "metadados": aq.metadados.model_dump(),
            },
        )
        return ativo

    # ── Cotas ─────────────────────────────────────────────────────────────────
    def coletar_serie(self, ativo: Ativo, data_inicio: date, data_fim: date) -> int:
        """Coleta a série diária do ativo e faz upsert em CotacaoDiaria."""
        self._ensure_login()
        di = ativo.primeira_cota if (ativo.primeira_cota and ativo.primeira_cota > data_inicio) else data_inicio
        raw = self._client.serie(TipoAtivo(ativo.tipo), ativo.id_quantum, di, data_fim)
        serie = parsers.parse_serie(raw)
        if not serie.pontos:
            return 0
        objs = [
            CotacaoDiaria(ativo=ativo, data=p.data, valor=p.valor)
            for p in serie.pontos
        ]
        CotacaoDiaria.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["ativo", "data"],
            update_fields=["valor"],
        )
        return len(objs)

    def coletar_carteira(self, ativo: Ativo, competencia: date | None = None) -> CarteiraFundo:
        """Coleta a composição da carteira do fundo (FI) e persiste por competência.

        Disponível apenas para FI; FII/Ação levantam ValueError. Idempotente por
        (ativo, competencia): substitui as posições anteriores.
        """
        if ativo.tipo != TipoAtivo.FI:
            raise ValueError("Carteira disponível apenas para fundos (FI).")
        if competencia is None:
            competencia = date.today().replace(day=1)
        self._ensure_login()
        raw = self._client.carteira(TipoAtivo(ativo.tipo), ativo.id_quantum, competencia)
        carteira_dom = parsers.parse_carteira(raw, competencia=competencia)
        with transaction.atomic():
            carteira, _ = CarteiraFundo.objects.update_or_create(
                ativo=ativo, competencia=competencia
            )
            carteira.posicoes.all().delete()
            PosicaoCarteira.objects.bulk_create([
                PosicaoCarteira(
                    carteira=carteira, nome=p.nome, participacao=p.participacao, ordem=i
                )
                for i, p in enumerate(carteira_dom.posicoes)
            ])
        return carteira

    def coletar_indices(self, data_inicio: date, data_fim: date) -> int:
        """Coleta a série de todos os índices semeados."""
        total = 0
        for indice in Ativo.objects.filter(tipo=TipoAtivo.INDICE):
            try:
                total += self.coletar_serie(indice, data_inicio, data_fim)
            except Exception as exc:  # índice indisponível não derruba o lote
                logger.warning(f"Falha ao coletar índice {indice.nome}: {exc}")
        return total


@transaction.atomic
def seed_indices() -> None:
    """Cria/atualiza os Ativos do tipo INDICE a partir de quantum.catalogo."""
    for id_quantum, nome in INDICES.items():
        Ativo.objects.update_or_create(
            tipo=TipoAtivo.INDICE.value,
            id_quantum=id_quantum,
            defaults={"nome": nome},
        )
