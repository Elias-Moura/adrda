import json
import os
import tempfile
import threading

import pandas as pd
from django.db import close_old_connections
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from quantum_scrapper import AtivoQuantum as AQScrapper
from quantum_scrapper import Ativo as AtivoScrapper
from quantum_scrapper import QuantumScrapper

from .models import Ativo, AtivoQuantum, CotacaoDiaria, Job

# Índices padrão do Quantum — buscados junto ao scrap de cotas
_INDICES_QUANTUM = [
    {"nome": "CDI",           "id_quantum": "1",   "tipo": "INDICE"},
    {"nome": "IPCA",          "id_quantum": "7",   "tipo": "INDICE"},
    {"nome": "IBOVESPA",      "id_quantum": "4",   "tipo": "INDICE"},
    {"nome": "IMA-B",         "id_quantum": "114", "tipo": "INDICE"},
    {"nome": "IHFA",          "id_quantum": "51",  "tipo": "INDICE"},
    {"nome": "IRF-M",         "id_quantum": "31",  "tipo": "INDICE"},
    {"nome": "IFIX",          "id_quantum": "15",  "tipo": "INDICE"},
    {"nome": "BDRX",          "id_quantum": "453", "tipo": "INDICE"},
    {"nome": "Dólar (PTAX)",  "id_quantum": "8",   "tipo": "INDICE"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _salvar_cotacoes(ativo_quantum_obj: AtivoQuantum, serie_raw: dict) -> int:
    objs = [
        CotacaoDiaria(ativo=ativo_quantum_obj, data=data, valor=valor)
        for data, valor in serie_raw.items()
    ]
    CotacaoDiaria.objects.bulk_create(
        objs,
        update_conflicts=True,
        unique_fields=["ativo", "data"],
        update_fields=["valor"],
    )
    return len(objs)


def _extrair_serie(raw_response: dict) -> dict[str, float]:
    try:
        body = json.loads(raw_response["responseList"][0]["body"])
        return {p["data"]: float(p["valor"]) for p in body["serie"]}
    except (KeyError, json.JSONDecodeError, IndexError):
        return {}


def _salvar_ativo_quantum(aq: "AQScrapper") -> AtivoQuantum:
    cnpj = aq.cnpj or ""
    if cnpj:
        ativo_obj, _ = Ativo.objects.get_or_create(cnpj=cnpj, defaults={"nome": aq.nome})
    else:
        ativo_obj, _ = Ativo.objects.get_or_create(nome=aq.nome, cnpj="")
    aq_obj, _ = AtivoQuantum.objects.update_or_create(
        ativo=ativo_obj,
        defaults={
            "id_quantum": str(aq.id_quantum or ""),
            "tipo": aq.tipo,
            "primeira_cota": aq.primeira_cota,
            "gestora": aq.gestora or "",
            "dados_complementares": aq.dados_complementares or {},
        },
    )
    return aq_obj


def _serie_do_banco(aq: AtivoQuantum) -> pd.Series:
    cotacoes = list(
        CotacaoDiaria.objects.filter(ativo=aq)
        .values_list("data", "valor")
        .order_by("data")
    )
    if not cotacoes:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(d): v for d, v in cotacoes}, name=aq.ativo.nome)


def _serie_do_banco_range(aq: AtivoQuantum, di, df) -> pd.Series:
    """Retorna a série filtrada ao intervalo [di, df]."""
    cotacoes = list(
        CotacaoDiaria.objects.filter(ativo=aq, data__gte=di, data__lte=df)
        .values_list("data", "valor")
        .order_by("data")
    )
    if not cotacoes:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(d): v for d, v in cotacoes}, name=aq.ativo.nome)


def _aq_para_scrapper(aq_db: AtivoQuantum) -> "AQScrapper":
    """Converte um AtivoQuantum do banco para o dataclass do scrapper."""
    return AQScrapper(
        nome=aq_db.ativo.nome,
        tipo=aq_db.tipo,
        id_quantum=(
            int(aq_db.id_quantum) if aq_db.id_quantum.isdigit() else aq_db.id_quantum
        ),
        cnpj=aq_db.ativo.cnpj,
        primeira_cota=aq_db.primeira_cota,
        gestora=aq_db.gestora,
        dados_complementares=aq_db.dados_complementares,
    )


# ── Views ─────────────────────────────────────────────────────────────────────

def index(request):
    jobs = Job.objects.all()[:15]
    ativos_lista = (
        AtivoQuantum.objects
        .exclude(tipo="INDICE")
        .select_related("ativo")
        .order_by("ativo__nome")
    )
    ativos_count = ativos_lista.count()
    tem_cotacoes = CotacaoDiaria.objects.filter(
        ativo__in=ativos_lista
    ).exists()
    return render(request, "scrapper/index.html", {
        "jobs": jobs,
        "ativos_count": ativos_count,
        "ativos_lista": ativos_lista,
        "tem_cotacoes": tem_cotacoes,
    })


def ativos_list(request):
    ativos = (
        Ativo.objects
        .select_related("quantum")
        .exclude(quantum__tipo="INDICE")
        .all()
    )
    return render(request, "scrapper/ativos.html", {"ativos": ativos})


# ── Importar via Excel ────────────────────────────────────────────────────────

@require_POST
def buscar_ativos(request):
    arquivo = request.FILES.get("arquivo")
    if not arquivo:
        return JsonResponse({"erro": "Nenhum arquivo enviado."}, status=400)

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    for chunk in arquivo.chunks():
        tmp.write(chunk)
    tmp.close()

    job = Job.objects.create(tipo="buscar_ativos", detalhe=arquivo.name)

    def _run(tmp_path: str):
        close_old_connections()
        try:
            ativos_raw = QuantumScrapper.carregar_ativos_excel(tmp_path)
            if not ativos_raw:
                raise ValueError(
                    "Nenhum ativo encontrado no Excel. "
                    "Verifique se as colunas se chamam 'nome' e 'cnpj'."
                )
            qs_client = QuantumScrapper()
            qs_client.login()
            ativos_quantum = qs_client.trabalha_novos_ativos(ativos_raw)
            for aq in ativos_quantum:
                _salvar_ativo_quantum(aq)
            job.status = "done"
            job.detalhe = (
                f"{len(ativos_quantum)} de {len(ativos_raw)} ativos importados "
                f"de '{arquivo.name}'"
            )
            job.concluido_em = timezone.now()
            job.save()
        except Exception as exc:
            job.status = "error"
            job.erro = str(exc)
            job.concluido_em = timezone.now()
            job.save()
        finally:
            close_old_connections()
            os.unlink(tmp_path)

    threading.Thread(target=_run, args=(tmp.name,), daemon=True).start()
    return JsonResponse({"job_id": job.id})


# ── Importar por CNPJ avulso ──────────────────────────────────────────────────

@require_POST
def adicionar_cnpj(request):
    cnpj = request.POST.get("cnpj", "").strip()
    if not cnpj:
        return JsonResponse({"erro": "Informe o CNPJ."}, status=400)

    job = Job.objects.create(tipo="buscar_ativos", detalhe=f"CNPJ: {cnpj}")

    def _run():
        close_old_connections()
        try:
            qs_client = QuantumScrapper()
            qs_client.login()
            resultados = qs_client.trabalha_novos_ativos(
                [AtivoScrapper(nome="", cnpj=cnpj)]
            )
            if not resultados:
                raise ValueError(f"CNPJ {cnpj!r} não encontrado no Quantum.")
            _salvar_ativo_quantum(resultados[0])
            job.status = "done"
            job.detalhe = f"Ativo '{resultados[0].nome}' adicionado (CNPJ: {cnpj})"
            job.concluido_em = timezone.now()
            job.save()
        except Exception as exc:
            job.status = "error"
            job.erro = str(exc)
            job.concluido_em = timezone.now()
            job.save()
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"job_id": job.id})


# ── Scrap de cotas (ativos selecionados) ──────────────────────────────────────

@require_POST
def scrap_cotas(request):
    """
    Busca cotas diárias apenas dos ativos selecionados pelo usuário.
    Salva em CotacaoDiaria + gera Excel. Índices padrão são sempre incluídos.
    """
    data_inicio = request.POST.get("data_inicio")
    data_fim = request.POST.get("data_fim")
    ativo_ids = request.POST.getlist("ativo_ids")

    if not data_inicio or not data_fim:
        return JsonResponse({"erro": "Informe data_inicio e data_fim."}, status=400)
    if not ativo_ids:
        return JsonResponse({"erro": "Selecione pelo menos um ativo."}, status=400)

    job = Job.objects.create(
        tipo="scrap",
        detalhe=f"{data_inicio} → {data_fim} · {len(ativo_ids)} ativo(s)",
    )

    def _run():
        close_old_connections()
        try:
            from datetime import date

            di = date.fromisoformat(data_inicio)
            df_fim = date.fromisoformat(data_fim)

            ativos_db = list(
                AtivoQuantum.objects
                .filter(id__in=ativo_ids)
                .exclude(tipo="INDICE")
                .select_related("ativo")
            )
            if not ativos_db:
                raise ValueError("Nenhum ativo válido selecionado.")

            qs_client = QuantumScrapper()
            qs_client.login()
            total_cotacoes = 0

            # ── Fundos/portfolios selecionados ───────────────────────────
            for aq_db in ativos_db:
                ativo_s = AQScrapper(
                    nome=aq_db.ativo.nome,
                    tipo=aq_db.tipo,
                    id_quantum=(
                        int(aq_db.id_quantum)
                        if aq_db.id_quantum.isdigit()
                        else aq_db.id_quantum
                    ),
                    cnpj=aq_db.ativo.cnpj,
                    primeira_cota=aq_db.primeira_cota,
                    gestora=aq_db.gestora,
                    dados_complementares=aq_db.dados_complementares,
                )
                data_efetiva = ativo_s.avalia_data_inicio(di)
                raw = qs_client.get_retorno_carteira(data_efetiva, df_fim, ativo_s)
                serie = _extrair_serie(raw)
                if serie:
                    total_cotacoes += _salvar_cotacoes(aq_db, serie)
                qs_client.ativos.append(aq_db.ativo.nome)
                qs_client.dfs_rentabilidades.append(
                    qs_client.monta_df_rentabilidade_diaria(raw)
                )

            # ── Índices padrão (sempre coletados junto) ──────────────────
            for cfg in _INDICES_QUANTUM:
                ativo_idx, _ = Ativo.objects.get_or_create(
                    nome=cfg["nome"], cnpj=""
                )
                aq_idx, _ = AtivoQuantum.objects.get_or_create(
                    ativo=ativo_idx,
                    defaults={"id_quantum": cfg["id_quantum"], "tipo": cfg["tipo"]},
                )
                try:
                    idx_s = AQScrapper(
                        nome=cfg["nome"],
                        tipo=cfg["tipo"],
                        id_quantum=int(cfg["id_quantum"]),
                    )
                    raw_idx = qs_client.get_retorno_carteira(di, df_fim, idx_s)
                    serie_idx = _extrair_serie(raw_idx)
                    if serie_idx:
                        total_cotacoes += _salvar_cotacoes(aq_idx, serie_idx)
                except Exception:
                    pass

            qs_client.save_scrap()

            job.status = "done"
            job.detalhe = (
                f"{len(ativos_db)} ativo(s) · {total_cotacoes} cotações salvas "
                f"({data_inicio} → {data_fim})"
            )
            job.concluido_em = timezone.now()
            job.save()
        except Exception as exc:
            job.status = "error"
            job.erro = str(exc)
            job.concluido_em = timezone.now()
            job.save()
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()
    return JsonResponse({"job_id": job.id})


# ── Relatório HTML (seleção + geração) ────────────────────────────────────────

def _selecao_ctx(data_inicio="", data_fim="", erro=""):
    """Contexto para a página de seleção de relatório."""
    return {
        "carteiras": (
            AtivoQuantum.objects
            .exclude(tipo="INDICE")
            .distinct()
            .select_related("ativo")
            .order_by("ativo__nome")
        ),
        "indices": (
            AtivoQuantum.objects
            .filter(tipo="INDICE")
            .distinct()
            .select_related("ativo")
            .order_by("ativo__nome")
        ),
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "erro": erro,
    }


def relatorio(request):
    """
    GET sem ids/datas  → página de seleção.
    GET com ids+datas  → busca dados faltantes no Quantum se necessário,
                         filtra ao período e gera o relatório HTML.
    """
    from datetime import date as date_type

    ids = request.GET.getlist("ids")
    data_inicio_str = request.GET.get("data_inicio", "")
    data_fim_str = request.GET.get("data_fim", "")

    # ── Página de seleção ────────────────────────────────────────────────
    if not ids or not data_inicio_str or not data_fim_str:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str,
            data_fim=data_fim_str,
        ))

    try:
        di = date_type.fromisoformat(data_inicio_str)
        df = date_type.fromisoformat(data_fim_str)
    except ValueError:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            erro="Data inválida. Use o formato AAAA-MM-DD.",
        ))

    if di >= df:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
            erro="A data de início deve ser anterior à data de fim.",
        ))

    # ── Geração do relatório ─────────────────────────────────────────────
    aq_selecionados = list(
        AtivoQuantum.objects.filter(id__in=ids).select_related("ativo")
    )

    qs_client = None  # instanciado só se precisar buscar dados

    precos_carteiras: dict[str, pd.Series] = {}
    precos_indices: dict[str, pd.Series] = {}

    for aq in aq_selecionados:
        tem_dados = CotacaoDiaria.objects.filter(
            ativo=aq, data__gte=di, data__lte=df
        ).exists()

        if not tem_dados:
            # Busca no Quantum e persiste antes de ler do banco
            if qs_client is None:
                qs_client = QuantumScrapper()
                qs_client.login()
            try:
                ativo_s = _aq_para_scrapper(aq)
                data_efetiva = ativo_s.avalia_data_inicio(di)
                raw = qs_client.get_retorno_carteira(data_efetiva, df, ativo_s)
                serie_raw = _extrair_serie(raw)
                if serie_raw:
                    _salvar_cotacoes(aq, serie_raw)
            except Exception:
                pass  # ativo ignorado se a busca falhar

        # Lê do banco, sempre filtrado ao período solicitado
        serie = _serie_do_banco_range(aq, di, df)
        if serie.empty:
            continue

        if aq.tipo == "INDICE":
            precos_indices[aq.ativo.nome] = serie
        else:
            precos_carteiras[aq.ativo.nome] = serie

    if not precos_carteiras:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
            erro="Nenhuma cotação encontrada para os ativos e período selecionados.",
        ))

    from .analise import gerar_relatorio_html

    html = gerar_relatorio_html(precos_carteiras, precos_indices)
    return HttpResponse(html)


# ── Exportar metadados para Excel ────────────────────────────────────────────

def exportar_excel(request):
    """
    GET ?ids=1&ids=2  →  download do Excel com dados_complementares dos ativos selecionados.
    Lê apenas do banco — sem chamadas ao Quantum.
    """
    import io

    ids = request.GET.getlist("ids")
    if not ids:
        return HttpResponse("Selecione pelo menos um ativo.", status=400)

    ativos_db = (
        AtivoQuantum.objects
        .filter(id__in=ids)
        .exclude(tipo="INDICE")
        .select_related("ativo")
        .order_by("ativo__nome")
    )

    rows = [
        {"id": aq.id_quantum, "nome": aq.ativo.nome, **(aq.dados_complementares or {})}
        for aq in ativos_db
    ]

    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="dados_complementares.xlsx"'
    return response


# ── Exportar cotas + retorno LN para Excel ───────────────────────────────────

def exportar_cotas_excel(request):
    """
    GET ?ids=1&ids=2&data_inicio=AAAA-MM-DD&data_fim=AAAA-MM-DD

    ids omitido  → todos os ativos (exceto índices).
    datas omitidas → todos os dados do banco.

    Retorna Excel com duas abas:
      • Cotas       — valores base-100 (DatetimeIndex × ativo)
      • Retorno_LN  — log-retorno diário ln(P_t / P_{t-1})
    """
    import io
    from datetime import date as date_type

    import numpy as np

    ids = request.GET.getlist("ids")
    data_inicio_str = request.GET.get("data_inicio", "")
    data_fim_str = request.GET.get("data_fim", "")

    aq_qs = AtivoQuantum.objects.exclude(tipo="INDICE").select_related("ativo")
    if ids:
        aq_qs = aq_qs.filter(id__in=ids)

    filtro_data: dict = {}
    if data_inicio_str:
        filtro_data["data__gte"] = date_type.fromisoformat(data_inicio_str)
    if data_fim_str:
        filtro_data["data__lte"] = date_type.fromisoformat(data_fim_str)

    cotas: dict[str, pd.Series] = {}
    for aq in aq_qs.order_by("ativo__nome"):
        pts = list(
            CotacaoDiaria.objects.filter(ativo=aq, **filtro_data)
            .values_list("data", "valor")
            .order_by("data")
        )
        if pts:
            cotas[aq.ativo.nome] = pd.Series(
                {pd.Timestamp(d): v for d, v in pts}
            )

    if not cotas:
        return HttpResponse("Nenhuma cotação encontrada para os ativos selecionados.", status=404)

    df_cotas = pd.DataFrame(cotas).sort_index()

    # Se não foi fornecido filtro de data e há mais de um ativo, alinha ao período
    # comum para evitar colunas quase inteiramente NaN (ativos com históricos distintos).
    if not data_inicio_str and not data_fim_str and len(cotas) > 1:
        latest_start = max(s.index[0] for s in cotas.values())
        df_cotas = df_cotas.loc[latest_start:]

    # Remove datas onde todos os ativos têm NaN (ex.: feriados sem dados)
    df_cotas = df_cotas.dropna(how="all", axis=0)
    df_cotas.index.name = "data"

    # LN return: ln(P_t / P_{t-1})  — primeira linha de cada ativo será NaN por definição
    df_ln = np.log(df_cotas / df_cotas.shift(1))
    df_ln = df_ln.dropna(how="all", axis=0)
    df_ln.index.name = "data"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_cotas.to_excel(writer, sheet_name="Cotas")
        df_ln.to_excel(writer, sheet_name="Retorno_LN")
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="cotas_retorno_ln.xlsx"'
    return response


# ── Status de job ─────────────────────────────────────────────────────────────

def job_status(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    return JsonResponse({
        "id": job.id,
        "tipo": job.tipo,
        "status": job.status,
        "detalhe": job.detalhe,
        "erro": job.erro,
        "criado_em": job.criado_em.isoformat(),
        "concluido_em": job.concluido_em.isoformat() if job.concluido_em else None,
    })
