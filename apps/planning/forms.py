from django import forms
from django.db import models

from .models import ProjectStage, StageProgressDeclaration, StageProgressVerification, StageTechnicalReview, StageSiteVisit, StageSiteVerification, StageInspectionRiskRule


class ProjectStageForm(forms.ModelForm):
    class Meta:
        model = ProjectStage
        fields = (
            "title",
            "stage_type",
            "description",
            "start_date",
            "end_date",
            "estimated_cost",
            "actual_cost",
            "status",
            "image",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "estimated_cost": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "actual_cost": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "image": forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage_type"].required = False
        self.fields["stage_type"].initial = ProjectStage.Type.STANDARD
        self.fields["start_date"].input_formats = ["%Y-%m-%d"]
        self.fields["end_date"].input_formats = ["%Y-%m-%d"]

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["stage_type"] = cleaned_data.get("stage_type") or ProjectStage.Type.STANDARD
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La date de fin doit être postérieure au début.")
        return cleaned_data


class StageProgressForm(forms.ModelForm):
    class Meta:
        fields = ("percent", "evidence", "note")
        labels = {
            "percent": "Progression en pourcentage",
            "evidence": "Preuve associée",
            "note": "Note",
        }
        widgets = {
            "percent": forms.NumberInput(attrs={"min": 0, "max": 100, "step": 1, "placeholder": "Ex. : 70"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, stage, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.stage = stage
        self.instance.organization = stage.organization
        if "evidence" in self.fields:
            self.fields["evidence"].queryset = stage.project.evidence_records.filter(
                models.Q(stage=stage) | models.Q(stage__isnull=True)
            )


class StageProgressDeclarationForm(StageProgressForm):
    class Meta(StageProgressForm.Meta):
        model = StageProgressDeclaration


class StageProgressVerificationForm(StageProgressForm):
    quantities = forms.JSONField(
        initial=list, required=False, widget=forms.Textarea(attrs={"rows": 4}),
        help_text='Liste JSON : [{"label":"Béton coulé","quantity":12,"unit":"m³"}]',
    )
    reservations = forms.JSONField(
        initial=list, required=False, widget=forms.Textarea(attrs={"rows": 4}),
        help_text='Liste JSON : [{"description":"Reprise nécessaire","status":"open"}]',
    )

    class Meta(StageProgressForm.Meta):
        model = StageProgressVerification
        fields = ("percent", "quantities", "reservations", "note")


class StageTechnicalReviewForm(forms.ModelForm):
    class Meta:
        model = StageTechnicalReview
        fields = ("decision", "reason", "corrective_actions")
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 3}),
            "corrective_actions": forms.Textarea(attrs={"rows": 4}),
        }


class StageSiteVisitForm(forms.ModelForm):
    class Meta:
        model = StageSiteVisit
        fields = ("visited_at", "location_label", "latitude", "longitude", "notes")
        labels = {
            "visited_at": "Date et heure de la visite",
            "location_label": "Lieu de la visite",
            "latitude": "Latitude",
            "longitude": "Longitude",
            "notes": "Compte rendu",
        }
        widgets = {
            "visited_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class StageSiteVerificationForm(forms.ModelForm):
    checklist = forms.JSONField(widget=forms.Textarea(attrs={"rows": 5}), help_text='[{"item":"Fondations","result":"ok","comment":"Conforme"}]')
    reservations = forms.JSONField(required=False, initial=list, widget=forms.Textarea(attrs={"rows": 4}), help_text='[{"description":"Correction","status":"open"}]')

    class Meta:
        model = StageSiteVerification
        fields = ("result", "checklist", "evidence", "reservations")
        labels = {"result": "Résultat final", "evidence": "Preuves examinées"}
        widgets = {"evidence": forms.CheckboxSelectMultiple}

    def __init__(self, *args, stage, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evidence"].queryset = stage.project.evidence_records.filter(
            models.Q(stage=stage) | models.Q(stage__isnull=True)
        )


class StageInspectionRiskRuleForm(forms.ModelForm):
    stage_types = forms.MultipleChoiceField(
        choices=ProjectStage.Type.choices, required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = StageInspectionRiskRule
        fields = ("stage_types",)
