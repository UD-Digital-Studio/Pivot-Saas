import uuid

from django import forms

from .models import ExpenseOwnerDecision, ExpensePivotVerification, ExpenseRequest, ExpenseRequestAttachment, ExpenseTechnicalOpinion
from apps.collaboration.models import EvidenceRecord


class ExpenseRequestForm(forms.ModelForm):
    create_mode = forms.ChoiceField(widget=forms.HiddenInput, choices=(("draft", "Brouillon"), ("submitted", "Soumettre")), initial="draft")

    class Meta:
        model = ExpenseRequest
        fields = ("expense_type", "amount", "currency", "purpose", "beneficiary", "milestone", "due_date")
        labels = {"expense_type": "Type de dépense", "amount": "Montant", "currency": "Devise", "purpose": "Objet", "beneficiary": "Bénéficiaire", "milestone": "Jalon", "due_date": "Échéance"}
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}), "purpose": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["milestone"].queryset = project.stages.all()
        self.fields["currency"].initial = "XAF"
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm outline-none focus:border-pivot-600 focus:ring-4 focus:ring-pivot-600/10"


class ExpenseTransitionForm(forms.Form):
    target_status = forms.ChoiceField(choices=ExpenseRequest.Status.choices)
    reason = forms.CharField(max_length=500, required=False)
    expected_version = forms.IntegerField(min_value=1)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("target_status") == ExpenseRequest.Status.REJECTED and not cleaned.get("reason", "").strip():
            self.add_error("reason", "Un motif est obligatoire pour refuser.")
        return cleaned


class ExpenseAttachmentForm(forms.Form):
    document_type = forms.ChoiceField(label="Nature de la pièce", choices=ExpenseRequestAttachment.DocumentType.choices)
    evidence = forms.ModelChoiceField(label="Preuve existante", queryset=EvidenceRecord.objects.none())

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evidence"].queryset = project.evidence_records.exclude(status=EvidenceRecord.Status.REJECTED).select_related("author")
        for field in self.fields.values():
            field.widget.attrs["class"] = "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm"


class ExpenseAttachmentDecisionForm(forms.Form):
    reason = forms.CharField(label="Motif", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    replacement_evidence = forms.ModelChoiceField(label="Nouvelle preuve", queryset=EvidenceRecord.objects.none(), required=False)

    def __init__(self, *args, project, replacement_required=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["replacement_evidence"].queryset = project.evidence_records.exclude(status=EvidenceRecord.Status.REJECTED)
        self.fields["replacement_evidence"].required = replacement_required


class ExpenseTechnicalOpinionForm(forms.Form):
    decision = forms.ChoiceField(label="Avis technique", choices=ExpenseTechnicalOpinion.Decision.choices)
    reason = forms.CharField(
        label="Motif et observations", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs["class"] = "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm"


class ExpensePivotVerificationForm(forms.Form):
    decision = forms.ChoiceField(label="Décision PIVOT", choices=ExpensePivotVerification.Decision.choices)
    reason = forms.CharField(
        label="Motivation", max_length=1000, widget=forms.Textarea(attrs={"rows": 4})
    )
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    is_exceptional = forms.BooleanField(label="Intervention exceptionnelle", required=False)
    confirmation = forms.CharField(label="Confirmation explicite", max_length=100, required=False)

    def __init__(self, *args, allow_exceptional=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not allow_exceptional:
            self.fields.pop("is_exceptional")
            self.fields.pop("confirmation")
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs["class"] = "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm"


class ExpenseOwnerDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        widget=forms.HiddenInput,
        choices=ExpenseOwnerDecision.Decision.choices,
    )
    reason = forms.CharField(
        label="Motif", max_length=1000, required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == ExpenseOwnerDecision.Decision.REJECTED and not cleaned.get("reason", "").strip():
            self.add_error("reason", "Le motif du refus est obligatoire.")
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].widget.attrs["class"] = "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm"


class PaymentForm(forms.Form):
    field_class = (
        "w-full rounded-lg border border-slate-300 bg-white px-4 py-3 outline-none "
        "transition focus:border-pivot-600 focus:ring-4 focus:ring-pivot-600/10"
    )
    amount = forms.DecimalField(
        label="Montant XAF",
        min_value=1,
        decimal_places=0,
        widget=forms.NumberInput(attrs={"placeholder": "Ex. 250000", "inputmode": "numeric"}),
    )
    operator = forms.ChoiceField(
        label="Opérateur", choices=(("mtn", "MTN Mobile Money"), ("orange", "Orange Money"))
    )
    phone = forms.RegexField(
        label="Téléphone payeur",
        regex=r"^\+?[0-9]{9,15}$",
        widget=forms.TextInput(
            attrs={"placeholder": "Ex. 670000000", "inputmode": "tel", "autocomplete": "tel"}
        ),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("amount", "operator", "phone"):
            self.fields[name].widget.attrs["class"] = self.field_class
        if not self.is_bound:
            self.fields["idempotency_key"].initial = uuid.uuid4()


class ExpensePaymentForm(forms.Form):
    operator = forms.ChoiceField(
        label="Opérateur", choices=(("mtn", "MTN Mobile Money"), ("orange", "Orange Money"))
    )
    phone = forms.RegexField(
        label="Téléphone du payeur", regex=r"^\+?[0-9]{9,15}$",
        widget=forms.TextInput(attrs={"placeholder": "Ex. 670000000", "inputmode": "tel", "autocomplete": "tel"}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("operator", "phone"):
            self.fields[name].widget.attrs["class"] = "w-full rounded-xl border border-slate-300 bg-white px-3 py-3 text-sm"
        if not self.is_bound:
            self.fields["idempotency_key"].initial = uuid.uuid4()


class WithdrawalForm(forms.Form):
    field_class = (
        "w-full rounded-lg border border-slate-300 bg-white px-4 py-3 outline-none "
        "transition focus:border-pivot-600 focus:ring-4 focus:ring-pivot-600/10"
    )
    amount = forms.DecimalField(
        label="Montant XAF",
        min_value=1,
        decimal_places=0,
        widget=forms.NumberInput(attrs={"placeholder": "Ex. 150000", "inputmode": "numeric"}),
    )
    reason = forms.CharField(
        label="Motif",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Précisez l’utilisation prévue des fonds"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = self.field_class
