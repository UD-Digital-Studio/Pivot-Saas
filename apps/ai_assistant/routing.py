import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class IntentDefinition:
    name: str
    concepts: tuple[str, ...]


INTENT_REGISTRY = (
    IntentDefinition(
        "subscription",
        (
            "abonnement", "forfait", "souscription", "facturation", "echeance",
            "subscription", "plan", "billing", "renewal", "trial", "essai",
        ),
    ),
    IntentDefinition(
        "users",
        (
            "utilisateur",
            "usager",
            "membre",
            "equipe",
            "collaborateur",
            "personnel",
            "employe",
            "personne",
            "user",
            "member",
            "team",
            "staff",
            "employee",
            "role",
        ),
    ),
    IntentDefinition(
        "platform",
        (
            "organisation",
            "organization",
            "entreprise",
            "societe",
            "structure",
            "company",
            "business",
        ),
    ),
    IntentDefinition(
        "finance",
        (
            "finance",
            "budget",
            "paiement",
            "payer",
            "paye",
            "regler",
            "reglement",
            "versement",
            "retrait",
            "solde",
            "depense",
            "depense total",
            "payment",
            "withdrawal",
            "balance",
            "cost",
        ),
    ),
    IntentDefinition(
        "stock",
        (
            "stock",
            "inventaire",
            "article",
            "materiau",
            "materiel",
            "fourniture",
            "inventory",
            "material",
            "supply",
        ),
    ),
    IntentDefinition(
        "stages",
        (
            "etape",
            "phase",
            "jalon",
            "progression",
            "avancement",
            "retard",
            "stage",
            "milestone",
            "progress",
            "overdue",
        ),
    ),
    IntentDefinition(
        "documents",
        (
            "document",
            "fichier",
            "piece",
            "jointe",
            "plan pdf",
            "file",
            "attachment",
            "pdf",
        ),
    ),
    IntentDefinition(
        "photos",
        ("photo", "image", "galerie", "illustration", "picture", "gallery"),
    ),
    IntentDefinition(
        "comments",
        (
            "commentaire",
            "discussion",
            "conversation",
            "message",
            "avis",
            "comment",
            "discussion",
        ),
    ),
    IntentDefinition(
        "report",
        ("rapport", "bilan", "synthese", "resume", "report", "summary", "overview"),
    ),
    IntentDefinition(
        "projects",
        ("projet", "chantier", "ouvrage", "construction", "project", "site"),
    ),
)


def normalize_question(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _matches_concept(words, normalized, concept):
    normalized_concept = normalize_question(concept)
    if " " in normalized_concept:
        return normalized_concept in normalized
    for word in words:
        if word == normalized_concept:
            return True
        if len(word) >= 5 and len(normalized_concept) >= 5:
            if SequenceMatcher(None, word, normalized_concept).ratio() >= 0.80:
                return True
    return False


def detect_intents(question):
    normalized = normalize_question(question)
    words = normalized.split()
    matches = tuple(
        definition.name
        for definition in INTENT_REGISTRY
        if any(_matches_concept(words, normalized, concept) for concept in definition.concepts)
    )
    if "users" in matches and "platform" in matches:
        matches = tuple(item for item in matches if item != "platform")
    if "projects" in matches and any(item != "projects" for item in matches):
        matches = tuple(item for item in matches if item != "projects")
    return matches
