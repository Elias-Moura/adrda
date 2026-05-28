import io
import os
import tempfile
import threading
from datetime import date as date_type

import numpy as np
import pandas as pd
from django.db import close_old_connections
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Ativo, CotacaoDiaria, Job
from .quantum.catalogo import TipoAtivo
from .services import QuantumService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serie_do_banco_range(ativo: Ativo, di, df) -> pd.Series:
    cotacoes = list(
        CotacaoDiaria.objects.filter(ativo=ativo, data__gte=di, data__lte=df)
        .values_list("data", "valor")
        .order_by("data")
    )
    if not cotacoes:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(d): v for d, v in cotacoes}, name=ativo.nome)


def _carregar_termos_excel(filepath: str) -> list[tuple[str, bool]]:
    """Lê um Excel com colunas 'cnpj' e/ou 'ticker'/'nome'.
    Retorna (termo, is_cnpj) por linha. CNPJ tem prioridade quando presente."""
    df = pd.read_excel(filepath)
    df.columns = df.columns.str.lower().str.strip()
    if "cnpj" not in df.columns and "ticker" not in df.columns and "nome" not in df.columns:
        raise ValueError(
            f"Excel precisa de coluna 'cnpj', 'ticker' ou 'nome'. "
            f"Colunas: {list(df.columns)}"
        )
    termos: list[tuple[str, bool]] = []
    for row in df.itertuples():
        cnpj = getattr(row, "cnpj", None)
        if cnpj is not None and pd.notna(cnpj):
            if isinstance(cnpj, float):
                # Célula numérica do Excel: zero-pad para 14 dígitos; 0 = vazio.
                cnpj_int = int(cnpj)
                cnpj_str = f"{cnpj_int:014d}" if cnpj_int > 0 else ""
            else:
                cnpj_str = str(cnpj).strip()
            if cnpj_str:
                termos.append((cnpj_str, True))
                continue
        for col in ("ticker", "nome"):
            valor = getattr(row, col, None)
            if valor is not None and pd.notna(valor) and str(valor).strip():
                termos.append((str(valor).strip(), False))
                break
    return termos


# ── Views ─────────────────────────────────────────────────────────────────────

def index(request):
    jobs = Job.objects.all()[:15]
    ativos_lista = (
        Ativo.objects.exclude(tipo=TipoAtivo.INDICE).order_by("nome")
    )
    ativos_count = ativos_lista.count()
    tem_cotacoes = CotacaoDiaria.objects.filter(ativo__in=ativos_lista).exists()
    return render(request, "scrapper/index.html", {
        "jobs": jobs,
        "ativos_count": ativos_count,
        "ativos_lista": ativos_lista,
        "tem_cotacoes": tem_cotacoes,
    })


def ativos_list(request):
    ativos = Ativo.objects.exclude(tipo=TipoAtivo.INDICE).order_by("nome")
    return render(request, "scrapper/ativos.html", {"ativos": ativos})


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
            termos = _carregar_termos_excel(tmp_path)
            if not termos:
                raise ValueError(
                    "Nenhum ativo no Excel. Use colunas 'cnpj', 'ticker' ou 'nome'."
                )
            service = QuantumService()
            total = 0
            for termo, is_cnpj in termos:
                resultados = (
                    service.buscar_por_cnpj(termo) if is_cnpj
                    else service.buscar_por_texto(termo)
                )
                if resultados:
                    service.importar_ativos(resultados[:1])  # 1º candidato
                    total += 1
            job.status = "done"
            job.detalhe = f"{total} de {len(termos)} ativos importados de '{arquivo.name}'"
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


@require_POST
def adicionar_cnpj(request):
    termo = request.POST.get("termo", "").strip()
    if not termo:
        return JsonResponse({"erro": "Informe o CNPJ ou código/nome do ativo."}, status=400)

    job = Job.objects.create(tipo="buscar_ativos", detalhe=f"Busca: {termo}")

    def _run():
        close_old_connections()
        try:
            service = QuantumService()
            resultados = service.buscar_termo(termo)
            if not resultados:
                raise ValueError(f"{termo!r} não encontrado no Quantum.")
            ativo = service.importar_ativos(resultados[:1])[0]
            job.status = "done"
            job.detalhe = f"Ativo '{ativo.nome}' adicionado ({termo})"
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


@require_POST
def scrap_cotas(request):
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
            di = date_type.fromisoformat(data_inicio)
            df_fim = date_type.fromisoformat(data_fim)

            ativos = list(
                Ativo.objects.filter(id__in=ativo_ids).exclude(tipo=TipoAtivo.INDICE)
            )
            if not ativos:
                raise ValueError("Nenhum ativo válido selecionado.")

            service = QuantumService()
            total = 0
            for ativo in ativos:
                total += service.coletar_serie(ativo, di, df_fim)
            total += service.coletar_indices(di, df_fim)

            job.status = "done"
            job.detalhe = (
                f"{len(ativos)} ativo(s) · {total} cotações salvas "
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


def _selecao_ctx(data_inicio="", data_fim="", erro=""):
    return {
        "carteiras": Ativo.objects.exclude(tipo=TipoAtivo.INDICE).order_by("nome"),
        "indices": Ativo.objects.filter(tipo=TipoAtivo.INDICE).order_by("nome"),
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "erro": erro,
    }


def relatorio(request):
    ids = request.GET.getlist("ids")
    data_inicio_str = request.GET.get("data_inicio", "")
    data_fim_str = request.GET.get("data_fim", "")

    if not ids or not data_inicio_str or not data_fim_str:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
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

    ativos = list(Ativo.objects.filter(id__in=ids))
    service: QuantumService | None = None

    precos_carteiras: dict[str, pd.Series] = {}
    precos_indices: dict[str, pd.Series] = {}

    for ativo in ativos:
        tem_dados = CotacaoDiaria.objects.filter(
            ativo=ativo, data__gte=di, data__lte=df
        ).exists()
        if not tem_dados:
            if service is None:
                service = QuantumService()
            try:
                service.coletar_serie(ativo, di, df)
            except Exception:
                pass  # ativo ignorado se a busca falhar

        serie = _serie_do_banco_range(ativo, di, df)
        if serie.empty:
            continue
        if ativo.tipo == TipoAtivo.INDICE:
            precos_indices[ativo.nome] = serie
        else:
            precos_carteiras[ativo.nome] = serie

    if not precos_carteiras:
        return render(request, "scrapper/relatorio.html", _selecao_ctx(
            data_inicio=data_inicio_str, data_fim=data_fim_str,
            erro="Nenhuma cotação encontrada para os ativos e período selecionados.",
        ))

    from .analise import gerar_relatorio_html

    html = gerar_relatorio_html(precos_carteiras, precos_indices)
    return HttpResponse(html)


def exportar_excel(request):
    ids = request.GET.getlist("ids")
    if not ids:
        return HttpResponse("Selecione pelo menos um ativo.", status=400)

    ativos = (
        Ativo.objects.filter(id__in=ids).exclude(tipo=TipoAtivo.INDICE).order_by("nome")
    )
    rows = [
        {"id_quantum": a.id_quantum, "nome": a.nome, "tipo": a.tipo,
         "cnpj": a.cnpj, "ticker": a.ticker, "gestora": a.gestora, **(a.metadados or {})}
        for a in ativos
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


def exportar_cotas_excel(request):
    ids = request.GET.getlist("ids")
    data_inicio_str = request.GET.get("data_inicio", "")
    data_fim_str = request.GET.get("data_fim", "")

    aq_qs = Ativo.objects.exclude(tipo=TipoAtivo.INDICE)
    if ids:
        aq_qs = aq_qs.filter(id__in=ids)

    filtro_data: dict = {}
    try:
        if data_inicio_str:
            filtro_data["data__gte"] = date_type.fromisoformat(data_inicio_str)
        if data_fim_str:
            filtro_data["data__lte"] = date_type.fromisoformat(data_fim_str)
    except ValueError:
        return HttpResponse("Data inválida. Use o formato AAAA-MM-DD.", status=400)

    cotas: dict[str, pd.Series] = {}
    for ativo in aq_qs.order_by("nome"):
        pts = list(
            CotacaoDiaria.objects.filter(ativo=ativo, **filtro_data)
            .values_list("data", "valor")
            .order_by("data")
        )
        if pts:
            cotas[ativo.nome] = pd.Series({pd.Timestamp(d): v for d, v in pts})

    if not cotas:
        return HttpResponse("Nenhuma cotação encontrada para os ativos selecionados.", status=404)

    df_cotas = pd.DataFrame(cotas).sort_index()
    if not data_inicio_str and not data_fim_str and len(cotas) > 1:
        latest_start = max(s.index[0] for s in cotas.values())
        df_cotas = df_cotas.loc[latest_start:]
    df_cotas = df_cotas.dropna(how="all", axis=0)
    df_cotas.index.name = "data"

    df_ln = np.log(df_cotas / df_cotas.shift(1)).dropna(how="all", axis=0)
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
