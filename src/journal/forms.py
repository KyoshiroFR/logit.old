from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Element, Version

DATETIME_WIDGET = forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})
TEXTAREA = {"rows": 3}
CODE_AREA = {"rows": 8, "spellcheck": "false", "class": "code"}
# Tolérance pour les horloges des postes légèrement en avance.
FUTURE_TOLERANCE = timedelta(minutes=5)


class InterventionForm(forms.Form):
    kind = forms.ChoiceField(label="Type", choices=Version.KINDS, widget=forms.RadioSelect, initial=Version.NORMAL)
    title = forms.CharField(label="Titre", max_length=200)
    occurred_at = forms.DateTimeField(
        label="Date de l’intervention", widget=DATETIME_WIDGET,
        help_text="Pour une intervention planifiée : la date prévue.")
    elements = forms.ModelMultipleChoiceField(
        label="Éléments concernés", queryset=Element.objects.none(), widget=forms.CheckboxSelectMultiple)
    change = forms.CharField(label="Modification", widget=forms.Textarea(attrs=TEXTAREA),
                             help_text="Ce qui a été changé, concrètement.")
    reason = forms.CharField(label="Motif", required=False, widget=forms.Textarea(attrs=TEXTAREA),
                             help_text="Pourquoi : demande, incident, référence de ticket…")
    impact = forms.CharField(label="Impact", required=False, widget=forms.Textarea(attrs=TEXTAREA),
                             help_text="Services touchés, coupure éventuelle, utilisateurs concernés.")
    verification = forms.CharField(label="Vérifications", required=False, widget=forms.Textarea(attrs=TEXTAREA),
                                   help_text="Ce qui a été contrôlé après l’intervention, et le résultat.")
    rollback = forms.CharField(label="Retour arrière", required=False, widget=forms.Textarea(attrs=TEXTAREA),
                               help_text="Comment annuler la modification. Si c’est impossible, explique pourquoi.")
    before_state = forms.CharField(label="État avant", required=False, widget=forms.Textarea(attrs=CODE_AREA))
    after_state = forms.CharField(label="État après", required=False, widget=forms.Textarea(attrs=CODE_AREA))

    def __init__(self, *args, current_elements=(), **kwargs):
        super().__init__(*args, **kwargs)
        ids = [e.pk for e in current_elements]
        self.fields["elements"].queryset = (Element.objects.filter(archived=False) | Element.objects.filter(pk__in=ids)).distinct()
        if not self.is_bound and "occurred_at" not in self.initial:
            self.initial["occurred_at"] = timezone.localtime().replace(second=0, microsecond=0)

    def clean(self):
        data = super().clean()
        kind, occurred = data.get("kind"), data.get("occurred_at")
        if kind and occurred and kind != Version.PLANNED and occurred > timezone.now() + FUTURE_TOLERANCE:
            self.add_error("occurred_at", "Une intervention réalisée ne peut pas être datée dans le futur. "
                                          "Choisis « Planifiée » pour une intervention à venir.")
        if kind and kind != Version.URGENT:
            for name in Version.REQUIRED_FOR_COMPLETE:
                if not (data.get(name) or "").strip():
                    self.add_error(name, "Obligatoire, sauf pour une urgence à compléter plus tard.")
        return data


class CorrectionForm(InterventionForm):
    note = forms.CharField(label="Motif de la correction", max_length=300,
                           help_text="Obligatoire : il sera visible dans l’historique de la fiche.")
    field_order = ["note"]


class CompleteForm(forms.Form):
    occurred_at = forms.DateTimeField(label="Date réelle de l’intervention", widget=DATETIME_WIDGET)
    verification = forms.CharField(label="Vérifications", widget=forms.Textarea(attrs=TEXTAREA))
    note = forms.CharField(label="Commentaire", max_length=300, required=False)

    def clean_occurred_at(self):
        value = self.cleaned_data["occurred_at"]
        if value > timezone.now() + FUTURE_TOLERANCE:
            raise forms.ValidationError("La date réelle ne peut pas être dans le futur.")
        return value


class CancelForm(forms.Form):
    note = forms.CharField(label="Motif de l’annulation", max_length=300)


class FilterForm(forms.Form):
    q = forms.CharField(label="Recherche", required=False, max_length=200)
    element = forms.ModelChoiceField(label="Élément", queryset=Element.objects.all(), required=False,
                                     empty_label="Tous les éléments")
    kind = forms.ChoiceField(label="Type", choices=[("", "Tous les types")] + Version.KINDS, required=False)
    period = forms.ChoiceField(label="Période", required=False, choices=[
        ("", "Toute période"), ("24h", "24 dernières heures"), ("48h", "48 dernières heures"),
        ("7j", "7 derniers jours"), ("30j", "30 derniers jours")])
