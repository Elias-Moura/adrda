"""Funções puras: dict cru da API → schemas Pydantic. Sem rede, sem Django."""
from __future__ import annotations

import json
import re
from datetime import date

from loguru import logger
from pydantic import ValidationError

from .catalogo import MEDIDAS_POR_TIPO, TipoAtivo
from .schemas import (
    AtivoQuantum,
    MetaACAO,
    MetaBase,
    MetaFI,
    MetaFII,
    MetaIndice,
    MetaRendaFixa,
    PontoSerie,
    ResultadoBusca,
    SerieDiaria,
)

_CNPJ_RE = re.compile(r"CNPJ:\s*([\d./-]+)")
_TIPO_RE = re.compile(r"Type:\s*([^|]+)")

_META_CLASS: dict[TipoAtivo, type[MetaBase]] = {
    TipoAtivo.FI: MetaFI,
    TipoAtivo.FII: MetaFII,
    TipoAtivo.ACAO: MetaACAO,
    TipoAtivo.INDICE: MetaIndice,
    TipoAtivo.RENDA_FIXA: MetaRendaFixa,
}


def parse_resultados_busca(grupos: list[dict]) -> list[ResultadoBusca]:
    """Achata o JSON agrupado da busca global numa lista de ResultadoBusca.

    id_quantum sempre como string (cobre RENDA_FIXA). CNPJ e subtipo são
    extraídos de informacaoAdicional quando presentes.
    """
    resultados: list[ResultadoBusca] = []
    for grupo in grupos:
        for entrada in grupo.get("primeirosResultados", []):
            item = entrada.get("itemSelecionavel", {})
            info = entrada.get("informacaoAdicional", "") or ""
            cnpj_match = _CNPJ_RE.search(info)
            tipo_match = _TIPO_RE.search(info)
            try:
                # id_quantum cru (sem str()): a validação do schema coage int->str
                # e rejeita None, em vez de produzir o literal "None".
                resultados.append(ResultadoBusca(
                    label=item.get("label", ""),
                    tipo=item.get("tipoItemSelecionavel", ""),
                    id_quantum=item.get("identificador"),
                    subtipo=tipo_match.group(1).strip() if tipo_match else None,
                    cnpj=cnpj_match.group(1) if cnpj_match else None,
                    codigo_grupo=grupo.get("codigoGrupo", 0),
                ))
            except ValidationError as exc:
                # Um candidato inválido (tipo desconhecido, id ausente) não
                # derruba o lote inteiro; é registrado e ignorado.
                logger.warning(f"Resultado de busca ignorado ({item!r}): {exc}")
    return resultados


def _body_multiplex(raw_multiplex: dict) -> str | None:
    try:
        return raw_multiplex["responseList"][0]["body"]
    except (KeyError, IndexError, TypeError):
        return None


def parse_metadados(tipo: TipoAtivo, raw_multiplex: dict) -> MetaBase:
    """Zipa a ordem de medidas do tipo com os valores posicionais da resposta.

    Tolerante: zip trunca no menor dos dois; campos faltantes ficam None;
    medidas extras são ignoradas pelo schema (extra='ignore').
    """
    meta_cls = _META_CLASS[TipoAtivo(tipo)]
    ordem = MEDIDAS_POR_TIPO.get(TipoAtivo(tipo), [])
    body = _body_multiplex(raw_multiplex)
    if not body or not ordem:
        return meta_cls()
    try:
        valores = json.loads(body)
    except json.JSONDecodeError:
        return meta_cls()
    dados = {
        nome: item.get("valor")
        for nome, item in zip(ordem, valores)
        if isinstance(item, dict)
    }
    return meta_cls(**dados)


def parse_serie(raw_multiplex: dict) -> SerieDiaria:
    """responseList[0].body -> {'serie': [{data, valor}]} -> SerieDiaria."""
    body = _body_multiplex(raw_multiplex)
    if not body:
        return SerieDiaria()
    try:
        pontos_raw = json.loads(body).get("serie", [])
    except (json.JSONDecodeError, AttributeError):
        return SerieDiaria()
    pontos: list[PontoSerie] = []
    for p in pontos_raw:
        try:
            pontos.append(
                PontoSerie(data=date.fromisoformat(p["data"]), valor=float(p["valor"]))
            )
        except (KeyError, TypeError, ValueError) as exc:
            # Um ponto malformado é descartado sem perder a série inteira.
            logger.warning(f"Ponto de série ignorado ({p!r}): {exc}")
    return SerieDiaria(pontos=pontos)


def _data_ou_none(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except (ValueError, TypeError):
        return None


def montar_ativo(resultado: ResultadoBusca, meta: MetaBase) -> AtivoQuantum:
    """Combina o resultado da busca + metadados validados num AtivoQuantum,
    derivando as colunas promovidas a partir dos campos disponíveis."""
    ticker = getattr(meta, "TICKER", None)
    setor = getattr(meta, "SETOR_QUANTUM", None)
    cnpj = getattr(meta, "CNPJ", None) or resultado.cnpj
    gestora = getattr(meta, "GESTAO", None)
    subtipo = resultado.subtipo or getattr(meta, "TIPO_DE_ATIVO", None)
    primeira_cota = _data_ou_none(getattr(meta, "INICIO_DO_FUNDO", None))
    nome = getattr(meta, "NOME", None) or resultado.label
    return AtivoQuantum(
        tipo=resultado.tipo,
        id_quantum=resultado.id_quantum,
        nome=nome,
        subtipo=subtipo,
        cnpj=cnpj,
        ticker=ticker,
        setor=setor,
        gestora=gestora,
        primeira_cota=primeira_cota,
        metadados=meta,
    )
