# TODO(Task-8): reescrever views para Ativo unificado
# Stubs provisórios — permitem makemigrations/migrate sem ImportError.
# Implementação completa virá na Task 8.
from django.http import HttpResponse
from django.shortcuts import render

from .models import Ativo, CotacaoDiaria, Job


def index(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def ativos_list(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def buscar_ativos(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def adicionar_cnpj(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def scrap_cotas(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def relatorio(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def exportar_excel(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def exportar_cotas_excel(request):
    return HttpResponse("Em refatoração — Task 8 pendente.")


def job_status(request, job_id):
    from django.shortcuts import get_object_or_404
    from django.http import JsonResponse

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
