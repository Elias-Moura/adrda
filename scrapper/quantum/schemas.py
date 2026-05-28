"""Modelos Pydantic v2 do domínio Quantum (puro-Python, sem Django).

Metadados tolerantes: todos os campos são Optional e `extra="ignore"`,
para não quebrar se o Quantum mudar/adicionar medidas.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator

from .catalogo import TipoAtivo


class ResultadoBusca(BaseModel):
    """Candidato achatado da busca global por texto/CNPJ."""

    label: str
    tipo: TipoAtivo
    id_quantum: str  # str! cobre RENDA_FIXA ("VALE38") e corrige o bug do int()
    subtipo: str | None = None
    cnpj: str | None = None
    codigo_grupo: int = 0

    @field_validator("id_quantum", mode="before")
    @classmethod
    def coagir_id_para_string(cls, v: object) -> str:
        """Converte id_quantum numérico (int) para str; rejeita None (campo obrigatório)."""
        if v is None:
            raise ValueError("id_quantum não pode ser None")
        return str(v)


class PontoSerie(BaseModel):
    data: date
    valor: float


class SerieDiaria(BaseModel):
    pontos: list[PontoSerie] = []


class PosicaoCarteira(BaseModel):
    """Uma posição da carteira investida (nome do ativo + participação %)."""

    nome: str
    participacao: float


class Carteira(BaseModel):
    competencia: date | None = None
    posicoes: list[PosicaoCarteira] = []


class MetaBase(BaseModel):
    """Base tolerante para os metadados por tipo."""

    model_config = ConfigDict(extra="ignore")


class MetaFI(MetaBase):
    NOME: str | None = None
    CLASSIFICACAO_LEGAL: str | None = None
    CNPJ: str | None = None
    GESTAO: str | None = None
    CLASSIFICACAO_ANBIMA: str | None = None
    BENCHMARK: str | None = None
    ABERTO_PARA_CAPTACAO: str | None = None
    PUBLICO_ALVO: str | None = None
    TAXA_ADMINISTRACAO_E_GESTAO: str | None = None
    TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA: str | None = None
    TAXA_DE_PERFORMANCE: str | None = None
    TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA: str | None = None
    APLICACAO_MINIMA: str | None = None
    CONVERSAO_DA_COTA_PARA_APLICACAO: str | None = None
    CONVERSAO_DA_COTA_PARA_RESGATE: str | None = None
    DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS: str | None = None
    TAXAS_INFORMACOES_ADICIONAIS_EXTRA: str | None = None
    INICIO_DO_FUNDO: str | None = None
    MOVIMENTACAO_MINIMA: str | None = None
    DIVULGACAO: str | None = None
    PORCENTAGEM_RENDA_VARIAVEL_FIE: str | None = None
    TAXA_DE_RESGATE_EXTRA: str | None = None
    TRIBUTACAO: str | None = None
    POSSUI_SERIE: str | None = None


class MetaFII(MetaBase):
    NOME: str | None = None
    CLASSIFICACAO_LEGAL: str | None = None
    CNPJ: str | None = None
    ADMINISTRADOR: str | None = None
    GESTAO: str | None = None
    PUBLICO_ALVO: str | None = None
    CLASSIFICACAO_ANBIMA: str | None = None
    INVESTIMENTO_TIPO_DE_IMOVEL: str | None = None
    INVESTIMENTO_QUANTIDADE_DE_IMOVEIS: str | None = None
    RENTABILIDADE_ALVO: str | None = None
    SITUACAO_ATUAL: str | None = None
    TAXA_ADMINISTRACAO_E_GESTAO: str | None = None
    TAXA_DE_PERFORMANCE: str | None = None
    TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA: str | None = None
    INVESTIMENTO_LOCALIZACAO_DO_IMOVEL_EXTRA: str | None = None
    TAXAS_INFORMACOES_ADICIONAIS_EXTRA: str | None = None
    INICIO_DO_FUNDO: str | None = None
    APLICACAO_MINIMA: str | None = None
    MOVIMENTACAO_MINIMA: str | None = None
    DIVULGACAO: str | None = None
    TRIBUTACAO: str | None = None
    POSSUI_SERIE: str | None = None


class MetaACAO(MetaBase):
    NOME: str | None = None
    TIPO_DE_ATIVO: str | None = None
    TICKER: str | None = None
    CLASSE: str | None = None
    BOLSA: str | None = None
    SETOR_QUANTUM: str | None = None
    CONTROLE_ACIONARIO: str | None = None
    GOVERNANCA_CORPORATIVA: str | None = None
    INICIO_DO_FUNDO: str | None = None
    TAXA_DE_ADMINISTRACAO: str | None = None
    APLICACAO_MINIMA: str | None = None
    MOVIMENTACAO_MINIMA: str | None = None
    TRIBUTACAO: str | None = None
    POSSUI_SERIE: str | None = None


class MetaIndice(MetaBase):
    """INDICE não tem card de medidas/valor (semeado por catálogo)."""

    NOME: str | None = None


class MetaRendaFixa(MetaBase):
    """RENDA_FIXA: sem captura de medidas; tolerante."""

    NOME: str | None = None


class AtivoQuantum(BaseModel):
    """Objeto de domínio que os services persistem no ORM."""

    tipo: TipoAtivo
    id_quantum: str
    nome: str
    subtipo: str | None = None
    cnpj: str | None = None
    ticker: str | None = None
    setor: str | None = None
    gestora: str | None = None
    primeira_cota: date | None = None
    metadados: MetaFI | MetaFII | MetaACAO | MetaIndice | MetaRendaFixa
