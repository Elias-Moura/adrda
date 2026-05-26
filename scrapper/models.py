from django.db import models


class Ativo(models.Model):
    nome = models.CharField(max_length=200)
    # Blank/empty para índices (CDI, IBOV…) que não têm CNPJ
    cnpj = models.CharField(max_length=20, blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Ativo"
        verbose_name_plural = "Ativos"
        constraints = [
            # Unicidade só quando cnpj não for vazio
            models.UniqueConstraint(
                condition=models.Q(cnpj__gt=""),
                fields=["cnpj"],
                name="ativo_unique_cnpj_nonempty",
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.cnpj})" if self.cnpj else self.nome


class AtivoQuantum(models.Model):
    ativo = models.OneToOneField(
        Ativo, on_delete=models.CASCADE, related_name="quantum"
    )
    id_quantum = models.CharField(max_length=100)
    # Ex.: FUNDO, PORTFOLIO, ACAO, INDICE
    tipo = models.CharField(max_length=50, blank=True)
    primeira_cota = models.DateField(null=True, blank=True)
    gestora = models.CharField(max_length=200, blank=True)
    dados_complementares = models.JSONField(default=dict)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ativo Quantum"
        verbose_name_plural = "Ativos Quantum"

    def __str__(self):
        return f"{self.ativo.nome} (ID: {self.id_quantum})"

    @property
    def is_indice(self):
        return self.tipo == "INDICE"


class CotacaoDiaria(models.Model):
    """Série de valor base-100 por ativo/índice e data."""

    ativo = models.ForeignKey(
        AtivoQuantum, on_delete=models.CASCADE, related_name="cotacoes"
    )
    data = models.DateField(db_index=True)
    valor = models.FloatField()

    class Meta:
        ordering = ["data"]
        unique_together = [("ativo", "data")]
        verbose_name = "Cotação Diária"
        verbose_name_plural = "Cotações Diárias"

    def __str__(self):
        return f"{self.ativo.ativo.nome} {self.data}: {self.valor:.4f}"


class Job(models.Model):
    TIPO_CHOICES = [
        ("buscar_ativos", "Buscar Ativos"),
        ("scrap", "Scrap Cotas"),
    ]
    STATUS_CHOICES = [
        ("running", "Em execução"),
        ("done", "Concluído"),
        ("error", "Erro"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="running")
    detalhe = models.TextField(blank=True)
    erro = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Job"
        verbose_name_plural = "Jobs"

    def __str__(self):
        return f"Job #{self.id} ({self.get_tipo_display()}) — {self.get_status_display()}"
