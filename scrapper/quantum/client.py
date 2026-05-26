"""QuantumClient — transporte HTTP puro (sessão, token, requests crus).

Não importa Django nem ORM, não faz parsing: devolve dict cru.
Login/token/headers portados de quantum_scrapper.QuantumScrapper.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

from .catalogo import MEDIDAS_POR_TIPO, TipoAtivo

load_dotenv()


class QuantumClient:
    _BASE_URL = "https://www.comparadordeativos.com.br"
    _LOGIN_URL = f"{_BASE_URL}/webaxis/webaxis2/notAuthorised/login/logar/realizaLogin"
    _TOKEN_REFRESH_URL = f"{_BASE_URL}/webaxis/webaxis2/token/refresh"
    _API_URL = f"{_BASE_URL}/b"
    _BUSCA_URL = f"{_BASE_URL}/webaxis/webaxis2/buscaGlobal/ajax/buscar"

    def __init__(self) -> None:
        self._client = httpx.Client(follow_redirects=True)
        self.token: str = ""

    # ── Ciclo de vida ─────────────────────────────────────────────────────────
    def close(self) -> None:
        """Fecha a sessão HTTP (libera o pool de conexões do httpx)."""
        self._client.close()

    def __enter__(self) -> "QuantumClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Autenticação ────────────────────────────────────────────────────────
    def login(self, username: str | None = None, password: str | None = None) -> None:
        username = username or os.getenv("QUANTUM_USERNAME")
        password = password or os.getenv("QUANTUM_PASSWORD")
        if not username or not password:
            raise ValueError(
                "Credenciais não encontradas. "
                "Configure QUANTUM_USERNAME e QUANTUM_PASSWORD no arquivo .env"
            )
        headers = {
            "accept": "*/*",
            "content-type": "application/json; charset=UTF-8",
            "origin": self._BASE_URL,
            "referer": f"{self._BASE_URL}/webaxis/login.jsp",
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
        self.token = self._fetch_bearer_token()
        logger.info("Login realizado com sucesso. Token obtido.")

    def _fetch_bearer_token(self) -> str:
        url = f"{self._TOKEN_REFRESH_URL}?_={int(time.time() * 1000)}"
        headers = {"accept": "*/*", "x-requested-with": "XMLHttpRequest"}
        response = self._client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"Falha ao obter token: {response.status_code} {response.text}")
        return self._extract_bearer(response)

    @staticmethod
    def _extract_bearer(response: httpx.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict):
                for key in ("token", "access_token", "apitoken", "jwt"):
                    if raw := data.get(key):
                        return raw if raw.startswith("Bearer ") else f"Bearer {raw}"
            if isinstance(data, str) and len(data) > 20:
                return data if data.startswith("Bearer ") else f"Bearer {data}"
        except Exception:
            pass
        raw = response.text.strip()
        if raw and len(raw) > 20:
            return raw if raw.startswith("Bearer ") else f"Bearer {raw}"
        raise ValueError(
            "Bearer token não encontrado na resposta de /token/refresh. "
            f"Status: {response.status_code} | Body: {response.text[:200]}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (UnicodeDecodeError, ValueError):
            return json.loads(response.content.decode("latin-1"))

    def _headers_api(self) -> dict[str, str]:
        return {
            "accept": "*/*",
            "accept-language": "pt-BR,pt;q=0.9,en;q=0.8",
            "authorization": self.token,
            "content-type": "application/json",
            "origin": self._BASE_URL,
            "referer": f"{self._BASE_URL}/static/comparacao/",
        }

    # ── Endpoints (devolvem dict cru) ──────────────────────────────────────────
    def buscar(self, termo: str, is_cnpj: bool = False, max_por_grupo: int = 5) -> list[dict]:
        """Busca global por texto (is_cnpj=False) ou por CNPJ (is_cnpj=True)."""
        if is_cnpj:
            url = (
                f"{self._BUSCA_URL}?filtroBusca=defaultSearch"
                f"&searchString={urllib.parse.quote(termo)}&isCNPJ=true"
            )
        else:
            url = (
                f"{self._BUSCA_URL}?filtroBusca=defaultSearch"
                f"&searchString={urllib.parse.quote(termo)}"
                f"&cancelaBusca=false&isCNPJ=false&isCodigoSUSEP=false"
                f"&codigoGrupoExpandido=&quantidadeMaximaPorGrupo={max_por_grupo}"
                f"&_={int(time.time() * 1000)}"
            )
        headers = {
            **self._headers_api(),
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/x-www-form-urlencoded",
            "referer": f"{self._BASE_URL}/webaxis/",
        }
        response = self._client.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._decode_json(response)

    def _relative_url(self, tipo: TipoAtivo, id_quantum: str, sufixo: str) -> str:
        return f"/api/ativos/{TipoAtivo(tipo).value}/{id_quantum}/medidas/{sufixo}"

    def dados_complementares(self, tipo: TipoAtivo, id_quantum: str) -> dict:
        """Multiplex /medidas/valor. Devolve o dict cru (responseList)."""
        ordem = MEDIDAS_POR_TIPO.get(TipoAtivo(tipo), [])
        body_medidas = json.dumps([{"medida": m} for m in ordem])
        payload = json.dumps({
            "commonHeader": {
                "Content-Type": "application/json",
                "Accept-Language": "pt-BR",
                "x-Moeda": "BRL",
                "x-Retorno": "Fechamento",
            },
            "requests": [{
                "method": "POST",
                "headers": {},
                "body": body_medidas,
                "relativeUrl": self._relative_url(tipo, id_quantum, "valor"),
            }],
        })
        response = self._client.post(self._API_URL, headers=self._headers_api(), content=payload)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._decode_json(response)

    def serie(
        self, tipo: TipoAtivo, id_quantum: str, data_inicio: date, data_fim: date,
        valor_base: int = 100,
    ) -> dict:
        """Multiplex /medidas/serie (EVOLUCAO_DO_ATIVO). Devolve o dict cru."""
        body = json.dumps({
            "medida": "EVOLUCAO_DO_ATIVO",
            "dataInicial": data_inicio.strftime("%Y-%m-%d"),
            "dataFinal": data_fim.strftime("%Y-%m-%d"),
            "propriedades": {"valorBase": valor_base, "periodicidade": "DIARIA"},
        })
        payload = json.dumps({
            "commonHeader": {
                "Content-Type": "application/json",
                "Accept-Language": "pt-BR",
                "x-Moeda": "BRL",
                "x-Retorno": "Fechamento",
            },
            "requests": [{
                "method": "POST",
                "headers": {},
                "body": body,
                "relativeUrl": self._relative_url(tipo, id_quantum, "serie"),
            }],
        })
        response = self._client.post(self._API_URL, headers=self._headers_api(), content=payload)
        if response.status_code != 200:
            raise ValueError(f"{response.status_code=} {response.text}")
        return self._decode_json(response)
