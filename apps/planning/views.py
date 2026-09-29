import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.projects.selectors import projects_for_user

from .forms import ProjectStageForm, StageProgressDeclarationForm, StageProgressVerificationForm, StageTechnicalReviewForm, StageSiteVisitForm, StageSiteVerificationForm, StageInspectionRiskRuleForm
from .models import ProjectStage, StageProgressDeclaration, StageSiteVisit
from .services import can_manage_stages, declare_stage_progress, verify_stage_progress, review_stage_progress, run_stage_digital_verification, record_stage_site_visit, complete_stage_site_verification, create_inspection_risk_rule, evaluate_stage_inspection_risk


@login_required
def stage_create(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if not can_manage_stages(actor=request.user, project=project):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied
    form = ProjectStageForm(request.POST, request.FILES)
    if form.is_valid():
        stage = form.save(commit=False)
        stage.organization = project.organization
        stage.project = project
        stage.created_by = request.user
        stage.full_clean()
        stage.save()
        messages.success(request, "L'étape a été créée.")
    else:
        messages.error(request, "L'étape n'a pas pu être créée. Vérifiez les informations.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_update(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if not can_manage_stages(actor=request.user, project=project):
        raise PermissionDenied
    stage = get_object_or_404(
        ProjectStage, pk=pk, project=project, organization=project.organization
    )
    if request.method != "POST":
        raise PermissionDenied
    form = ProjectStageForm(request.POST, request.FILES, instance=stage)
    if form.is_valid():
        updated_stage = form.save(commit=False)
        updated_stage.organization = stage.organization
        updated_stage.project = stage.project
        updated_stage.created_by = stage.created_by
        updated_stage.full_clean()
        updated_stage.save()
        messages.success(request, "L'étape a été mise à jour.")
    else:
        messages.error(request, "L'étape n'a pas pu être modifiée. Vérifiez les informations.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_progress_declare(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = StageProgressDeclarationForm(request.POST, stage=stage)
    if form.is_valid():
        declare_stage_progress(actor=request.user, stage=stage, **form.cleaned_data)
        messages.success(request, "La progression déclarée a été enregistrée sans être présentée comme vérifiée.")
    else:
        messages.error(request, "La déclaration de progression est invalide.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_progress_verify(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = StageProgressVerificationForm(request.POST, stage=stage)
    if form.is_valid():
        try:
            verify_stage_progress(actor=request.user, stage=stage, **form.cleaned_data)
            messages.success(request, "La progression vérifiée a été enregistrée.")
        except ValidationError as error:
            messages.error(request, error.messages[0])
    else:
        messages.error(request, "La vérification de progression est invalide.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_progress_review(request, project_pk, pk, declaration_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    declaration = get_object_or_404(StageProgressDeclaration, pk=declaration_pk, stage=stage)
    if request.method != "POST":
        raise PermissionDenied
    form = StageTechnicalReviewForm(request.POST)
    if form.is_valid():
        try:
            review_stage_progress(actor=request.user, declaration=declaration, **form.cleaned_data)
            messages.success(request, "La décision technique a été enregistrée.")
        except ValidationError as error:
            messages.error(request, error.messages[0])
    else:
        messages.error(request, "Le motif et les actions correctives requises doivent être renseignés.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_progress_digital_verify(request, project_pk, pk, declaration_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    declaration = get_object_or_404(StageProgressDeclaration, pk=declaration_pk, stage=stage)
    if request.method != "POST":
        raise PermissionDenied
    try:
        result = run_stage_digital_verification(actor=request.user, declaration=declaration)
        if result.result == result.Result.PASSED:
            messages.success(request, "Digital Verified : tous les contrôles numériques sont conformes.")
        else:
            messages.error(request, "Digital Verified a échoué. Consultez les contrôles du dossier.")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_site_visit_create(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = StageSiteVisitForm(request.POST)
    if form.is_valid():
        record_stage_site_visit(actor=request.user, stage=stage, **form.cleaned_data)
        messages.success(request, "La visite terrain a été enregistrée.")
    else:
        messages.error(request, "La date et la localisation de la visite sont obligatoires.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_site_verification_create(request, project_pk, pk, visit_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    visit = get_object_or_404(StageSiteVisit, pk=visit_pk, stage=stage)
    if request.method != "POST":
        raise PermissionDenied
    form = StageSiteVerificationForm(request.POST, stage=stage)
    technical = stage.latest_verified_progress
    if form.is_valid() and technical:
        try:
            complete_stage_site_verification(
                actor=request.user, visit=visit, technical_verification=technical,
                **form.cleaned_data,
            )
            messages.success(request, "PIVOT Site Verified a été enregistré.")
        except ValidationError as error:
            messages.error(request, error.messages[0])
    else:
        messages.error(request, "Une vérification technique signée, une checklist et une preuve sont obligatoires.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def inspection_risk_rule_create(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if not request.user.is_superuser or request.method != "POST":
        raise PermissionDenied
    form = StageInspectionRiskRuleForm(request.POST)
    if form.is_valid():
        create_inspection_risk_rule(actor=request.user, organization=project.organization, data=form.cleaned_data)
        messages.success(request, "Une nouvelle version de la règle de risque est active.")
    else:
        messages.error(request, "La règle de risque est invalide.")
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def stage_inspection_risk_evaluate(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(ProjectStage, pk=pk, project=project)
    if request.method != "POST" or not stage.latest_verified_progress:
        raise PermissionDenied
    try:
        assessment = evaluate_stage_inspection_risk(actor=request.user, technical_verification=stage.latest_verified_progress)
        messages.success(request, "Inspection imposée." if assessment.inspection_required else "Aucune inspection imposée par cette règle.")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect(f"{project.get_absolute_url()}?tab=stages")


@login_required
def calendar_view(request):
    projects = projects_for_user(request.user)
    stages = ProjectStage.objects.filter(project__in=projects).select_related("project")
    return render(request, "planning/calendar.html", {"projects": projects, "stages": stages})


@login_required
def calendar_events(request):
    projects = projects_for_user(request.user)
    project_id = request.GET.get("project")
    if project_id:
        project = get_object_or_404(projects, pk=project_id)
        projects = projects.filter(pk=project.pk)
    stages = ProjectStage.objects.filter(project__in=projects).select_related("project")
    events = [
        {
            "id": f"project-{project.pk}",
            "title": project.name,
            "start": project.project_date.isoformat(),
            "end": project.project_date.isoformat(),
            "status": project.status,
            "type": "project",
            "project": {"id": str(project.pk), "name": project.name},
            "url": project.get_absolute_url(),
        }
        for project in projects
    ]
    events.extend(
        [
            {
                "id": str(stage.pk),
                "title": stage.title,
                "start": stage.start_date.isoformat(),
                "end": stage.end_date.isoformat(),
                "status": stage.status,
                "type": "stage",
                "project": {"id": str(stage.project_id), "name": stage.project.name},
                "url": f"{stage.project.get_absolute_url()}?tab=stages",
            }
            for stage in stages
        ]
    )
    return JsonResponse({"events": events})


@login_required
def stages_export_csv(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="etapes-{project.pk}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        ["Titre", "Statut", "Date de début", "Date de fin", "Coût estimé XAF", "Coût réel XAF"]
    )
    for stage in project.stages.all():
        writer.writerow(
            [
                stage.title,
                stage.get_status_display(),
                stage.start_date.isoformat(),
                stage.end_date.isoformat(),
                stage.estimated_cost,
                stage.actual_cost,
            ]
        )
    return response
