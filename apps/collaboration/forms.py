from django.utils.translation import gettext_lazy as _
import uuid

from django import forms

from .models import EvidenceRecord, ProjectComment, ProjectDocument, ProjectImage


class EvidenceCaptureForm(forms.Form):
    """Mobile evidence capture with server-side signature validation."""

    PHOTO_LIMIT = 10 * 1024 * 1024
    VIDEO_LIMIT = 25 * 1024 * 1024
    DOCUMENT_LIMIT = 10 * 1024 * 1024
    PHOTO_TYPES = {".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG\r\n\x1a\n",), ".webp": (b"RIFF",)}
    VIDEO_TYPES = {".mp4": (b"ftyp",), ".mov": (b"ftyp",), ".webm": (b"\x1aE\xdf\xa3",)}
    DOCUMENT_TYPES = {".pdf": (b"%PDF",), ".docx": (b"PK\x03\x04",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG\r\n\x1a\n",)}

    evidence_type = forms.ChoiceField(label=_("Type"), choices=EvidenceRecord.Type.choices)
    title = forms.CharField(label=_("Titre"), max_length=200)
    uploaded_file = forms.FileField(label=_("Fichier"), widget=forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp,.mp4,.mov,.webm,.pdf,.docx"}))
    stage = forms.ModelChoiceField(label=_("Étape"), queryset=None, required=False)
    description = forms.CharField(label=_("Description"), max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    location_consent = forms.BooleanField(label=_("Joindre ma position à cette preuve"), required=False)
    location_status = forms.ChoiceField(choices=EvidenceRecord.LocationStatus.choices, initial=EvidenceRecord.LocationStatus.NOT_REQUESTED, required=False, widget=forms.HiddenInput)
    latitude = forms.DecimalField(required=False, max_digits=9, decimal_places=6, widget=forms.HiddenInput)
    longitude = forms.DecimalField(required=False, max_digits=9, decimal_places=6, widget=forms.HiddenInput)
    location_accuracy_m = forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput)
    submission_id = forms.UUIDField(required=False, initial=uuid.uuid4, widget=forms.HiddenInput)

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = project.stages.all()
        self.fields["title"].widget.attrs["placeholder"] = "Ex. Livraison de ciment"

    def clean(self):
        cleaned = super().clean()
        uploaded = cleaned.get("uploaded_file")
        evidence_type = cleaned.get("evidence_type")
        if not uploaded or not evidence_type:
            return self._clean_location(cleaned)
        from pathlib import Path
        suffix = Path(uploaded.name).suffix.lower()
        if evidence_type == EvidenceRecord.Type.PHOTO:
            allowed, limit, label = self.PHOTO_TYPES, self.PHOTO_LIMIT, "photo"
        elif evidence_type == EvidenceRecord.Type.VIDEO:
            allowed, limit, label = self.VIDEO_TYPES, self.VIDEO_LIMIT, "vidéo"
        else:
            allowed, limit, label = self.DOCUMENT_TYPES, self.DOCUMENT_LIMIT, "document"
        if suffix not in allowed:
            self.add_error("uploaded_file", f"Format de {label} non autorisé.")
            return self._clean_location(cleaned)
        if uploaded.size > limit:
            self.add_error("uploaded_file", f"Le fichier dépasse la limite de {limit // (1024 * 1024)} Mo.")
            return self._clean_location(cleaned)
        header = uploaded.read(16)
        uploaded.seek(0)
        signatures = allowed[suffix]
        valid = any(signature in header if signature == b"ftyp" else header.startswith(signature) for signature in signatures)
        if suffix == ".webp":
            valid = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        if not valid:
            self.add_error("uploaded_file", "Le contenu du fichier ne correspond pas à son format.")
        return self._clean_location(cleaned)

    def _clean_location(self, cleaned):
        consent = bool(cleaned.get("location_consent"))
        status = cleaned.get("location_status")
        latitude, longitude = cleaned.get("latitude"), cleaned.get("longitude")
        if not consent:
            cleaned.update(location_status=EvidenceRecord.LocationStatus.NOT_REQUESTED, latitude=None, longitude=None, location_accuracy_m=None)
        elif status == EvidenceRecord.LocationStatus.GRANTED:
            if latitude is None or longitude is None:
                self.add_error("location_consent", "La position n’a pas pu être déterminée.")
            elif not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                self.add_error("location_consent", "Les coordonnées reçues sont invalides.")
        elif status in {EvidenceRecord.LocationStatus.DENIED, EvidenceRecord.LocationStatus.UNAVAILABLE}:
            cleaned.update(latitude=None, longitude=None, location_accuracy_m=None)
        else:
            cleaned.update(location_status=EvidenceRecord.LocationStatus.UNAVAILABLE, latitude=None, longitude=None, location_accuracy_m=None)
        return cleaned


class EvidenceCorrectionForm(EvidenceCaptureForm):
    correction_reason = forms.CharField(label=_("Motif de la correction"), max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, original, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evidence_type"].initial = original.evidence_type
        self.fields["evidence_type"].widget = forms.HiddenInput()
        self.fields["title"].initial = original.title
        self.fields["description"].initial = original.description
        self.fields["stage"].initial = original.stage_id


class EvidenceDecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=(("verified", "Vérifier"), ("approved", "Approuver"), ("rejected", "Rejeter")))
    reason = forms.CharField(max_length=500, required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "rejected" and not cleaned.get("reason", "").strip():
            self.add_error("reason", "Un motif est obligatoire pour rejeter.")
        return cleaned


class DocumentForm(forms.ModelForm):
    class Meta:
        model = ProjectDocument
        fields = ("title", "file")

    def clean_file(self):
        file = self.cleaned_data["file"]
        if (
            not file.name.lower().endswith(".pdf")
            or getattr(file, "content_type", "") != "application/pdf"
        ):
            raise forms.ValidationError(_("Seuls les fichiers PDF sont autorisés."))
        if file.size > 10 * 1024 * 1024:
            raise forms.ValidationError(_("Le PDF ne doit pas dépasser 10 Mo."))
        return file


class DocumentReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=(("verified", "Vérifier"), ("rejected", "Rejeter")))
    reason = forms.CharField(label=_("Motif"), max_length=500, required=False)

    def clean(self):
        data = super().clean()
        if data.get("decision") == "rejected" and not data.get("reason", "").strip():
            self.add_error("reason", "Un motif est obligatoire pour rejeter.")
        return data


class ImageForm(forms.ModelForm):
    class Meta:
        model = ProjectImage
        fields = ("image", "caption")

    def clean_image(self):
        image = self.cleaned_data["image"]
        if image.size > 5 * 1024 * 1024:
            raise forms.ValidationError(_("L'image ne doit pas dépasser 5 Mo."))
        return image


class CommentForm(forms.ModelForm):
    class Meta:
        model = ProjectComment
        fields = ("content",)
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Écrivez votre commentaire…",
                    "class": "block w-full resize-y rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-pivot-600 focus:ring-4 focus:ring-pivot-600/10 dark:border-slate-600 dark:bg-slate-900 dark:text-white",
                }
            )
        }
