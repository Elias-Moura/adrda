from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("ativos/", views.ativos_list, name="ativos"),
    path("ativos/<int:ativo_id>/excluir/", views.excluir_ativo, name="excluir_ativo"),
    path("buscar/", views.buscar_ativos, name="buscar_ativos"),
    path("buscar-candidatos/", views.buscar_candidatos, name="buscar_candidatos"),
    path("adicionar-ativo/", views.adicionar_ativo, name="adicionar_ativo"),
    path("scrap/", views.scrap_cotas, name="scrap_cotas"),
    path("relatorio/", views.relatorio, name="relatorio"),
    path("exportar-excel/", views.exportar_excel, name="exportar_excel"),
    path("exportar-cotas/", views.exportar_cotas_excel, name="exportar_cotas_excel"),
    path("jobs/<int:job_id>/", views.job_status, name="job_status"),
]
