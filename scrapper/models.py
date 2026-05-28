from django.db import models

from scrapper.quantum.catalogo import TipoAtivo


class Ativo(models.Model):
    """Ativo unificado do Quantum. Chave natural: (tipo, id_quantum)."""

    TIPO_CHOICES = [(t.value, t.value) for t in TipoAtivo]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    id_quantum = models.CharField(max_length=100)  # string (cobre RENDA_FIXA)
    subtipo = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=200)
    # Colunas promovidas (consultáveis/indexadas)
    # cnpj é indexado mas não-único: a unicidade é garantida pela chave natural
    # (tipo, id_quantum), e o mesmo CNPJ pode aparecer sob tipos distintos.
    cnpj = models.CharField(max_length=20, blank=True, default="", db_index=True)
    ticker = models.CharField(max_length=20, blank=True, default="", db_index=True)
    setor = models.CharField(max_length=120, blank=True, default="")
    gestora = models.CharField(max_length=200, blank=True, default="")
    primeira_cota = models.DateField(null=True, blank=True)
    # Resto dos metadados (já validado por pydantic; meta.model_dump())
    metadados = models.JSONField(default=dict)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Ativo"
        verbose_name_plural = "Ativos"
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "id_quantum"], name="ativo_natural_key"
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.tipo})"

    @property
    def is_indice(self) -> bool:
        return self.tipo == TipoAtivo.INDICE


class CotacaoDiaria(models.Model):
    """Série de valor base-100 por ativo e data."""

    ativo = models.ForeignKey(
        Ativo, on_delete=models.CASCADE, related_name="cotacoes"
    )
    data = models.DateField(db_index=True)
    valor = models.FloatField()

    class Meta:
        ordering = ["data"]
        unique_together = [("ativo", "data")]
        verbose_name = "Cotação Diária"
        verbose_name_plural = "Cotações Diárias"

    def __str__(self):
        return f"{self.ativo.nome} {self.data}: {self.valor:.4f}"


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


class CarteiraFundo(models.Model):
    """Composição da carteira de um fundo numa competência (mês de referência)."""

    ativo = models.ForeignKey(
        Ativo, on_delete=models.CASCADE, related_name="carteiras"
    )
    competencia = models.DateField()
    importada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-competencia"]
        verbose_name = "Carteira de Fundo"
        verbose_name_plural = "Carteiras de Fundo"
        constraints = [
            models.UniqueConstraint(
                fields=["ativo", "competencia"], name="carteira_ativo_competencia"
            )
        ]

    def __str__(self):
        return f"{self.ativo.nome} — {self.competencia:%m/%Y}"


class PosicaoCarteira(models.Model):
    """Uma posição (ativo investido) dentro de uma CarteiraFundo."""

    carteira = models.ForeignKey(
        CarteiraFundo, on_delete=models.CASCADE, related_name="posicoes"
    )
    nome = models.CharField(max_length=255)
    participacao = models.FloatField()
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem"]
        verbose_name = "Posição da Carteira"
        verbose_name_plural = "Posições da Carteira"

    def __str__(self):
        return f"{self.nome}: {self.participacao:.2f}%"
