from django import forms

from .models import Idea, Locality


class IdeaForm(forms.ModelForm):
    use_required_attribute = False
    locality = forms.ModelChoiceField(queryset=Locality.objects.all(), required=True)
    privacy_accepted = forms.BooleanField(required=True)

    class Meta:
        model = Idea
        fields = ["name", "submitter_name", "email", "locality", "content"]
        labels = {"submitter_name": "Imię i nazwisko autora"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "np. Sąsiedzka pracownia pomysłów"}),
            "submitter_name": forms.TextInput(attrs={"placeholder": "np. Anna Kowalska"}),
            "email": forms.EmailInput(attrs={"placeholder": "anna@example.org"}),
            "content": forms.Textarea(attrs={"class": "wysiwyg-value", "hidden": True}),
        }

    def save(self, commit=True):
        """Zapisuje autora ręcznego zgłoszenia także w publicznym opisie inicjatywy."""
        idea = super().save(commit=False)
        idea.creator_name = idea.creator_name or idea.submitter_name
        if commit:
            idea.save()
            self.save_m2m()
        return idea
