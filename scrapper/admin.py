from django.contrib import admin

from .models import Ativo, AtivoQuantum, CotacaoDiaria, Job


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ["nome", "cnpj", "criado_em"]
    search_fields = ["nome", "cnpj"]


@admin.register(AtivoQuantum)
class AtivoQuantumAdmin(admin.ModelAdmin):
    list_display = ["ativo", "id_quantum", "tipo", "gestora", "atualizado_em"]
    search_fields = ["ativo__nome", "id_quantum"]
    readonly_fields = ["atualizado_em"]


@admin.register(CotacaoDiaria)
class CotacaoDiariaAdmin(admin.ModelAdmin):
    list_display = ["ativo", "data", "valor"]
    list_filter = ["ativo__tipo"]
    search_fields = ["ativo__ativo__nome"]
    date_hierarchy = "data"


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["id", "tipo", "status", "detalhe", "criado_em", "concluido_em"]
    list_filter = ["tipo", "status"]
    readonly_fields = ["criado_em", "concluido_em"]
