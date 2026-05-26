from django.db import migrations

# Espelha scrapper.quantum.catalogo.INDICES (inline para não acoplar a
# migração ao código; migração é um snapshot histórico).
_INDICES = {
    "1": "CDI", "31": "IPCA", "4": "Ibovespa", "51": "IMA-B", "15": "IRF-M",
    "7": "Dólar", "114": "IDA-DI", "453": "Poupança (Selic)", "8": "Poupança",
}


def seed(apps, schema_editor):
    Ativo = apps.get_model("scrapper", "Ativo")
    for id_quantum, nome in _INDICES.items():
        Ativo.objects.update_or_create(
            tipo="INDICE", id_quantum=id_quantum, defaults={"nome": nome}
        )


def unseed(apps, schema_editor):
    Ativo = apps.get_model("scrapper", "Ativo")
    Ativo.objects.filter(tipo="INDICE", id_quantum__in=list(_INDICES)).delete()


class Migration(migrations.Migration):
    dependencies = [("scrapper", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
