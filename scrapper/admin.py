# TODO(Task-7): reescrever admin para Ativo unificado
from django.contrib import admin

from .models import Ativo, CotacaoDiaria, Job


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ["nome", "tipo", "cnpj", "ticker", "gestora", "criado_em"]
    search_fields = ["nome", "cnpj", "ticker"]
    list_filter = ["tipo"]


@admin.register(CotacaoDiaria)
class CotacaoDiariaAdmin(admin.ModelAdmin):
    list_display = ["ativo", "data", "valor"]
    list_filter = ["ativo__tipo"]
    search_fields = ["ativo__nome"]
    date_hierarchy = "data"


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["id", "tipo", "status", "detalhe", "criado_em", "concluido_em"]
    list_filter = ["tipo", "status"]
    readonly_fields = ["criado_em", "concluido_em"]
