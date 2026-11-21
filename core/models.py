from datetime import time
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Locality(models.Model):
    """Miejscowość z urzędowego rejestru SIMC."""

    simc_code = models.CharField("Identyfikator SIMC", max_length=7, primary_key=True)
    name = models.CharField("Nazwa miejscowości", max_length=100)
    county_code = models.CharField("Kod powiatu", max_length=2)
    municipality_code = models.CharField("Kod gminy", max_length=2)
    municipality_type_code = models.CharField("Rodzaj gminy", max_length=1)
    locality_type_code = models.CharField("Rodzaj miejscowości", max_length=2)
    registry_date = models.DateField("Stan rejestru")
    latitude = models.FloatField("Szerokość geograficzna", blank=True, null=True)
    longitude = models.FloatField("Długość geograficzna", blank=True, null=True)

    class Meta:
        ordering = ["name", "simc_code"]

    def __str__(self):
        return self.name


class Institution(models.Model):
    """Instytucja, która może zgłaszać lub prowadzić lokalne inicjatywy."""

    class Type(models.TextChoices):
        UNIVERSITY = "university", "Uczelnie"
        SCHOOL = "school", "Szkoły"
        LOCAL_GOVERNMENT = "local_government", "Samorządy"
        OTHER = "other", "Inne instytucje"

    name = models.CharField("Nazwa", max_length=200)
    address = models.CharField("Adres", max_length=255)
    news_url = models.URLField("Adres URL aktualności", blank=True)
    institution_type = models.CharField("Typ instytucji", max_length=80, choices=Type.choices)
    locality = models.ForeignKey(
        Locality,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="institutions",
        verbose_name="Miejscowość",
    )

    class Meta:
        ordering = ["name"]


class InstitutionNewsSource(models.Model):
    """Oficjalna strona aktualności należąca do instytucji lub jej jednostki."""

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="news_sources"
    )
    url = models.URLField("Adres URL aktualności", max_length=500)

    class Meta:
        ordering = ["url"]
        constraints = [
            models.UniqueConstraint(fields=["institution", "url"], name="unique_news_source")
        ]


class Idea(models.Model):
    class InstitutionRole(models.TextChoices):
        CREATOR = "creator", "Twórca"
        CO_CREATOR = "co_creator", "Współtwórca"
        LOCAL_ADAPTOR = "local_adaptor", "Lokalny adaptator"
        LOCAL_REPORTER = "local_reporter", "Instytucja informująca"
        EXTERNAL_REFERENCE = "external_reference", "Relacja zewnętrzna"
        UNKNOWN = "unknown", "Niepewna relacja"

    name = models.CharField("Nazwa pomysłu", max_length=160)
    submitter_name = models.CharField("Imię i nazwisko", max_length=160)
    email = models.EmailField("Adres e-mail")
    creator_name = models.CharField("Twórca inicjatywy", max_length=200, blank=True)
    creator_team = models.TextField("Zespół twórców", blank=True)
    creator_contact = models.CharField("Kontakt do twórcy lub zespołu", max_length=255, blank=True)
    locality = models.ForeignKey(
        Locality,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ideas",
        verbose_name="Miejscowość",
    )
    institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ideas",
        verbose_name="Instytucja źródłowa",
    )
    institution_role = models.CharField(
        "Rola instytucji źródłowej",
        max_length=32,
        choices=InstitutionRole.choices,
        default=InstitutionRole.UNKNOWN,
    )
    implementing_institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="implemented_ideas",
        verbose_name="Instytucja wdrażająca",
    )
    source_url = models.URLField("Adres źródłowego artykułu", blank=True, null=True, unique=True)
    source_label = models.CharField("Nazwa źródła", max_length=120, blank=True)
    content = models.TextField("Opis pomysłu")
    published_at = models.DateField(
        "Data publikacji artykułu", blank=True, null=True, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    innovation_score = models.DecimalField(
        "Wynik innowacyjności", max_digits=4, decimal_places=1, blank=True, null=True
    )
    innovation_details = models.JSONField("Szczegóły oceny", blank=True, default=dict)
    innovation_rationales = models.JSONField("Uzasadnienia oceny", blank=True, default=dict)
    scored_at = models.DateTimeField("Data oceny", blank=True, null=True)
    relative_novelty = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    relative_value = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    relative_replicability = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    relative_impact = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    relative_score = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    relative_scored_at = models.DateTimeField(null=True)
    partner_needs = models.ManyToManyField(
        "PartnerTag",
        blank=True,
        related_name="ideas",
        verbose_name="Potrzeby partnerskie",
    )
    similarity_tags = models.ManyToManyField(
        "SimilarityTag",
        blank=True,
        related_name="ideas",
        verbose_name="Tagi podobieństwa",
    )

    class Meta:
        ordering = ["-scored_at", "-created_at"]

    def __str__(self):
        return self.name


class InnovationIndicator(models.Model):
    """Konfigurowalny wskaźnik używany do oceny innowacyjności."""

    key = models.SlugField("Klucz techniczny", max_length=32, unique=True)
    name = models.CharField("Nazwa", max_length=80)
    question = models.TextField("Pytanie oceniające")
    weight = models.DecimalField(
        "Waga",
        max_digits=3,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    position = models.PositiveSmallIntegerField("Kolejność", default=0)
    enabled = models.BooleanField("Aktywny", default=True)

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return self.name


class IdeaIndicatorScore(models.Model):
    """Ocena jednej innowacji według jednego wskaźnika."""

    idea = models.ForeignKey(Idea, on_delete=models.CASCADE, related_name="indicator_scores")
    indicator = models.ForeignKey(
        InnovationIndicator, on_delete=models.PROTECT, related_name="idea_scores"
    )
    score = models.PositiveSmallIntegerField(
        "Punktacja", blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    rationale = models.TextField("Uzasadnienie", blank=True)

    class Meta:
        ordering = ["indicator__position", "indicator__pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["idea", "indicator"], name="unique_idea_indicator_score"
            )
        ]


class DevelopmentRecommendation(models.Model):
    """Kolejny, możliwy do zatwierdzenia krok rozwoju inicjatywy."""

    class Stage(models.TextChoices):
        CONCEPT = "concept", "Koncepcja"
        PILOT = "pilot", "Pilotaż"
        LOCAL_IMPLEMENTATION = "local_implementation", "Wdrożenie lokalne"
        TRANSFER_READY = "transfer_ready", "Gotowe do transferu"

    class Path(models.TextChoices):
        PILOT = "pilot", "Pilotaż"
        TRANSFER = "transfer", "Transfer do innej organizacji"
        PARTNERSHIP = "partnership", "Partnerstwo rozwojowe"
        FINANCING = "financing", "Przygotowanie do finansowania"
        COMMERCIALISATION = "commercialisation", "Komercjalizacja"
        IMPLEMENTATION = "implementation", "Szersze wdrożenie"

    class Status(models.TextChoices):
        GENERATED = "generated", "Wygenerowana"
        APPROVED = "approved", "Zatwierdzona"
        FAILED = "failed", "Wymaga ponowienia"

    idea = models.OneToOneField(Idea, on_delete=models.CASCADE, related_name="recommendation")
    stage = models.CharField("Etap rozwoju", max_length=32, choices=Stage.choices)
    development_path = models.CharField(
        "Rekomendowana ścieżka", max_length=32, choices=Path.choices
    )
    next_step = models.TextField("Najbliższy krok")
    rationale = models.TextField("Uzasadnienie")
    risk = models.TextField("Ryzyko lub niewiadoma")
    status = models.CharField(
        "Status", max_length=16, choices=Status.choices, default=Status.GENERATED
    )
    error = models.TextField("Błąd generowania", blank=True)
    generated_at = models.DateTimeField("Wygenerowano", auto_now=True)
    approved_at = models.DateTimeField("Zatwierdzono", blank=True, null=True)

    def __str__(self):
        return f"{self.idea}: {self.get_development_path_display()}"


class PartnerTag(models.Model):
    """Wspólny słownik potrzeb inicjatyw i możliwości partnerów."""

    key = models.SlugField("Klucz techniczny", max_length=48, unique=True)
    name = models.CharField("Nazwa", max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SimilarityTag(models.Model):
    """Tag opisujący problem i kontekst rozwiązania na potrzeby podobieństwa."""

    class Category(models.TextChoices):
        PROBLEM = "problem", "Problem"
        AUDIENCE = "audience", "Odbiorcy"
        SECTOR = "sector", "Branża"
        MECHANISM = "mechanism", "Mechanizm"
        SOLUTION_TYPE = "solution_type", "Typ rozwiązania"
        STAGE = "stage", "Etap"
        TERRITORY = "territory", "Obszar terytorialny"

    category = models.CharField("Kategoria", max_length=24, choices=Category.choices)
    key = models.SlugField("Klucz techniczny", max_length=64)
    name = models.CharField("Nazwa", max_length=100)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(fields=["category", "key"], name="unique_similarity_tag")
        ]

    def __str__(self):
        return f"{self.get_category_display()}: {self.name}"


class PartnerOrganization(models.Model):
    """Organizacja mogąca wesprzeć dalszy rozwój inicjatywy."""

    class Type(models.TextChoices):
        USER = "user", "Użytkownik rozwiązania"
        IMPLEMENTATION = "implementation", "Partner wdrożeniowy"
        EXPERT = "expert", "Ekspert"
        FUNDER = "funder", "Finansujący / program wsparcia"

    name = models.CharField("Nazwa", max_length=160, unique=True)
    organization_type = models.CharField("Typ", max_length=20, choices=Type.choices)
    description = models.TextField("Opis")
    contact = models.CharField("Kontakt", max_length=255, blank=True)
    contact_url = models.URLField("Adres kontaktowy", blank=True)
    locality = models.ForeignKey(
        Locality,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="partner_organizations",
        verbose_name="Miejscowość",
    )
    areas = models.TextField("Obszary działania", blank=True)
    tags = models.ManyToManyField(PartnerTag, blank=True, related_name="organizations")
    is_active = models.BooleanField("Aktywny", default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InstitutionImportRun(models.Model):
    """Trwały zapis pełnego przebiegu pobierania innowacji z aktualności."""

    started_at = models.DateTimeField("Rozpoczęto", auto_now_add=True)
    finished_at = models.DateTimeField("Zakończono", blank=True, null=True)
    status = models.CharField(max_length=16, default="running")
    institution_types = models.JSONField(default=list)
    institutions_processed = models.PositiveIntegerField(default=0)
    ideas_created = models.PositiveIntegerField(default=0)
    ideas_skipped = models.PositiveIntegerField(default=0)
    duration_seconds = models.FloatField(blank=True, null=True)
    institutions_per_minute = models.FloatField(blank=True, null=True)
    error = models.TextField(blank=True)
    institutions_total = models.PositiveIntegerField(default=0)
    current_institution = models.CharField(max_length=200, blank=True)
    current_action = models.CharField(max_length=200, blank=True)
    news_source_index = models.PositiveIntegerField(default=0)
    article_queue = models.JSONField(blank=True, null=True)
    article_index = models.PositiveIntegerField(default=0)
    retry_after = models.DateTimeField(blank=True, null=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-started_at"]


class InstitutionImportEvent(models.Model):
    """Ostatnie kroki importu wyświetlane w panelu administracyjnym."""

    run = models.ForeignKey(InstitutionImportRun, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=500)

    class Meta:
        ordering = ["-created_at", "-pk"]


class NCBRImportRun(models.Model):
    """Trwały zapis niezależnego importu projektów z katalogu NCBR."""

    started_at = models.DateTimeField("Rozpoczęto", auto_now_add=True)
    finished_at = models.DateTimeField("Zakończono", blank=True, null=True)
    status = models.CharField(max_length=16, default="pending")
    projects_total = models.PositiveIntegerField(default=0)
    projects_processed = models.PositiveIntegerField(default=0)
    ideas_created = models.PositiveIntegerField(default=0)
    ideas_skipped = models.PositiveIntegerField(default=0)
    current_action = models.CharField(max_length=200, blank=True)
    error = models.TextField(blank=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-started_at"]


class NCBRImportEvent(models.Model):
    """Ostatnie kroki importu NCBR widoczne w panelu administracyjnym."""

    run = models.ForeignKey(NCBRImportRun, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=500)

    class Meta:
        ordering = ["-created_at", "-pk"]


class CrawlSchedule(models.Model):
    """Konfiguracja automatycznego uruchamiania pełnego crawlowania."""

    enabled = models.BooleanField("Włącz automatyczny crawling", default=False)
    interval_days = models.PositiveSmallIntegerField("Uruchamiaj co ile dni", default=7)
    run_at = models.TimeField("Godzina uruchomienia", default=time(3))
    next_run_at = models.DateTimeField("Następne uruchomienie", blank=True, null=True)
    last_started_at = models.DateTimeField(
        "Ostatnie automatyczne uruchomienie", blank=True, null=True
    )


class PromptTemplate(models.Model):
    """Edytowalna treść promptu wykorzystywanego przez usługi LLM."""

    key = models.CharField(max_length=64, primary_key=True)
    content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]


class ScoringCalibration(models.Model):
    """Jedyna konfiguracja opcjonalnej kalibracji ocen LLM."""

    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class ScoringCalibrationExample(models.Model):
    """Przykład referencyjny dla pojedynczego kryterium oceny."""

    calibration = models.ForeignKey(
        ScoringCalibration, on_delete=models.CASCADE, related_name="examples"
    )
    criterion = models.CharField("Klucz wskaźnika", max_length=32)
    title = models.CharField(max_length=160)
    description = models.TextField()
    score = models.PositiveSmallIntegerField()
    rationale = models.TextField()
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["criterion", "position", "pk"]


class InnovationIndicatorSettings(models.Model):
    """Wagi czterech obecnych wskaźników wyniku innowacyjności."""

    novelty_weight = models.DecimalField(
        "Waga: Nowatorstwo",
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.30"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    value_weight = models.DecimalField(
        "Waga: Wartość innowacji",
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.30"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    replicability_weight = models.DecimalField(
        "Waga: Replikowalność",
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.20"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    impact_weight = models.DecimalField(
        "Waga: Potencjał oddziaływania",
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.20"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    updated_at = models.DateTimeField(auto_now=True)


class RankingRun(models.Model):
    """Niezmienna pula wejściowa oraz trwały checkpoint porównań LLM."""

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, default="pending")
    model = models.CharField(max_length=100)
    prompt = models.TextField()
    snapshot = models.JSONField()
    comparisons = models.JSONField(default=dict)
    results = models.JSONField(default=dict)
    error = models.TextField(blank=True)


class ScoringOrderStudy(models.Model):
    """Zamrożony plan ograniczonego badania zgodności kolejności."""

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, default="pending")
    model = models.CharField(max_length=100)
    prompt = models.TextField()
    seed = models.PositiveIntegerField()
    sample_per_stratum = models.PositiveSmallIntegerField()
    population_counts = models.JSONField(default=dict)
    error = models.TextField(blank=True)


class ScoringOrderPair(models.Model):
    """Pojedyncze porównanie z pełną kopią danych wejściowych i odpowiedzi."""

    study = models.ForeignKey(ScoringOrderStudy, on_delete=models.CASCADE, related_name="pairs")
    position = models.PositiveIntegerField()
    criterion = models.CharField(max_length=32)
    stratum = models.CharField(max_length=16)
    left_idea_id = models.PositiveIntegerField()
    right_idea_id = models.PositiveIntegerField()
    left_name = models.CharField(max_length=160)
    right_name = models.CharField(max_length=160)
    left_content = models.TextField()
    right_content = models.TextField()
    left_score = models.PositiveSmallIntegerField()
    right_score = models.PositiveSmallIntegerField()
    outcome = models.CharField(max_length=16, blank=True)
    rationale = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["study", "position"], name="unique_study_position"),
            models.UniqueConstraint(
                fields=["study", "criterion", "left_idea_id", "right_idea_id"],
                name="unique_study_pair",
            ),
        ]


class OverallOrderStudy(models.Model):
    """Zamrożona próba do sprawdzenia kolejności wyników końcowych."""

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, default="pending")
    model = models.CharField(max_length=100)
    prompt = models.TextField()
    seed = models.PositiveIntegerField()
    sample_per_stratum = models.PositiveSmallIntegerField()
    repeat_count = models.PositiveSmallIntegerField()
    population_counts = models.JSONField(default=dict)
    error = models.TextField(blank=True)


class OverallOrderPair(models.Model):
    """Pojedynczy osąd łącznego potencjału z kopią danych wejściowych."""

    study = models.ForeignKey(OverallOrderStudy, on_delete=models.CASCADE, related_name="pairs")
    repeat_of = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True)
    position = models.PositiveIntegerField()
    stratum = models.CharField(max_length=16)
    left_idea_id = models.PositiveIntegerField()
    right_idea_id = models.PositiveIntegerField()
    left_name = models.CharField(max_length=160)
    right_name = models.CharField(max_length=160)
    left_content = models.TextField()
    right_content = models.TextField()
    left_score = models.DecimalField(max_digits=4, decimal_places=1)
    right_score = models.DecimalField(max_digits=4, decimal_places=1)
    outcome = models.CharField(max_length=16, blank=True)
    rationale = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["study", "position"], name="unique_overall_position"),
        ]
