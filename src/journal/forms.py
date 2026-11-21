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
    category = forms.ChoiceField(label="Catégorie", choices=Version.CATEGORIES, widget=forms.RadioSelect,
                                 initial="config")
    kind = forms.ChoiceField(label="Déroulement", choices=Version.KINDS, widget=forms.RadioSelect, initial=Version.NORMAL)
    title = forms.CharField(label="Titre", max_length=200)
    occurred_at = forms.DateTimeField(
        label="Date de l’intervention", widget=DATETIME_WIDGET,
        help_text="Pour une intervention planifiée : la date prévue.")
    elements = forms.ModelMultipleChoiceField(
        label="Éléments concernés", queryset=Element.objects.none(), widget=forms.CheckboxSelectMultiple)
    change = forms.CharField(label="Ce qui a changé", widget=forms.Textarea(attrs={
        **TEXTAREA, "placeholder": "Ex. GPO SEC-Block-NTLM liée à l’OU Serveurs : « Restreindre NTLM » = Refuser tout"}))
    reason = forms.CharField(label="Pourquoi", required=False, widget=forms.Textarea(attrs={
        **TEXTAREA, "placeholder": "Contexte, demande, ticket, incident…"}))
    impact = forms.CharField(label="Impacts potentiels à surveiller", required=False, widget=forms.Textarea(attrs={
        **TEXTAREA, "placeholder": "Ex. Risque sur les vieux applicatifs qui utilisent encore NTLM. « Aucun » si rien."}))
    rollback = forms.CharField(label="Procédure de retour arrière", required=False, widget=forms.Textarea(attrs={
        **TEXTAREA, "placeholder": "Ex. Délier la GPO SEC-Block-NTLM, ou repasser le paramètre en mode audit."}))
    verification = forms.CharField(label="Vérifications effectuées", required=False,
                                   widget=forms.Textarea(attrs=TEXTAREA))
    before_state = forms.CharField(label="Avant", required=False, widget=forms.Textarea(attrs=CODE_AREA),
                                   help_text="La première ligne sert de résumé dans le registre.")
    after_state = forms.CharField(label="Après", required=False, widget=forms.Textarea(attrs=CODE_AREA),
                                  help_text="La première ligne sert de résumé dans le registre.")

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
                    self.add_error(name, "À renseigner, sauf pour une urgence à compléter plus tard.")
        return data


class CorrectionForm(InterventionForm):
    note = forms.CharField(label="Motif de la correction", max_length=300,
                           help_text="Obligatoire : il sera visible dans l’historique de la fiche.")
    field_order = ["note"]


class CompleteForm(forms.Form):
    occurred_at = forms.DateTimeField(label="Date réelle de l’intervention", widget=DATETIME_WIDGET)
    verification = forms.CharField(label="Vérifications effectuées", widget=forms.Textarea(attrs=TEXTAREA))
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
    element = forms.TypedChoiceField(label="Élément", required=False, coerce=int, empty_value=None)
    category = forms.ChoiceField(label="Catégorie", required=False, widget=forms.RadioSelect,
                                 choices=[("", "Toutes")] + Version.CATEGORIES)
    kind = forms.ChoiceField(label="Déroulement", required=False, widget=forms.RadioSelect,
                             choices=[("", "Tous")] + Version.KINDS)
    period = forms.ChoiceField(label="Période", required=False, widget=forms.RadioSelect, choices=[
        ("", "Tout"), ("24h", "24 h"), ("48h", "48 h"), ("7j", "7 jours"), ("30j", "30 jours")])

    def __init__(self, data=None, *args, **kwargs):
        # Formulaire toujours lié : les valeurs absentes valent « tout », ce qui coche le bon bouton.
        data = data.copy() if data is not None else {}
        for key in ("q", "element", "category", "kind", "period"):
            data.setdefault(key, "")
        super().__init__(data, *args, **kwargs)
        groups = {}
        for element in Element.objects.order_by("group", "name"):
            groups.setdefault(element.get_group_display(), []).append(
                (element.pk, element.name + (" (archivé)" if element.archived else "")))
        self.fields["element"].choices = [("", "Tous les éléments")] + list(groups.items())


def element_groups(form):
    """Éléments proposés dans le formulaire, regroupés par domaine, avec leur état coché."""
    field = form["elements"]
    selected = {str(v.pk if hasattr(v, "pk") else v) for v in (field.value() or [])}
    groups = {}
    for element in form.fields["elements"].queryset.order_by("group", "name"):
        groups.setdefault(element.get_group_display(), []).append((element, str(element.pk) in selected))
    return list(groups.items())
