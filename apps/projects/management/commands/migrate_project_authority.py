import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.collaboration.models import ProjectDocument, ProjectImage
from apps.finance.models import PaymentTransaction
from apps.projects.models import (
    Project,
    ProjectAuthorityMigrationReview,
    ProjectMembership,
    ProjectOwnership,
    ProjectOwnershipHistory,
    ProjectStatusHistory,
)


def preservation_snapshot():
    return {
        "projects": Project.objects.count(),
        "documents": ProjectDocument.objects.count(),
        "files": ProjectDocument.objects.exclude(file="").count(),
        "photos": ProjectImage.objects.count(),
        "transactions": PaymentTransaction.objects.count(),
        "status_history": ProjectStatusHistory.objects.count(),
        "ownership_history": ProjectOwnershipHistory.objects.count(),
    }


class Command(BaseCommand):
    help = "Migre et contrôle l'autorité des projets existants sans supprimer de données."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Appliquer les changements.")
        parser.add_argument("--actor", help="Nom d'utilisateur de l'opérateur qui audite la migration.")
        parser.add_argument("--output", help="Chemin facultatif du rapport JSON.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        actor = None
        if apply_changes:
            if not options.get("actor"):
                raise CommandError("--actor est obligatoire avec --apply.")
            actor = get_user_model().objects.filter(
                username=options["actor"], is_active=True
            ).first()
            if actor is None or not actor.is_superuser:
                raise CommandError("L'acteur doit être un super-administrateur actif.")
        else:
            actor = get_user_model().objects.filter(is_superuser=True, is_active=True).first()

        before = preservation_snapshot()
        decisions = []
        with transaction.atomic():
            for project in Project.objects.select_related("organization").order_by("pk"):
                candidates = list(
                    project.memberships.filter(
                        user__role="client", user__is_active=True
                    ).select_related("user").order_by("created_at", "user_id")
                )
                candidate_ids = [item.user_id for item in candidates]
                if len(candidates) == 1:
                    candidate = candidates[0]
                    project.memberships.filter(
                        project_role=ProjectMembership.Role.OWNER
                    ).exclude(pk=candidate.pk).update(
                        project_role=ProjectMembership.Role.CONTRACTOR
                    )
                    if candidate.project_role != ProjectMembership.Role.OWNER:
                        candidate.project_role = ProjectMembership.Role.OWNER
                        candidate.save(update_fields=("project_role",))
                    ownership, _ = ProjectOwnership.objects.update_or_create(
                        project=project,
                        defaults={
                            "organization": project.organization,
                            "owner": candidate.user,
                            "is_confirmed": True,
                            "confirmed_at": timezone.now(),
                            "confirmed_by": candidate.user,
                            "terms_version": "migration-2026-09-v1",
                            "terms_accepted": True,
                        },
                    )
                    ProjectAuthorityMigrationReview.objects.filter(
                        project=project, status=ProjectAuthorityMigrationReview.Status.OPEN
                    ).update(
                        status=ProjectAuthorityMigrationReview.Status.RESOLVED,
                        resolved_at=timezone.now(),
                        resolved_by=actor,
                        resolution_note="Un client unique a été identifié par la migration.",
                    )
                    if actor is not None and not AuditEvent.objects.filter(
                        action="project.authority_migrated",
                        target_type="project",
                        target_id=str(project.pk),
                    ).exists():
                        AuditEvent.objects.create(
                            organization=project.organization,
                            actor=actor,
                            action="project.authority_migrated",
                            target_type="project",
                            target_id=str(project.pk),
                            metadata={
                                "owner_id": candidate.user_id,
                                "rule": "single_active_client",
                                "terms_version": ownership.terms_version,
                            },
                        )
                    outcome = "owner_assigned"
                else:
                    reason = (
                        ProjectAuthorityMigrationReview.Reason.NO_CLIENT
                        if not candidates
                        else ProjectAuthorityMigrationReview.Reason.MULTIPLE_CLIENTS
                    )
                    ProjectAuthorityMigrationReview.objects.update_or_create(
                        project=project,
                        defaults={
                            "organization": project.organization,
                            "reason": reason,
                            "status": ProjectAuthorityMigrationReview.Status.OPEN,
                            "candidate_user_ids": candidate_ids,
                            "resolved_at": None,
                            "resolved_by": None,
                            "resolution_note": "",
                        },
                    )
                    ProjectOwnership.objects.filter(project=project).update(
                        is_confirmed=False,
                        terms_accepted=False,
                        confirmed_at=None,
                        confirmed_by=None,
                    )
                    outcome = "manual_review"
                decisions.append(
                    {
                        "project_id": str(project.pk),
                        "project": project.name,
                        "client_candidates": candidate_ids,
                        "outcome": outcome,
                    }
                )
            after = preservation_snapshot()
            if not apply_changes:
                transaction.set_rollback(True)

        preserved = all(before[key] == after[key] for key in before)
        report = {
            "mode": "applied" if apply_changes else "dry-run",
            "database_vendor": connections[Project.objects.db].vendor,
            "generated_at": timezone.now().isoformat(),
            "before": before,
            "after": after,
            "preserved": preserved,
            "summary": {
                "owner_assigned": sum(d["outcome"] == "owner_assigned" for d in decisions),
                "manual_review": sum(d["outcome"] == "manual_review" for d in decisions),
            },
            "projects": decisions,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if options.get("output"):
            output = Path(options["output"]).resolve()
            output.write_text(rendered, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Rapport écrit dans {output}"))
        self.stdout.write(rendered)
        if not preserved:
            raise CommandError("Le contrôle de préservation des données a échoué.")
