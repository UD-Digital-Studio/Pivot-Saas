from django.utils.translation import gettext_lazy as _
import uuid

from django import forms
from django.contrib.auth import get_user_model

from apps.collaboration.models import EvidenceRecord
from apps.planning.models import ProjectStage

from .models import (
    InventoryAnomalyResolution, InventoryExpectedRange, StockItem, StockMovement,
)


class StockItemForm(forms.ModelForm):
    class Meta:
        model = StockItem
        fields = ("name", "unit", "unit_price", "quantity", "alert_threshold")
        widgets = {
            "unit_price": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "quantity": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "alert_threshold": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }


class StockAdjustmentForm(forms.Form):
    movement_type = forms.ChoiceField(label=_("Nature"), choices=(
        (StockMovement.Type.PURCHASED, "Acheté"),
        (StockMovement.Type.DELIVERED, "Livré sur le chantier"),
        (StockMovement.Type.CONSUMED, "Consommé"),
    ))
    source_quantity = forms.DecimalField(label=_("Quantité source"), max_digits=16, decimal_places=4, min_value=0.0001)
    source_unit = forms.CharField(label=_("Unité source"), max_length=30)
    conversion_factor = forms.DecimalField(label=_("Facteur vers l'unité de stock"), max_digits=16, decimal_places=6, min_value=0.000001, initial=1)
    source_reference = forms.CharField(label=_("Source / référence"), max_length=200)
    evidence = forms.ModelChoiceField(
        label=_("Facture ou bon existant"), queryset=EvidenceRecord.objects.none(), required=False,
    )
    stage = forms.ModelChoiceField(
        label=_("Étape concernée"), queryset=ProjectStage.objects.none(), required=False,
    )
    reason = forms.CharField(label=_("Motif"), max_length=500)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["evidence"].queryset = project.evidence_records.filter(
                evidence_type__in=(EvidenceRecord.Type.INVOICE, EvidenceRecord.Type.DELIVERY_NOTE)
            ).exclude(status=EvidenceRecord.Status.REJECTED)
            self.fields["stage"].queryset = project.stages.all()
        if not self.is_bound:
            self.fields["idempotency_key"].initial = uuid.uuid4()


class StockImportForm(forms.Form):
    file = forms.FileField(label=_("Fichier CSV"))

    def clean_file(self):
        file = self.cleaned_data["file"]
        if not file.name.lower().endswith(".csv"):
            raise forms.ValidationError(_("Le fichier doit être au format CSV."))
        if file.size > 2 * 1024 * 1024:
            raise forms.ValidationError(_("Le fichier ne doit pas dépasser 2 Mo."))
        return file


class ExpectedRangeAssignmentForm(forms.Form):
    existing_range = forms.ModelChoiceField(
        label=_("Sélectionner une plage existante"),
        queryset=InventoryExpectedRange.objects.none(), required=False,
    )
    work_type = forms.CharField(label=_("Ouvrage"), max_length=200, required=False)
    unit = forms.CharField(label=_("Unité"), max_length=30, required=False)
    minimum_quantity = forms.DecimalField(label=_("Minimum attendu"), min_value=0, required=False)
    maximum_quantity = forms.DecimalField(label=_("Maximum attendu"), min_value=0, required=False)
    assumptions = forms.CharField(
        label=_("Hypothèses techniques"), required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    out_of_range_action = forms.ChoiceField(
        label=_("Action en cas d'écart"),
        choices=InventoryExpectedRange.OutOfRangeAction.choices,
        required=False,
        initial=InventoryExpectedRange.OutOfRangeAction.FLAG,
    )

    def __init__(self, *args, project, item, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        self.fields["existing_range"].queryset = project.inventory_expected_ranges.all()
        self.fields["unit"].initial = item.unit

    def clean(self):
        cleaned = super().clean()
        existing = cleaned.get("existing_range")
        definition = [cleaned.get(key) for key in (
            "work_type", "unit", "minimum_quantity", "maximum_quantity", "assumptions"
        )]
        if not existing and any(value in (None, "") for value in definition):
            raise forms.ValidationError(_("Tous les champs de la nouvelle plage sont obligatoires."))
        if existing and existing.unit != self.item.unit:
            raise forms.ValidationError(_("L'unité de la plage doit correspondre à celle de l'article."))
        if not existing and cleaned.get("unit") != self.item.unit:
            raise forms.ValidationError(_("L'unité doit correspondre à celle de l'article."))
        if not existing and cleaned.get("minimum_quantity") > cleaned.get("maximum_quantity"):
            raise forms.ValidationError(_("Le minimum ne peut pas dépasser le maximum."))
        if not existing and not cleaned.get("out_of_range_action"):
            self.add_error("out_of_range_action", "Choisissez l'action applicable en cas d'écart.")
        return cleaned


class InventoryAnomalyResolutionForm(forms.Form):
    responsible = forms.ModelChoiceField(label=_("Responsable"), queryset=get_user_model().objects.none())
    evidence = forms.ModelMultipleChoiceField(
        label=_("Preuves de résolution"), queryset=EvidenceRecord.objects.none()
    )
    reason = forms.CharField(
        label=_("Motif et actions réalisées"), max_length=3000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible"].queryset = get_user_model().objects.filter(
            project_memberships__project=project
        ).distinct()
        self.fields["evidence"].queryset = project.evidence_records.exclude(
            status=EvidenceRecord.Status.REJECTED
        )


class InventoryAnomalyDecisionForm(forms.Form):
    decision = forms.ChoiceField(label=_("Décision"), choices=(
        (InventoryAnomalyResolution.Status.APPROVED, "Valider la résolution"),
        (InventoryAnomalyResolution.Status.REJECTED, "Rejeter la résolution"),
    ))
    reason = forms.CharField(
        label=_("Motif de la décision"), max_length=3000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
