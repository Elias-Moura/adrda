import json
import logging
import os
import urllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import reduce
from typing import Optional, Any
from urllib.parse import quote

import httpx
import pandas as pd
import trio
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


@dataclass
class Ativo:
    nome: str = ''
    cnpj: str = ''
    id: int = 0


@dataclass
class AtivoQuantum:
    nome: str
    tipo: str
    id_quantum: Optional[int] = None
    cnpj: Optional[str] = None
    primeira_cota: Optional[date] = None
    gestora: Optional[str] = None
    dados_complementares: Optional[dict[str, str]] = None

    def avalia_data_inicio(self, data_inicio_desejada: date) -> date:
        """
        Decide qual data usar para o scrap.
        Se a data do fundo for mais nova que a data solicitada, usa a data de início
        do fundo para evitar erros. Caso contrário, retorna a data solicitada.
        """
        if self.primeira_cota and self.primeira_cota > data_inicio_desejada:
            logger.debug(
                f'Data do ativo é mais nova que a data solicitada. '
                f'{self.primeira_cota=} > {data_inicio_desejada}'
            )
            return self.primeira_cota
        return data_inicio_desejada


@dataclass
class ResultadoBusca:
    """
    Um candidato retornado pela busca global do Quantum (pesquisa por texto).

    Espelha o `itemSelecionavel` da resposta de /buscaGlobal/ajax/buscar.
    `tipo` (tipoItemSelecionavel: FI, FII, ACAO, ...) é o mesmo valor usado nas
    chamadas a /api/ativos/{tipo}/{id_quantum}/...
    """
    label: str
    tipo: str
    id_quantum: int
    informacao_adicional: str = ""
    cnpj: Optional[str] = None
    codigo_grupo: int = 0


class _RateLimiter:
    """
    Token bucket para trio.

    - fill(total): tarefa de background — injeta `total` tokens na taxa configurada.
    - acquire(): consome um token; bloqueia se o bucket estiver vazio.
    """

    def __init__(self, rate: int):
        self._rate = rate
        self._send, self._recv = trio.open_memory_channel(rate)

    async def fill(self, total: int) -> None:
        interval = 1.0 / self._rate
        async with self._send:
            for i in range(total):
                await self._send.send(None)
                if i < total - 1:
                    await trio.sleep(interval)

    async def acquire(self) -> None:
        await self._recv.receive()


class QuantumScrapper:
    _BASE_URL = "https://www.comparadordeativos.com.br"
    _LOGIN_URL = (
        f"{_BASE_URL}/webaxis/webaxis2/notAuthorised/login/logar/realizaLogin"
    )
    _TOKEN_REFRESH_URL = f"{_BASE_URL}/webaxis/webaxis2/token/refresh"
    _API_URL = f"{_BASE_URL}/b"

    def __init__(self):
        self._client = httpx.Client(follow_redirects=True)
        self.token: str = ""
        self.data_inicio: date
        self.data_fim: date
        self.ativos: list[str] = []
        self.dfs_rentabilidades: list[pd.DataFrame] = []

    def login(self, username: str = None, password: str = None) -> "QuantumScrapper":
        """
        Autentica no Quantum via HTTP.
        Credenciais lidas do .env (QUANTUM_USERNAME / QUANTUM_PASSWORD) se não
        forem passadas explicitamente.
        """
        username = username or os.getenv("QUANTUM_USERNAME")
        password = password or os.getenv("QUANTUM_PASSWORD")

        if not username or not password:
            raise ValueError(
                "Credenciais não encontradas. "
                "Configure QUANTUM_USERNAME e QUANTUM_PASSWORD no arquivo .env"
            )

        # Headers retirados de login_curl.txt
        headers = {
            "accept": "*/*",
            "accept-language": "pt-BR,pt;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "content-type": "application/json; charset=UTF-8",
            "dnt": "1",
            "origin": self._BASE_URL,
            "prefer": "safe",
            "priority": "u=1, i",
            "referer": f"{self._BASE_URL}/webaxis/login.jsp",
            "sec-ch-ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
            ),
            "x-requested-with": "XMLHttpRequest",
        }

        payload = {
            "username": username,
            "senha": password,
            "autenticador": None,
            "isNavegadorChrome": True,
            "paginaRedirecionar": None,
        }

        response = self._client.post(self._LOGIN_URL, headers=headers, json=payload)

        if response.status_code not in (200, 302):
            raise ValueError(f"Falha no login: {response.status_code} {response.text}")

        # Passo 2: busca o Bearer token (o JSESSIONID do cookie jar já é enviado
        # automaticamente pelo httpx.Client nesta chamada)
        self.token = self._fetch_bearer_token()
        logger.info("Login realizado com sucesso. Token obtido.")
        return self

    def _fetch_bearer_token(self) -> str:
        """
        Obtém o Bearer token chamando o endpoint de refresh.

        O login (passo 1) já estabeleceu o JSESSIONID no cookie jar do client.
        Este endpoint usa essa sessão para devolver o token JWT usado nas chamadas
        à API de dados.
        """
        import time
        headers = {
            "accept": "*/*",
            "accept-language": "pt-BR,pt;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "dnt": "1",
            "prefer": "safe",
            "priority": "u=1, i",
            "referer": f"{self._BASE_URL}/webaxis/",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0"
            ),
            "x-requested-with": "XMLHttpRequest",
        }
        url = f"{self._TOKEN_REFRESH_URL}?_={int(time.time() * 1000)}"
        response = self._client.get(url, headers=headers)

        if response.status_code != 200:
            raise ValueError(
                f"Falha ao obter token: {response.status_code} {response.text}"
            )

        return self._extract_bearer(response)

    def _extract_bearer(self, response: httpx.Response) -> str:
        """
        Extrai o Bearer token da resposta do endpoint /token/refresh.
        Tenta JSON body (campos comuns) e, como fallback, o valor bruto do body.
        """
        try:
            data = response.json()
            if isinstance(data, dict):
                for key in ("token", "access_token", "apitoken", "jwt"):
                    if raw := data.get(key):
                        return raw if raw.startswith("Bearer ") else f"Bearer {raw}"
            # Alguns backends devolvem o token como string JSON pura
            if isinstance(data, str) and len(data) > 20:
                return data if data.startswith("Bearer ") else f"Bearer {data}"
        except Exception:
            pass

        # Fallback: body é texto puro com o token
        raw = response.text.strip()
        if raw and len(raw) > 20:
            return raw if raw.startswith("Bearer ") else f"Bearer {raw}"

        raise ValueError(
            "Bearer token não encontrado na resposta de /token/refresh. "
            f"Status: {response.status_code} | Body: {response.text[:200]}"
        )

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        """
        Decodifica o JSON da resposta tratando encoding.
        O backend do Quantum retorna alguns endpoints em ISO-8859-1 (latin-1)
        em vez de UTF-8, causando UnicodeDecodeError no json.loads padrão.
        """
        try:
            return response.json()
        except (UnicodeDecodeError, ValueError):
            return json.loads(response.content.decode("latin-1"))

    def _headers_api(self) -> dict:
        """
        Headers padrão para chamadas à API de dados.
        A autenticação é feita pelo cookie JSESSIONID, que o httpx.Client
        envia automaticamente em todas as requisições após o login.
        """
        return {
            "accept": "*/*",
            "accept-language": "pt-BR,pt;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "authorization": self.token,
            "content-type": "application/json",
            "dnt": "1",
            "origin": self._BASE_URL,
            "prefer": "safe",
            "priority": "u=1, i",
            "referer": f"{self._BASE_URL}/static/comparacao/",
            "sec-ch-ua": '"Chromium";v="142", "Microsoft Edge";v="142", "Not_A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0"
            ),
        }

    def req_cnpj(self, cnpj: str) -> dict:
        logger.debug(f'Recebido: {cnpj=}')
        url = (
            f"{self._BASE_URL}/webaxis/webaxis2/buscaGlobal/ajax/buscar"
            f"?filtroBusca=defaultSearch&searchString={urllib.parse.quote(cnpj)}&isCNPJ=true"
        )
        headers = {
            **self._headers_api(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"{self._BASE_URL}/webaxis/",
        }

        response = self._client.get(url, headers=headers)

        logger.debug(f'Resposta da consulta por CNPJ {response.status_code}')
        if response.status_code != 200:
            raise ValueError(f'{response.status_code=} {response.text}')
        return self._decode_json(response)

    def _build_url_busca_texto(self, termo: str, max_por_grupo: int = 5) -> str:
        """
        Monta a URL da busca global por texto livre (nome ou ticker).

        Replica exatamente os parâmetros enviados pela pesquisa interativa da
        interface ("Search assets"): mesmo endpoint de `req_cnpj`, porém com
        `isCNPJ=false` e os filtros de agrupamento.
        """
        import time
        return (
            f"{self._BASE_URL}/webaxis/webaxis2/buscaGlobal/ajax/buscar"
            f"?filtroBusca=defaultSearch"
            f"&searchString={urllib.parse.quote(termo)}"
            f"&cancelaBusca=false"
            f"&isCNPJ=false"
            f"&isCodigoSUSEP=false"
            f"&codigoGrupoExpandido="
            f"&quantidadeMaximaPorGrupo={max_por_grupo}"
            f"&_={int(time.time() * 1000)}"
        )

    @staticmethod
    def _parsear_resultados_busca(grupos: list[dict]) -> list[ResultadoBusca]:
        """
        Achata o JSON agrupado da busca global numa lista de ResultadoBusca.

        A resposta vem agrupada por tipo de ativo (cada `codigoGrupo` é um grupo);
        uma mesma pesquisa pode retornar vários grupos (ex.: HASH11 devolve o
        fundo de índice e o ETF). O CNPJ é extraído de `informacaoAdicional`
        quando presente (fundos vêm como 'CNPJ: 00.000.000/0000-00 | ...').
        """
        import re
        resultados: list[ResultadoBusca] = []
        for grupo in grupos:
            for entrada in grupo.get("primeirosResultados", []):
                item = entrada.get("itemSelecionavel", {})
                info = entrada.get("informacaoAdicional", "") or ""
                cnpj_match = re.search(r"CNPJ:\s*([\d./-]+)", info)
                resultados.append(ResultadoBusca(
                    label=item.get("label", ""),
                    tipo=item.get("tipoItemSelecionavel", ""),
                    id_quantum=int(item["identificador"]),
                    informacao_adicional=info,
                    cnpj=cnpj_match.group(1) if cnpj_match else None,
                    codigo_grupo=grupo.get("codigoGrupo", 0),
                ))
        return resultados

    def buscar_ativos(self, termo: str, max_por_grupo: int = 5) -> list[ResultadoBusca]:
        """
        Pesquisa ativos por texto livre (nome ou ticker) na busca global do Quantum.

        Reproduz a pesquisa interativa da interface. Diferente de `req_cnpj`, o
        resultado pode conter vários grupos/tipos de ativo; este método devolve
        todos os candidatos achatados numa única lista.
        """
        logger.debug(f"Buscando ativos por texto: {termo=}")
        url = self._build_url_busca_texto(termo, max_por_grupo)
        headers = {
            **self._headers_api(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"{self._BASE_URL}/webaxis/",
        }

        response = self._client.get(url, headers=headers)

        logger.debug(f"Resposta da busca por texto {response.status_code}")
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._parsear_resultados_busca(self._decode_json(response))

    # ── Métodos async (usados por trabalha_novos_ativos) ─────────────────────

    async def _buscar_ativos_async(
        self, termo: str, client: httpx.AsyncClient, max_por_grupo: int = 5
    ) -> list[ResultadoBusca]:
        """Variante async de `buscar_ativos` (mesma assinatura de resultado)."""
        url = self._build_url_busca_texto(termo, max_por_grupo)
        headers = {
            **self._headers_api(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"{self._BASE_URL}/webaxis/",
        }
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._parsear_resultados_busca(self._decode_json(response))


    async def _req_cnpj_async(self, cnpj: str, client: httpx.AsyncClient) -> dict:
        url = (
            f"{self._BASE_URL}/webaxis/webaxis2/buscaGlobal/ajax/buscar"
            f"?filtroBusca=defaultSearch&searchString={urllib.parse.quote(cnpj)}&isCNPJ=true"
        )
        headers = {
            **self._headers_api(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"{self._BASE_URL}/webaxis/",
        }
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f'{response.status_code=} {response.text}')
        return self._decode_json(response)

    async def _get_dados_complementares_async(
        self, tipo: str, id: int, client: httpx.AsyncClient
    ) -> dict:
        payload = self._build_payload_dados_complementares(tipo, id)
        response = await client.post(
            self._API_URL, headers=self._headers_api(), content=payload
        )
        if response.status_code != 200:
            raise ValueError(f'{response.status_code=} {response.text}')
        return self._simplificar_retorno_multiplex(self._decode_json(response))

    async def _processar_ativo_async(
        self,
        ativo: Ativo,
        client: httpx.AsyncClient,
        limiter: _RateLimiter,
    ) -> AtivoQuantum | None:
        """
        Processa um ativo: busca CNPJ + dados complementares, respeitando o rate limit.
        Retorna None se o CNPJ não tiver resultado no Quantum (ex.: ETFs, índices sem CNPJ).
        """
        await limiter.acquire()
        dados = await self._req_cnpj_async(ativo.cnpj, client)

        try:
            item = dados[0]['primeirosResultados'][0]['itemSelecionavel']
        except (IndexError, KeyError):
            await limiter.acquire()  # consome o 2º token para manter o balanço do rate limiter
            logger.warning(f"CNPJ {ativo.cnpj!r} não encontrado no Quantum — ativo ignorado.")
            return None

        nome = item['label']
        tipo = item['tipoItemSelecionavel']
        id_quantum = item['identificador']

        await limiter.acquire()
        dados_comp = await self._get_dados_complementares_async(tipo, id_quantum, client)

        return AtivoQuantum(
            nome=nome,
            tipo=tipo,
            id_quantum=id_quantum,
            cnpj=dados_comp['CNPJ'],
            primeira_cota=date.fromisoformat(dados_comp['INICIO_DO_FUNDO']),
            gestora=dados_comp['GESTAO'],
            dados_complementares=dados_comp,
        )

    async def _trabalha_novos_ativos_async(
        self, ativos: list[Ativo], rate: int
    ) -> list[AtivoQuantum]:
        """Orquestra o processamento concorrente com rate limiting via trio."""
        n_requests = len(ativos) * 2  # req_cnpj + _get_dados_complementares por ativo
        limiter = _RateLimiter(rate=rate)
        results: list[AtivoQuantum | None] = [None] * len(ativos)

        async def _processar(idx: int, ativo: Ativo, client: httpx.AsyncClient) -> None:
            results[idx] = await self._processar_ativo_async(ativo, client, limiter)
            if results[idx] is not None:
                logger.debug(f"[{idx + 1}/{len(ativos)}] {results[idx].nome} concluído.")

        async with httpx.AsyncClient(
            follow_redirects=True,
            cookies=self._client.cookies,
        ) as client:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(limiter.fill, n_requests)
                for idx, ativo in enumerate(ativos):
                    nursery.start_soon(_processar, idx, ativo, client)

        return [r for r in results if r is not None]

    def trabalha_novos_ativos(
        self, ativos: list[Ativo], rate: int = 10
    ) -> list[AtivoQuantum]:
        """
        Busca dados de múltiplos ativos de forma concorrente (trio).
        rate: máximo de requisições por segundo (padrão: 10).
        """
        if not ativos:
            return []
        return trio.run(self._trabalha_novos_ativos_async, ativos, rate)

    def resolve_relative_url(self, asset: AtivoQuantum, sufixo: str = 'serie') -> str:
        identificador = asset.id_quantum
        if asset.tipo == 'PORTFOLIO':
            identificador = quote(asset.nome)
        return f"/api/ativos/{asset.tipo}/{identificador}/medidas/{sufixo}"

    def get_retorno_carteira(
        self,
        data_inicio: date,
        data_fim: date,
        ativo: AtivoQuantum,
        valor_base: int = 100,
    ) -> dict:
        payload = json.dumps({
            "commonHeader": {
                "Content-Type": "application/json",
                "Accept-Language": "pt-BR",
                "x-Moeda": "BRL",
                "x-Retorno": "Fechamento",
            },
            "requests": [
                {
                    "method": "POST",
                    "headers": {},
                    "body": (
                        "{"
                        + '"medida":"EVOLUCAO_DO_ATIVO",'
                        + f'"dataInicial":"{data_inicio.strftime("%Y-%m-%d")}",'
                        + f'"dataFinal":"{data_fim.strftime("%Y-%m-%d")}",'
                        + f'"propriedades":{{"valorBase":{valor_base},"periodicidade":"DIARIA"}}'
                        + "}"
                    ),
                    "relativeUrl": self.resolve_relative_url(ativo),
                }
            ],
        }, indent=None, separators=(',', ':'))

        response = self._client.post(
            self._API_URL, headers=self._headers_api(), content=payload
        )
        logger.debug(f'Retorno diário {response.status_code}')
        return self._decode_json(response)

    @staticmethod
    def _build_payload_dados_complementares(tipo: str, id: int) -> str:
        return json.dumps({
            "commonHeader": {
                "Content-Type": "application/json",
                "Accept-Language": "pt-BR",
                "x-Moeda": "BRL",
                "x-Retorno": "Fechamento",
            },
            "requests": [
                {
                    "method": "POST",
                    "headers": {},
                    "body": (
                        '[{"medida":"NOME"},{"medida":"CLASSIFICACAO_LEGAL"},{"medida":"CNPJ"},'
                        '{"medida":"GESTAO"},{"medida":"CLASSIFICACAO_ANBIMA"},{"medida":"BENCHMARK"},'
                        '{"medida":"ABERTO_PARA_CAPTACAO"},{"medida":"PUBLICO_ALVO"},'
                        '{"medida":"TAXA_ADMINISTRACAO_E_GESTAO"},{"medida":"TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA"},'
                        '{"medida":"TAXA_DE_PERFORMANCE"},{"medida":"TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA"},'
                        '{"medida":"APLICACAO_MINIMA"},{"medida":"CONVERSAO_DA_COTA_PARA_APLICACAO"},'
                        '{"medida":"CONVERSAO_DA_COTA_PARA_RESGATE"},'
                        '{"medida":"DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS"},'
                        '{"medida":"TAXAS_INFORMACOES_ADICIONAIS_EXTRA"},{"medida":"INICIO_DO_FUNDO"},'
                        '{"medida":"MOVIMENTACAO_MINIMA"},{"medida":"DIVULGACAO"},'
                        '{"medida":"PORCENTAGEM_RENDA_VARIAVEL_FIE"},{"medida":"TAXA_DE_RESGATE_EXTRA"},'
                        '{"medida":"TRIBUTACAO"},{"medida":"POSSUI_SERIE"}]'
                    ),
                    "relativeUrl": f"/api/ativos/{tipo}/{id}/medidas/valor",
                }
            ],
        })

    def _get_dados_complementares(self, tipo: str, id: int) -> dict:
        logger.debug(f'{tipo=}, {id=}')
        payload = self._build_payload_dados_complementares(tipo, id)
        response = self._client.post(
            self._API_URL, headers=self._headers_api(), content=payload
        )
        if response.status_code != 200:
            raise ValueError(f'{response.status_code=} {response.text}')
        return self._simplificar_retorno_multiplex(self._decode_json(response))

    def _simplificar_retorno_multiplex(self, json_resposta_multiplex: dict[str, Any]) -> dict[str, Any]:
        """
        Processa o JSON de resposta multiplex do backend,
        desserializando o body e mapeando os valores para um dicionário simples.
        """
        ordem_medidas = [
            "NOME", "CLASSIFICACAO_LEGAL", "CNPJ", "GESTAO", "CLASSIFICACAO_ANBIMA",
            "BENCHMARK", "ABERTO_PARA_CAPTACAO", "PUBLICO_ALVO", "TAXA_ADMINISTRACAO_E_GESTAO",
            "TAXA_ADMINISTRACAO_E_GESTAO_MAXIMA", "TAXA_DE_PERFORMANCE",
            "TAXA_DE_PERFORMANCE_INDICE_DE_REFERENCIA", "APLICACAO_MINIMA",
            "CONVERSAO_DA_COTA_PARA_APLICACAO", "CONVERSAO_DA_COTA_PARA_RESGATE",
            "DISPONIBILIZACAO_DOS_RECURSOS_RESGATADOS", "TAXAS_INFORMACOES_ADICIONAIS_EXTRA",
            "INICIO_DO_FUNDO", "MOVIMENTACAO_MINIMA", "DIVULGACAO",
            "PORCENTAGEM_RENDA_VARIAVEL_FIE", "TAXA_DE_RESGATE_EXTRA",
            "TRIBUTACAO", "POSSUI_SERIE",
        ]

        logger.debug(f'Recebido: {json_resposta_multiplex=}')

        response_data = json_resposta_multiplex.get("responseList", [{}])[0]
        body_string = response_data.get("body")
        logger.debug(f'{body_string=}')

        if not body_string:
            raise Exception("erro: Corpo da resposta (body) não encontrado ou vazio.")

        try:
            dados_medidas: list[dict[str, Any]] = json.loads(body_string)
        except json.JSONDecodeError as e:
            raise Exception(f"Falha ao decodificar a string JSON do body: {e}")

        if len(dados_medidas) != len(ordem_medidas):
            raise Exception(
                f"Inconsistência de dados: O número de medidas na requisição não corresponde "
                f"ao número de valores no retorno. "
                f"{len(ordem_medidas)=}, {len(dados_medidas)=}"
            )

        return {
            medida_nome: dados_medidas[i].get("valor")
            for i, medida_nome in enumerate(ordem_medidas)
        }

    def monta_df_rentabilidade_diaria(self, response: dict) -> pd.DataFrame:
        try:
            dados = json.loads(response['responseList'][0]['body'])['serie']
        except KeyError:
            return pd.DataFrame()

        saida_de_dados: dict[str, list] = {
            'hoje': [],
            'valor': [],
            'rentabilidade': [],
            '%': [],
        }
        cota_ontem = 100.0

        for i, cota in enumerate(dados, start=1):
            cota_hoje = float(cota['valor'])
            rentabilidade = (cota_hoje - cota_ontem) / cota_ontem
            cota_ontem = cota_hoje

            saida_de_dados['hoje'].append(cota['data'])
            saida_de_dados['valor'].append(cota_hoje)
            saida_de_dados['rentabilidade'].append(rentabilidade)
            saida_de_dados['%'].append(1 + rentabilidade)

            if i == len(dados):
                saida_de_dados['hoje'].append('')
                saida_de_dados['valor'].append('')
                saida_de_dados['rentabilidade'].append('Rentabilidade período:')
                saida_de_dados['%'].append(
                    reduce(lambda x, y: x * y, saida_de_dados['%']) - 1
                )

        return pd.DataFrame(saida_de_dados)

    def raspar_dados(
        self, data_inicio: date, data_fim: date, carteira: AtivoQuantum
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Busca e retorna a série de cotas diárias do ativo.
        Retorna uma tupla (df_rentabilidade, df_vazio, df_vazio) para manter
        compatibilidade com o pipeline existente em analise.py.
        A volatilidade é calculada externamente a partir da variação diária de preço.
        """
        rentabilidade_df = self.monta_df_rentabilidade_diaria(
            self.get_retorno_carteira(data_inicio, data_fim, carteira)
        )
        return rentabilidade_df, pd.DataFrame(), pd.DataFrame()

    def scrap(self, ativos: list[AtivoQuantum], data_inicio: date, data_fim: date) -> None:
        self.data_inicio = data_inicio
        self.data_fim = data_fim

        for ativo in ativos:
            self.ativos.append(ativo.nome)
            logger.debug(f'Processando: {ativo}')

            data_inicio_efetiva = ativo.avalia_data_inicio(self.data_inicio)
            df_rentabilidade, _, _ = self.raspar_dados(data_inicio_efetiva, data_fim, ativo)
            self.dfs_rentabilidades.append(df_rentabilidade)

    def save_scrap(self) -> None:
        logger.info('Salvando dados brutos coletados no Quantum.')
        self.salvar_retonos(self.ativos)

    def salvar_retonos(self, wallets: list[str]) -> None:
        with pd.ExcelWriter('rentabilidade_diaria_ativos.xlsx') as writer:
            for df, sheet_name in zip(self.dfs_rentabilidades, wallets):
                df.to_excel(writer, sheet_name=sheet_name[:31])

    @staticmethod
    def carregar_ativos_excel(filepath) -> list["Ativo"]:
        """
        Lê um Excel com colunas 'nome' e 'cnpj' e retorna uma lista de Ativo.
        Nomes de colunas são normalizados para minúsculas.
        Linhas com CNPJ vazio/NaN são ignoradas.
        CNPJs numéricos (Excel remove pontuação) são convertidos com zero-fill.
        """
        df = pd.read_excel(filepath)
        df.columns = df.columns.str.lower().str.strip()

        if "cnpj" not in df.columns:
            raise ValueError(
                f"Coluna 'cnpj' não encontrada. Colunas disponíveis: {list(df.columns)}"
            )
        if "nome" not in df.columns:
            raise ValueError(
                f"Coluna 'nome' não encontrada. Colunas disponíveis: {list(df.columns)}"
            )

        ativos = []
        for row in df.itertuples():
            cnpj_raw = row.cnpj
            if not pd.notna(cnpj_raw):
                continue
            # Excel às vezes armazena CNPJ como número (perde zeros à esquerda)
            if isinstance(cnpj_raw, float):
                cnpj_str = f"{int(cnpj_raw):014d}"
            else:
                cnpj_str = str(cnpj_raw).strip()
            if not cnpj_str:
                continue
            nome = str(row.nome).strip() if pd.notna(row.nome) else cnpj_str
            ativos.append(Ativo(nome=nome, cnpj=cnpj_str))
        return ativos

    @staticmethod
    def salvar_dados_complementares(
        ativos: list["AtivoQuantum"],
        filepath: str = "dados_complementares.xlsx",
    ) -> None:
        """
        Exporta os dados complementares de uma lista de AtivoQuantum para Excel.
        Cada linha = um ativo; colunas = id_quantum + todos os campos de dados_complementares.
        """
        rows = [
            {"id": ativo.id_quantum, **(ativo.dados_complementares or {})}
            for ativo in ativos
        ]
        pd.DataFrame(rows).to_excel(filepath, index=False)
        logger.info(f"Dados complementares salvos em '{filepath}' ({len(rows)} ativos).")


def parseFloat(valor: str) -> float:
    return float(valor.replace('.', '').replace(',', '.').replace('R$ ', ''))


if __name__ == '__main__':
    from pathlib import Path
    import sys

    qs = QuantumScrapper()
    qs.login()  # lê QUANTUM_USERNAME e QUANTUM_PASSWORD do .env

    # ── Modo 1: busca por CNPJ a partir de um Excel ──────────────────────────
    excel_path = Path.home() / 'Downloads' / 'lista_ativos_bruno.xlsx'
    if excel_path.exists():
        ativos_raw = QuantumScrapper.carregar_ativos_excel(excel_path)
        ativos = qs.trabalha_novos_ativos(ativos_raw)
        QuantumScrapper.salvar_dados_complementares(ativos, 'tabela_bruno.xlsx')
        sys.exit(0)

    # ── Modo 2: lista fixa de portfolios ─────────────────────────────────────
    lista_ativos = [
        AtivoQuantum(nome='Carteira nível 1 2024', tipo='PORTFOLIO'),
        AtivoQuantum(nome='Carteira nível 2 2025', tipo='PORTFOLIO'),
        AtivoQuantum(nome='Carteira nível 3 2024', tipo='PORTFOLIO'),
        AtivoQuantum(nome='Carteira nível 4 2024', tipo='PORTFOLIO'),
        AtivoQuantum(nome='Carteira nível 5 2024', tipo='PORTFOLIO'),
    ]

    qs.scrap(
        ativos=lista_ativos,
        data_inicio=date(2022, 12, 31),
        data_fim=date(2025, 12, 31),
    )
    qs.save_scrap()
