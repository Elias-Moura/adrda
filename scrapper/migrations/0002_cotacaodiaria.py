import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scrapper", "0001_initial"),
    ]

    operations = [
        # Permite cnpj vazio (índices não têm CNPJ)
        migrations.AlterField(
            model_name="ativo",
            name="cnpj",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        # Unique parcial: só aplica quando cnpj não for vazio
        migrations.AddConstraint(
            model_name="ativo",
            constraint=models.UniqueConstraint(
                condition=models.Q(cnpj__gt=""),
                fields=["cnpj"],
                name="ativo_unique_cnpj_nonempty",
            ),
        ),
        # Séries de cotação diária (base 100) para fundos e índices
        migrations.CreateModel(
            name="CotacaoDiaria",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("data", models.DateField(db_index=True)),
                ("valor", models.FloatField()),
                (
                    "ativo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cotacoes",
                        to="scrapper.ativoquantum",
                    ),
                ),
            ],
            options={
                "ordering": ["data"],
                "unique_together": {("ativo", "data")},
            },
        ),
    ]
