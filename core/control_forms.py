"""Formularze własnego panelu administracyjnego."""

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.text import slugify

from core.models import (
    CrawlSchedule,
    DevelopmentRecommendation,
    Idea,
    InnovationIndicator,
    InnovationIndicatorSettings,
    Institution,
    InstitutionNewsSource,
    Locality,
    PartnerOrganization,
    PartnerTag,
    ScoringCalibration,
    ScoringCalibrationExample,
)
from core.services.prompt_registry import PromptDefinition


class CredentialsForm(forms.Form):
    username = forms.CharField(label="Nazwa użytkownika", max_length=150)
    password1 = forms.CharField(
        label="Nowe hasło", required=False, strip=False, widget=forms.PasswordInput
    )
    password2 = forms.CharField(
        label="Powtórz nowe hasło", required=False, strip=False, widget=forms.PasswordInput
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["username"].initial = user.username

    def clean_username(self):
        username = self.cleaned_data["username"]
        if get_user_model().objects.exclude(pk=self.user.pk).filter(username=username).exists():
            raise ValidationError("Ta nazwa użytkownika jest już zajęta.")
        return username

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 != password2:
            self.add_error("password2", "Hasła muszą być takie same.")
        elif password1:
            validate_password(password1, self.user)
        return cleaned

    def save(self):
        self.user.username = self.cleaned_data["username"]
        if self.cleaned_data["password1"]:
            self.user.set_password(self.cleaned_data["password1"])
        self.user.save()
        return self.user


class InstitutionPanelForm(forms.ModelForm):
    additional_news_urls = forms.CharField(
        label="Dodatkowe adresy aktualności",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Jeden adres URL w wierszu"}),
    )

    class Meta:
        model = Institution
        fields = ["name", "address", "institution_type", "locality", "news_url"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["locality"].queryset = Locality.objects.order_by("name", "simc_code")
        self.fields["locality"].required = True
        self.fields["locality"].widget = forms.HiddenInput()
        if self.instance.pk:
            self.fields["additional_news_urls"].initial = "\n".join(
                self.instance.news_sources.values_list("url", flat=True)
            )

    def clean_additional_news_urls(self):
        urls = [
            url.strip()
            for url in self.cleaned_data["additional_news_urls"].splitlines()
            if url.strip()
        ]
        for url in urls:
            URLValidator(schemes=["http", "https"])(url)
        return urls

    def save(self, commit=True):
        institution = super().save(commit)
        if commit:
            InstitutionNewsSource.objects.filter(institution=institution).delete()
            InstitutionNewsSource.objects.bulk_create(
                [
                    InstitutionNewsSource(institution=institution, url=url)
                    for url in self.cleaned_data["additional_news_urls"]
                ]
            )
        return institution


class InstitutionListFilterForm(forms.Form):
    """Filtry listy instytucji w panelu administracyjnym."""

    institution_type = forms.ChoiceField(
        label="Typ instytucji",
        choices=[("", "Wszystkie typy"), *Institution.Type.choices],
        required=False,
    )
    locality = forms.ModelChoiceField(
        label="Miejscowość",
        queryset=Locality.objects.order_by("name", "simc_code"),
        required=False,
        widget=forms.HiddenInput(),
    )
    published_from = forms.DateField(
        label="Data publikacji od",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    published_to = forms.DateField(
        label="Data publikacji do",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned = super().clean()
        date_from, date_to = cleaned.get("published_from"), cleaned.get("published_to")
        if date_from and date_to and date_from > date_to:
            self.add_error("published_to", "Data końcowa nie może być wcześniejsza niż początkowa.")
        return cleaned


class CrawlScheduleForm(forms.ModelForm):
    """Ustawienia okresowego pełnego przebiegu crawlera."""

    class Meta:
        model = CrawlSchedule
        fields = ["enabled", "interval_days", "run_at"]
        labels = {
            "enabled": "Włącz automatyczny crawling",
            "interval_days": "Uruchamiaj co ile dni",
            "run_at": "Godzina uruchomienia",
        }
        widgets = {
            "interval_days": forms.NumberInput(attrs={"min": 1, "max": 365}),
            "run_at": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean_interval_days(self):
        interval_days = self.cleaned_data["interval_days"]
        if not 1 <= interval_days <= 365:
            raise ValidationError("Podaj liczbę dni od 1 do 365.")
        return interval_days


class PromptTemplatesForm(forms.Form):
    """Dynamiczny formularz wszystkich promptów z katalogu aplikacji."""

    def __init__(self, definitions: tuple[PromptDefinition, ...], *args, **kwargs):
        initial = kwargs.pop("initial", {})
        super().__init__(*args, initial=initial, **kwargs)
        for definition in definitions:
            self.fields[definition.key] = forms.CharField(
                label=definition.label,
                help_text=definition.description,
                widget=forms.Textarea(attrs={"rows": 12}),
            )


class ScoringCalibrationForm(forms.ModelForm):
    """Przełącznik używania przykładów kalibracyjnych w oceniaczu."""

    class Meta:
        model = ScoringCalibration
        fields = ["enabled"]
        labels = {"enabled": "Włącz kalibrację podczas kolejnych ocen"}


class InnovationIndicatorForm(forms.ModelForm):
    """Edycja definicji wskaźnika innowacyjności."""

    class Meta:
        model = InnovationIndicator
        fields = ["key", "name", "question"]
        widgets = {
            "question": forms.Textarea(attrs={"rows": 4}),
        }


class InnovationIndicatorConfigurationForm(forms.Form):
    """Zapisuje atomowo wagi i aktywność wszystkich wskaźników."""

    def __init__(self, indicators, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indicators = tuple(indicators)
        for indicator in self.indicators:
            self.fields[f"weight_{indicator.pk}"] = forms.DecimalField(
                label="Waga",
                min_value=Decimal("0"),
                max_value=Decimal("1"),
                decimal_places=2,
                max_digits=3,
                initial=indicator.weight,
                widget=forms.NumberInput(attrs={"min": 0, "max": 1, "step": "0.01"}),
            )
            self.fields[f"enabled_{indicator.pk}"] = forms.BooleanField(
                label="Aktywny", required=False, initial=indicator.enabled
            )

    def clean(self):
        cleaned = super().clean()
        active_weights = [
            cleaned.get(f"weight_{indicator.pk}")
            for indicator in self.indicators
            if cleaned.get(f"enabled_{indicator.pk}")
        ]
        if not active_weights:
            raise ValidationError("Włącz co najmniej jeden wskaźnik.")
        if sum(active_weights, Decimal("0")) != Decimal("1.00"):
            raise ValidationError("Suma wag aktywnych wskaźników musi wynosić dokładnie 1,00.")
        return cleaned

    def save(self):
        for indicator in self.indicators:
            indicator.weight = self.cleaned_data[f"weight_{indicator.pk}"]
            indicator.enabled = self.cleaned_data[f"enabled_{indicator.pk}"]
        InnovationIndicator.objects.bulk_update(self.indicators, ["weight", "enabled"])

class InnovationIndicatorSettingsForm(forms.ModelForm):
    """Historyczny formularz utrzymany do czasu usunięcia starej konfiguracji."""

    class Meta:
        model = InnovationIndicatorSettings
        fields = ["novelty_weight", "value_weight", "replicability_weight", "impact_weight"]


class ScoringCalibrationExampleForm(forms.ModelForm):
    """Edycja pojedynczego przykładu kalibracyjnego."""

    class Meta:
        model = ScoringCalibrationExample
        fields = ["title", "description", "score", "rationale"]
        labels = {
            "title": "Nazwa przykładu",
            "description": "Opis przykładu",
            "score": "Punktacja",
            "rationale": "Uzasadnienie punktacji",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "rationale": forms.Textarea(attrs={"rows": 3}),
            "score": forms.NumberInput(attrs={"min": 0, "max": 100}),
        }

    def clean_score(self):
        score = self.cleaned_data["score"]
        if not 0 <= score <= 100:
            raise ValidationError("Punktacja musi być liczbą od 0 do 100.")
        return score


class NewScoringCalibrationExampleForm(ScoringCalibrationExampleForm):
    """Dodawanie przykładu wraz z wyborem kryterium, którego dotyczy."""

    class Meta(ScoringCalibrationExampleForm.Meta):
        fields = ["criterion", "title", "description", "score", "rationale"]
        labels = {
            **ScoringCalibrationExampleForm.Meta.labels,
            "criterion": "Kryterium",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["criterion"].widget = forms.Select(
            choices=[
                (item.key, item.name) for item in InnovationIndicator.objects.filter(enabled=True)
            ]
        )


class DevelopmentRecommendationForm(forms.ModelForm):
    """Merytoryczna korekta rekomendacji wygenerowanej przez LLM."""

    class Meta:
        model = DevelopmentRecommendation
        fields = ["stage", "development_path", "next_step", "rationale", "risk", "status"]
        labels = {
            "stage": "Etap rozwoju",
            "development_path": "Rekomendowana ścieżka",
            "next_step": "Najbliższy krok",
            "rationale": "Uzasadnienie",
            "risk": "Ryzyko lub najważniejsza niewiadoma",
            "status": "Status publikacji",
        }
        widgets = {
            "next_step": forms.Textarea(attrs={"rows": 3}),
            "rationale": forms.Textarea(attrs={"rows": 4}),
            "risk": forms.Textarea(attrs={"rows": 3}),
        }


class IdeaPartnerNeedsForm(forms.ModelForm):
    """Ustawia potrzeby, według których wyszukiwani są partnerzy inicjatywy."""

    class Meta:
        from core.models import Idea

        model = Idea
        fields = ["partner_needs"]
        labels = {"partner_needs": "Potrzeby inicjatywy"}
        widgets = {"partner_needs": forms.CheckboxSelectMultiple}


class IdeaProvenanceForm(forms.ModelForm):
    """Pozwala uzupełnić twórców oraz relacje instytucjonalne inicjatywy."""

    class Meta:
        model = Idea
        fields = [
            "creator_name",
            "creator_team",
            "creator_contact",
            "institution",
            "institution_role",
            "implementing_institution",
        ]
        widgets = {
            "creator_team": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        institutions = Institution.objects.order_by("name")
        self.fields["institution"].queryset = institutions
        self.fields["implementing_institution"].queryset = institutions
        self.fields["institution_role"].required = False

    def clean_institution_role(self):
        return self.cleaned_data["institution_role"] or Idea.InstitutionRole.UNKNOWN


class PartnerOrganizationForm(forms.ModelForm):
    """CRUD partnera wraz z czytelną edycją tagów tekstowych."""

    tags_text = forms.CharField(
        label="Tagi możliwości",
        required=False,
        help_text="Oddziel tagi przecinkami, np. pilotaż, badania, finansowanie.",
    )

    class Meta:
        model = PartnerOrganization
        fields = [
            "name",
            "organization_type",
            "description",
            "contact",
            "contact_url",
            "locality",
            "areas",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "areas": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["locality"].queryset = Locality.objects.order_by("name", "simc_code")
        if self.instance.pk:
            self.fields["tags_text"].initial = ", ".join(
                self.instance.tags.values_list("name", flat=True)
            )

    def save(self, commit=True):
        partner = super().save(commit)
        if commit:
            tags = []
            tag_names = {
                item.strip() for item in self.cleaned_data["tags_text"].split(",") if item.strip()
            }
            for name in tag_names:
                key = slugify(name)
                tag, _ = PartnerTag.objects.get_or_create(key=key, defaults={"name": name})
                tags.append(tag)
            partner.tags.set(tags)
        return partner
