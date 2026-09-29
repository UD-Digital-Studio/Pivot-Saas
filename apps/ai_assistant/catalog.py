from dataclasses import dataclass, field

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured

SENSITIVE_FIELD_NAMES = {
    "password",
    "token_hash",
    "payer_phone",
    "provider_reference",
    "idempotency_key",
    "raw_response_redacted",
    "file",
    "image",
}


@dataclass(frozen=True)
class CatalogField:
    name: str
    fr: str
    en: str


@dataclass(frozen=True)
class CatalogEntity:
    key: str
    model_label: str
    fr: str
    en: str
    description_fr: str
    description_en: str
    fields: tuple[CatalogField, ...]
    relations: dict[str, str] = field(default_factory=dict)
    vocabulary: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)
    computed: tuple[CatalogField, ...] = ()

    @property
    def model(self):
        return apps.get_model(self.model_label)


def f(name, fr, en):
    return CatalogField(name=name, fr=fr, en=en)


CATALOG = (
    CatalogEntity(
        "organization",
        "organizations.Organization",
        "Organisation",
        "Organization",
        "Espace de travail isolé regroupant les utilisateurs et projets.",
        "Isolated workspace grouping users and projects.",
        (
            f("name", "nom", "name"),
            f("status", "statut", "status"),
            f("created_at", "date de création", "creation date"),
        ),
        vocabulary={
            "status": {
                "active": ("active", "active"),
                "suspended": ("suspendue", "suspended"),
                "archived": ("archivée", "archived"),
            }
        },
    ),
    CatalogEntity(
        "user",
        "accounts.User",
        "Utilisateur",
        "User",
        "Compte PIVOT rattaché à une organisation et à un rôle.",
        "PIVOT account attached to an organization and a role.",
        (
            f("username", "nom d’utilisateur", "username"),
            f("first_name", "prénom", "first name"),
            f("last_name", "nom", "last name"),
            f("role", "rôle", "role"),
            f("is_active", "compte actif", "active account"),
            f("date_joined", "date d’inscription", "join date"),
        ),
        relations={"organization": "organization"},
        vocabulary={
            "role": {
                "engineer": ("ingénieur", "engineer"),
                "client": ("client", "client"),
                "contractor": ("entrepreneur", "contractor"),
                "site_manager": ("responsable de chantier", "site manager"),
                "admin": ("administrateur", "administrator"),
            }
        },
    ),
    CatalogEntity(
        "project",
        "projects.Project",
        "Projet",
        "Project",
        "Chantier suivi dans une organisation avec un ingénieur responsable.",
        "Construction project tracked in an organization with a responsible engineer.",
        (
            f("name", "nom", "name"),
            f("description", "description", "description"),
            f("location", "localisation", "location"),
            f("project_date", "date du projet", "project date"),
            f("status", "statut", "status"),
            f("budget_amount", "budget en XAF", "budget in XAF"),
            f("created_at", "date de création", "creation date"),
            f("updated_at", "dernière modification", "last update"),
        ),
        relations={"organization": "organization", "engineer": "user"},
        vocabulary={
            "status": {
                "pending": ("en attente", "pending"),
                "ongoing": ("en cours", "ongoing"),
                "complete": ("terminé", "complete"),
            }
        },
        computed=(
            f(
                "progress_percent",
                "progression calculée depuis les étapes",
                "progress computed from stages",
            ),
        ),
    ),
    CatalogEntity(
        "project_membership",
        "projects.ProjectMembership",
        "Affectation projet",
        "Project membership",
        "Rôle contextuel d’un utilisateur dans un projet.",
        "Contextual role of a user within a project.",
        (
            f("project_role", "rôle dans le projet", "role in project"),
            f("created_at", "date d’affectation", "assignment date"),
        ),
        relations={"organization": "organization", "project": "project", "user": "user"},
        vocabulary={
            "project_role": {
                "owner": ("propriétaire du chantier", "project owner"),
                "contractor": ("entrepreneur", "contractor"),
                "site_manager": ("responsable de chantier", "site manager"),
                "engineer": ("ingénieur", "engineer"),
                "pivot_reviewer": ("vérificateur PIVOT", "PIVOT reviewer"),
            }
        },
    ),
    CatalogEntity(
        "stage",
        "planning.ProjectStage",
        "Étape",
        "Stage",
        "Étape planifiée d’un chantier avec dates, coûts et progression.",
        "Planned construction stage with dates, costs and progress.",
        (
            f("title", "titre", "title"),
            f("description", "description", "description"),
            f("start_date", "date de début", "start date"),
            f("end_date", "date de fin", "end date"),
            f("estimated_cost", "coût estimé", "estimated cost"),
            f("actual_cost", "coût réel", "actual cost"),
            f("status", "statut", "status"),
        ),
        relations={"organization": "organization", "project": "project", "created_by": "user"},
        vocabulary={
            "status": {
                "pending": ("en attente", "pending"),
                "active": ("active", "active"),
                "complete": ("terminée", "complete"),
            }
        },
        computed=(
            f("progress_percent", "pourcentage de progression", "progress percentage"),
            f("is_overdue", "étape en retard", "overdue stage"),
        ),
    ),
    CatalogEntity(
        "stock_item",
        "inventory.StockItem",
        "Article de stock",
        "Stock item",
        "Matériau ou article suivi dans le stock d’un projet.",
        "Material or item tracked in a project's inventory.",
        (
            f("name", "nom", "name"),
            f("unit", "unité", "unit"),
            f("unit_price", "prix unitaire", "unit price"),
            f("quantity", "quantité", "quantity"),
            f("alert_threshold", "seuil d’alerte", "alert threshold"),
            f("status", "statut de validation", "validation status"),
            f("updated_at", "dernière modification", "last update"),
        ),
        relations={
            "organization": "organization",
            "project": "project",
            "created_by": "user",
            "verified_by": "user",
        },
        vocabulary={
            "status": {
                "pending": ("en attente", "pending"),
                "verified": ("vérifié", "verified"),
                "approved": ("approuvé", "approved"),
            }
        },
        computed=(
            f("total_price", "valeur totale", "total value"),
            f("is_low_stock", "stock faible", "low stock"),
        ),
    ),
    CatalogEntity(
        "stock_movement",
        "inventory.StockMovement",
        "Mouvement de stock",
        "Stock movement",
        "Entrée ou sortie traçable modifiant la quantité d’un article.",
        "Traceable incoming or outgoing movement changing an item's quantity.",
        (
            f("variation", "variation de quantité", "quantity variation"),
            f("resulting_quantity", "quantité résultante", "resulting quantity"),
            f("reason", "motif", "reason"),
            f("created_at", "date", "date"),
        ),
        relations={
            "organization": "organization",
            "project": "project",
            "item": "stock_item",
            "actor": "user",
        },
    ),
    CatalogEntity(
        "document",
        "collaboration.ProjectDocument",
        "Document",
        "Document",
        "Document de chantier soumis à un circuit d’approbation.",
        "Project document submitted to an approval workflow.",
        (
            f("title", "titre", "title"),
            f("status", "statut", "status"),
            f("review_reason", "motif de décision", "review reason"),
            f("uploaded_at", "date de dépôt", "upload date"),
            f("reviewed_at", "date de décision", "review date"),
        ),
        relations={
            "organization": "organization",
            "project": "project",
            "uploaded_by": "user",
            "reviewed_by": "user",
        },
        vocabulary={
            "status": {
                "pending": ("en attente", "pending"),
                "verified": ("vérifié", "verified"),
                "approved": ("approuvé", "approved"),
                "rejected": ("rejeté", "rejected"),
            }
        },
    ),
    CatalogEntity(
        "photo",
        "collaboration.ProjectImage",
        "Photo",
        "Photo",
        "Photo partagée dans la galerie d’un chantier.",
        "Photo shared in a project's gallery.",
        (
            f("caption", "légende", "caption"),
            f("is_cover", "photo de couverture", "cover photo"),
            f("created_at", "date d’ajout", "upload date"),
        ),
        relations={"organization": "organization", "project": "project", "uploaded_by": "user"},
    ),
    CatalogEntity(
        "comment",
        "collaboration.ProjectComment",
        "Commentaire",
        "Comment",
        "Message de collaboration rattaché à un projet.",
        "Collaboration message attached to a project.",
        (
            f("content", "contenu", "content"),
            f("is_deleted", "supprimé", "deleted"),
            f("created_at", "date de publication", "publication date"),
            f("updated_at", "date de modification", "update date"),
        ),
        relations={"organization": "organization", "project": "project", "author": "user"},
    ),
    CatalogEntity(
        "payment",
        "finance.PaymentTransaction",
        "Paiement",
        "Payment",
        "Transaction de paiement Mobile Money d’un utilisateur pour un projet.",
        "User Mobile Money payment transaction for a project.",
        (
            f("amount", "montant", "amount"),
            f("currency", "devise", "currency"),
            f("provider", "fournisseur", "provider"),
            f("operator", "opérateur", "operator"),
            f("status", "statut", "status"),
            f("requested_at", "date de demande", "request date"),
            f("completed_at", "date de fin", "completion date"),
        ),
        relations={"organization": "organization", "project": "project", "user": "user"},
        vocabulary={
            "status": {
                "pending": ("en attente", "pending"),
                "success": ("réussi", "successful"),
                "failed": ("échoué", "failed"),
                "cancelled": ("annulé", "cancelled"),
                "expired": ("expiré", "expired"),
            }
        },
    ),
    CatalogEntity(
        "withdrawal",
        "finance.Withdrawal",
        "Retrait",
        "Withdrawal",
        "Demande de retrait financier rattachée à un projet.",
        "Financial withdrawal request attached to a project.",
        (
            f("amount", "montant", "amount"),
            f("status", "statut", "status"),
            f("reason", "motif", "reason"),
            f("requested_at", "date de demande", "request date"),
            f("decided_at", "date de décision", "decision date"),
        ),
        relations={
            "organization": "organization",
            "project": "project",
            "requested_by": "user",
            "decided_by": "user",
        },
        vocabulary={
            "status": {
                "pending": ("en attente", "pending"),
                "accounted": ("comptabilisé", "accounted"),
                "rejected": ("rejeté", "rejected"),
            }
        },
    ),
)

CATALOG_BY_KEY = {entity.key: entity for entity in CATALOG}


def get_entity(key):
    try:
        return CATALOG_BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown catalog entity: {key}") from exc


def validate_catalog():
    errors = []
    for entity in CATALOG:
        try:
            model = entity.model
        except LookupError:
            errors.append(f"{entity.key}: model {entity.model_label} does not exist")
            continue
        exposed_names = {item.name for item in (*entity.fields, *entity.computed)}
        forbidden = exposed_names & SENSITIVE_FIELD_NAMES
        if forbidden:
            errors.append(f"{entity.key}: sensitive fields exposed: {sorted(forbidden)}")
        for item in entity.fields:
            try:
                model._meta.get_field(item.name)
            except FieldDoesNotExist:
                errors.append(f"{entity.key}: field {item.name} does not exist")
        for relation_name, target_key in entity.relations.items():
            try:
                relation = model._meta.get_field(relation_name)
            except FieldDoesNotExist:
                errors.append(f"{entity.key}: relation {relation_name} does not exist")
                continue
            if not relation.is_relation:
                errors.append(f"{entity.key}: {relation_name} is not a relation")
            if target_key not in CATALOG_BY_KEY:
                errors.append(f"{entity.key}: relation target {target_key} is unknown")
            elif relation.related_model is not CATALOG_BY_KEY[target_key].model:
                errors.append(
                    f"{entity.key}: relation {relation_name} does not target {target_key}"
                )
        for field_name, translations in entity.vocabulary.items():
            try:
                source_values = {
                    str(value) for value, _label in model._meta.get_field(field_name).choices
                }
            except FieldDoesNotExist:
                errors.append(f"{entity.key}: vocabulary field {field_name} does not exist")
                continue
            if source_values != set(translations):
                errors.append(f"{entity.key}: vocabulary {field_name} differs from model choices")
    return errors


def assert_catalog_valid():
    errors = validate_catalog()
    if errors:
        raise ImproperlyConfigured("Invalid AI business catalog: " + "; ".join(errors))


def catalog_prompt(language="fr"):
    assert_catalog_valid()
    use_english = str(language).lower().startswith("en")
    lines = [
        "Controlled PIVOT business catalog. Use only these entities, fields and values; "
        "never invent another model, field, relation or status. This is schema only, not user data."
    ]
    for entity in CATALOG:
        name = entity.en if use_english else entity.fr
        description = entity.description_en if use_english else entity.description_fr
        fields = [item.en if use_english else item.fr for item in entity.fields]
        computed = [item.en if use_english else item.fr for item in entity.computed]
        relations = [f"{source}->{target}" for source, target in entity.relations.items()]
        vocabularies = []
        for field_name, values in entity.vocabulary.items():
            rendered = ", ".join(
                f"{value}={labels[1] if use_english else labels[0]}"
                for value, labels in values.items()
            )
            vocabularies.append(f"{field_name}[{rendered}]")
        line = f"- {entity.key} ({name}): {description} Fields: {', '.join(fields)}."
        if computed:
            line += f" Computed: {', '.join(computed)}."
        if relations:
            line += f" Relations: {', '.join(relations)}."
        if vocabularies:
            line += f" Vocabulary: {'; '.join(vocabularies)}."
        lines.append(line)
    return "\n".join(lines)
