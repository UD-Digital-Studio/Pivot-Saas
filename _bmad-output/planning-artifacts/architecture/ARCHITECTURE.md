# PIVOT-SASS — Architecture applicative

Statut : architecture rebaselinée E16  
Version : 1.0  
Date : 2026-09-04  
Entrées : `../PRD_PIVOT.md`, `../ux/UX_DESIGN.md` ; la SPEC historique reste informative pour E1–E15.

## 1. Résumé de la solution

PIVOT-SASS sera un monolithe modulaire Django rendu côté serveur. Toute la logique métier et applicative sera écrite en Python/Django. L'interface reposera sur les templates Django, HTML, CSS et un minimum de JavaScript natif pour les interactions qui l'exigent.

La première étape utilisera SQLite3 afin de simplifier le démarrage local. Le modèle de données et les requêtes devront rester compatibles avec une migration ultérieure vers PostgreSQL avant une exploitation SaaS concurrente à grande échelle.

## 2. Décisions structurantes

| Domaine | Décision |
|---|---|
| Style | Monolithe Django modulaire |
| Langage serveur | Python |
| Framework | Django |
| Interface | Templates Django, HTML, CSS, JavaScript natif limité |
| API | Vues Django ; JSON uniquement pour calendrier et interactions ciblées |
| Base initiale | SQLite3 |
| Base cible possible | PostgreSQL sans changement du modèle fonctionnel |
| Multi-entreprise | Base partagée, lignes rattachées à une organisation |
| Authentification | Sessions Django et modèle utilisateur personnalisé |
| Autorisation | Rôle de compte pour le périmètre global ; rôle contextuel + organisation pour chaque projet |
| Paiement | Adaptateur MeSomb isolé du domaine |
| Fichiers | Abstraction via `FileField`/storage Django |
| Administration | Django Admin personnalisé |
| Traitement asynchrone initial | Aucun obligatoire ; services isolés pour évolution future |

## 3. Invariants d'architecture

Ces règles s'appliquent à tous les modules :

1. Toute donnée métier appartient directement ou indirectement à une organisation.
2. Une requête utilisateur ne peut jamais lire ou modifier une autre organisation.
3. L'organisation n'est jamais acceptée aveuglément depuis un champ de formulaire ; elle est dérivée du contexte authentifié.
4. Un identifiant d'objet seul ne constitue jamais une autorisation.
5. Les règles métier résident dans des services ou modèles du domaine, pas dans les templates ni dans JavaScript.
6. Les montants utilisent `DecimalField`, jamais `float` ni texte.
7. Les dates utilisent des champs date/heure Django, jamais du texte libre.
8. Paiements, retraits et mouvements de stock conservent une trace immuable.
9. Les opérations externes susceptibles d'être répétées utilisent une clé d'idempotence.
10. Les fichiers sont privés par défaut et servis après contrôle d'accès lorsqu'ils contiennent des données de chantier.
11. Les vues POST appliquent CSRF et refusent les méthodes inattendues.
12. SQLite3 ne doit pas entraîner l'utilisation de SQL propriétaire ou de conventions impossibles à migrer.

## 4. Organisation du dépôt

```text
PIVOT-SASS/
├── manage.py
├── pyproject.toml
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── core/
│   ├── organizations/
│   ├── accounts/
│   ├── projects/
│   ├── finance/
│   ├── planning/
│   ├── inventory/
│   ├── collaboration/
│   ├── reporting/
│   └── audit/
├── templates/
│   ├── base/
│   ├── components/
│   ├── registration/
│   └── errors/
├── static/
├── media/
├── tests/
└── docs/
```

Chaque application Django peut contenir :

```text
app/
├── admin.py
├── apps.py
├── forms.py
├── models.py
├── selectors.py
├── services.py
├── urls.py
├── views.py
├── migrations/
├── templates/app/
└── tests/
```

- `selectors.py` regroupe les lectures filtrées et optimisées.
- `services.py` porte les mutations et règles impliquant plusieurs modèles.
- Les modèles garantissent leurs invariants locaux avec contraintes et validation.
- Les vues orchestrent requête, autorisation, formulaire, service et réponse.

## 5. Responsabilités des modules

### `core`

Types partagés, utilitaires, mixins de vues, pages système, gestion des erreurs et composants transversaux sans dépendance métier circulaire.

### `organizations`

Organisation, adhésion, statut et contexte de l'organisation active. Ce module constitue la frontière d'isolation SaaS.

### `accounts`

Utilisateur personnalisé, profil, rôles, activation, invitation, connexion et réinitialisation du mot de passe.

### `projects`

Projet, affectations, statuts, tableaux de bord et contrôle central de l'accès à un projet.

### `finance`

Budget, transactions, paiements MeSomb, retraits, agrégats financiers et exports associés.

### `planning`

Étapes, calendrier, progression, coûts estimés/réels et association des images aux étapes.

### `inventory`

Articles, mouvements, ajustements, statuts, import et export du stock.

### `collaboration`

Documents, images, commentaires, approbations et accès contrôlé aux fichiers.

### `reporting`

Rapports PDF, projections de lecture et exports transversaux. Ce module lit les autres domaines mais ne modifie pas leurs données.

### `audit`

Journal des événements sensibles : administration, permissions, finance, stock, documents et suppressions.

## 6. Modèle de données principal

### Organisation et identités

- `Organization(id, name, slug, status, created_at, updated_at)`
- `User(id, organization_id, username, email, role, is_active, is_staff, ...)`
- `UserProfile(user_id, phone, location, bio, avatar)`
- `Invitation(id, organization_id, email, role, token_hash, expires_at, accepted_at)`

Choix initial : un utilisateur appartient à une seule organisation. Une évolution multi-organisation exigera ultérieurement un modèle d'adhésion séparé.

### Projets

- `Project(id, organization_id, engineer_id, name, description, location, project_date, status, budget_amount, cover_image, created_at, updated_at)`
- `ProjectMembership(id, organization_id, project_id, user_id, project_role, created_at)` avec `OWNER`, `CONTRACTOR`, `SITE_MANAGER`, `ENGINEER`, `PIVOT_REVIEWER`
- `ProjectOwnership(project_id, organization_id, owner_id, is_confirmed, confirmed_at, confirmed_by_id, terms_version, terms_accepted)`
- `ProjectOwnershipHistory(project_id, previous_owner_id, new_owner_id, actor_id, reason, created_at)`
- `ProjectAuthorityMigrationReview(project_id, reason, status, candidate_user_ids, resolution...)`

Contraintes :

- unicité de `(project, user)` ;
- ingénieur et membres dans la même organisation que le projet ;
- budget positif ou nul ;
- statut limité aux valeurs du domaine.

### Finance

- `PaymentTransaction(id, organization_id, project_id, user_id, amount, currency, provider, operator, payer_phone, provider_reference, idempotency_key, status, requested_at, completed_at, raw_response_redacted)`
- `Withdrawal(id, organization_id, project_id, amount, status, reason, requested_by, approved_by, requested_at, decided_at)`

Le total payé est la somme des transactions réussies. Le montant disponible est calculé à partir des transactions réussies moins les retraits comptabilisés. Ces agrégats ne sont pas saisis manuellement.

### Planning

- `ProjectStage(id, organization_id, project_id, title, description, start_date, end_date, estimated_cost, actual_cost, status, created_by, updated_at)`

### Stock

- `StockItem(id, organization_id, project_id, name, unit, unit_price, quantity, status, created_by, verified_by, verified_at)`
- `StockMovement(id, organization_id, project_id, item_id, delta, resulting_quantity, reason, created_by, created_at)`

La quantité est modifiée exclusivement par un service qui crée simultanément le mouvement correspondant.

### Collaboration

- `ProjectDocument(id, organization_id, project_id, title, file, status, uploaded_by, reviewed_by, review_reason, uploaded_at, reviewed_at)`
- `ProjectImage(id, organization_id, project_id, stage_id, image, caption, is_cover, uploaded_by, created_at)`
- `Comment(id, organization_id, project_id, author_id, body, created_at, updated_at, deleted_at)`

### Audit

- `AuditEvent(id, organization_id, actor_id, action, target_type, target_id, metadata_redacted, ip_address, created_at)`

## 7. Isolation multi-entreprise

### Stratégie initiale

Toutes les tables métier portent `organization_id`. L'organisation active est déterminée depuis l'utilisateur connecté. Les sélecteurs commencent toujours par le filtre d'organisation, puis appliquent les règles de rôle et de projet.

Exemple conceptuel :

```python
Project.objects.filter(
    organization=request.user.organization,
)
```

Ce filtre seul ne suffit pas pour les clients et responsables : leurs projets sont ensuite limités aux affectations actives.

### Défense en profondeur

- Managers/querysets dédiés pour les lectures contextualisées.
- Mixins ou décorateurs centralisés pour les vues de projet.
- Services recevant explicitement l'acteur et la ressource déjà contextualisée.
- Formulaires dont les querysets de relations sont limités à l'organisation.
- Tests systématiques d'accès croisé entre deux organisations.
- Django Admin filtré selon les privilèges ; seuls les superadministrateurs peuvent traverser les organisations.

## 8. Autorisation

L'autorisation combine trois dimensions :

1. appartenance à l'organisation ;
2. rôle global de l'utilisateur ;
3. propriété ou affectation au projet.

Les permissions métier sont exposées par des fonctions nommées, par exemple :

- `can_view_project(actor, project)` ;
- `can_manage_project(actor, project)` ;
- `can_manage_stage(actor, project)` ;
- `can_adjust_stock(actor, project)` ;
- `can_approve_document(actor, project)` ;
- `can_initiate_payment(actor, project)`.

Les templates utilisent ces décisions pour l'affichage, mais la vue ou le service les vérifie à nouveau.

## 9. Paiement MeSomb

Le domaine dépend d'une interface interne, pas directement du SDK :

```python
class PaymentGateway:
    def initiate(self, command): ...
    def query(self, provider_reference): ...
```

Un adaptateur `MeSombGateway` traduit les commandes et réponses. Un faux adaptateur permet les tests sans réseau.

Flux :

1. valider acteur, projet, montant, opérateur et numéro ;
2. créer une transaction `PENDING` avec clé d'idempotence unique ;
3. appeler MeSomb ;
4. enregistrer la référence et le statut retourné ;
5. rapprocher ultérieurement les statuts non définitifs ;
6. ne comptabiliser que le passage validé vers `SUCCEEDED`.

Les secrets proviennent exclusivement des variables d'environnement. Les réponses brutes sont expurgées avant persistance ou journalisation.

## 10. SQLite3 aujourd'hui, PostgreSQL ensuite

### Usage autorisé de SQLite3

- développement local ;
- démonstration ;
- tests simples ;
- première validation fonctionnelle avec faible concurrence.

### Limites acceptées temporairement

- concurrence d'écriture limitée ;
- verrouillage moins adapté aux paiements et ajustements simultanés ;
- garanties différentes pour certaines opérations transactionnelles ;
- absence de mécanismes avancés d'isolation multi-tenant au niveau base.

### Règles de portabilité

- utiliser l'ORM Django et les migrations ;
- éviter le SQL brut spécifique à SQLite ;
- ne pas utiliser de champs ou fonctions uniquement SQLite ;
- encapsuler les opérations critiques dans `transaction.atomic()` ;
- appliquer contraintes `UniqueConstraint` et `CheckConstraint` portables ;
- exécuter la suite de tests sur PostgreSQL avant toute mise en production multi-utilisateur ;
- prévoir une migration de données répétable et vérifiée.

SQLite3 est donc une décision de démarrage, pas la base recommandée pour la production SaaS finale.

## 11. Interface et échanges HTTP

- Pages principalement rendues par vues Django classiques.
- Formulaires POST avec jeton CSRF et pattern POST/Redirect/GET.
- JSON réservé aux événements calendrier, recherches ciblées et mises à jour partielles justifiées.
- Les endpoints JSON appliquent les mêmes formulaires, services et permissions que les pages.
- Téléchargement de fichier via une vue contrôlée ou une URL signée lorsque le stockage le permet.
- Pagination côté serveur pour projets, transactions, retraits, mouvements et audit.

## 12. Fichiers et médias

En développement, les fichiers utilisent un répertoire local exclu du versionnement. Le code dépend uniquement de l'API de stockage Django afin de permettre un stockage objet en production.

À chaque dépôt :

- limite de taille ;
- liste blanche de types ;
- nom de stockage généré ;
- contrôle d'accès au téléchargement ;
- métadonnées rattachées à l'organisation et au projet.

## 13. Rapports et exports

Les rapports utilisent des projections de lecture dédiées pour éviter que les templates PDF n'effectuent des requêtes métier. Les exports réutilisent les sélecteurs autorisés.

La génération synchrone est acceptable au démarrage pour de petits volumes. L'interface de service doit permettre de déplacer plus tard les rapports lourds vers une file de tâches sans changer les vues métier.

## 14. Configuration

- `base.py` : applications, middleware, templates, sécurité commune.
- `development.py` : SQLite3, e-mail console, debug local.
- `production.py` : variables obligatoires, HTTPS, cookies sécurisés, hôtes explicites, stockage et base configurables.
- Un fichier `.env.example` documente uniquement les noms des variables, jamais des secrets.
- Le démarrage de production échoue clairement si une configuration critique manque.

## 15. Journalisation et audit

- Journaux techniques structurés sans mot de passe, jeton, clé ou réponse de paiement sensible.
- Identifiant de corrélation par requête lorsque possible.
- Audit métier distinct pour les actions qui changent droits, argent, stock, validation ou suppression.
- Les erreurs utilisateur sont compréhensibles ; les détails internes restent dans les journaux.

## 16. Stratégie de tests

### Tests unitaires

- calculs financiers ;
- transitions de statuts ;
- permissions ;
- règles de stock ;
- validation de formulaires ;
- adaptateur de paiement simulé.

### Tests d'intégration Django

- vues par rôle ;
- accès croisé entre organisations ;
- soumissions CSRF ;
- transactions atomiques ;
- fichiers et exports ;
- administration filtrée.

### Parcours fonctionnels prioritaires

1. inscription et activation ingénieur ;
2. création d'organisation, utilisateurs et projet ;
3. affectation puis accès client/responsable ;
4. paiement réussi, échoué et répété ;
5. ajustement concurrent ou répété du stock ;
6. validation d'un document ;
7. rapport et export sans fuite inter-organisation.

## 17. Ordre d'implémentation recommandé

1. socle Django, configuration, qualité et tests ;
2. organisations, utilisateur personnalisé et authentification ;
3. projets, affectations et autorisations ;
4. étapes et calendrier ;
5. stock et mouvements ;
6. documents, images et commentaires ;
7. finance, faux adaptateur puis MeSomb ;
8. rapports et exports ;
9. administration, audit et durcissement ;
10. validation PostgreSQL et préparation production.

## 18. Rebaseline E16 — autorité et permissions projet

Le rôle de compte décrit l'identité globale mais ne donne aucun accès implicite à un chantier. Sauf
super-administration de plateforme, chaque lecture ou mutation exige une `ProjectMembership` appartenant
à la même organisation et au projet visé.

| Capacité | Owner confirmé | Contractor | Site manager | Engineer | PIVOT reviewer |
|---|:---:|:---:|:---:|:---:|:---:|
| Lire le dossier projet | Oui | Oui | Oui | Oui | Oui |
| Confirmer l'ownership | Oui, pour soi | Non | Non | Non | Non |
| Autoriser/exécuter un paiement chantier | Oui | Non | Non | Non | Non |
| Suivre/réconcilier un paiement | Oui | Non | Non | Oui | Oui |
| Gérer le projet et son statut | Non | Non | Non | Oui | Non |
| Gérer les étapes terrain | Non | Non | Oui | Oui | Non |
| Vérifier stock et documents | Non | Non | Non | Oui | Oui |
| Changer le propriétaire | Non | Non | Non | Oui, avec motif | Non |

Invariants d'exécution :

- `projects_for_user()` est la frontière de lecture ; une ressource hors périmètre retourne 404 ;
- `has_project_role()` combine utilisateur, organisation, projet et rôle contextuel ;
- `can_authorize_project_finance()` impose `OWNER` et un ownership confirmé ;
- l'UX masque les actions interdites et les services Django répètent le contrôle ;
- le super-administrateur conserve son contrôle global audité sans devenir owner financier.

Les décisions ouvertes restent non implémentées : copropriété, délégation financière, organisation interne
des entrepreneurs, rémunération de l'ingénieur, inspections obligatoires, conservation de la
géolocalisation et autorité finale sur les contestations.

## 19. Critères de validation de l'architecture

- Chaque exigence de la SPEC possède un module responsable.
- Le code métier reste indépendant des templates et du fournisseur MeSomb.
- Deux organisations de test ne peuvent jamais accéder aux données l'une de l'autre.
- SQLite3 permet le développement sans enfermer le modèle dans des choix non portables.
- Les opérations financières et de stock sont atomiques, idempotentes lorsque nécessaire et auditables.
- L'interface peut être réalisée sans SPA ni second backend.
- Le passage à PostgreSQL et à un stockage objet est prévu sans refonte fonctionnelle.

## 20. Risques connus

| Risque | Réponse architecturale |
|---|---|
| Fuite inter-organisation | Filtrage centralisé, tests croisés, formulaires contextualisés |
| Double paiement | Clé d'idempotence et transitions contrôlées |
| Stock incohérent sous concurrence | Service atomique, mouvement obligatoire, PostgreSQL avant charge réelle |
| SQLite saturé | Usage temporaire et plan de migration explicite |
| Fichiers exposés | Stockage privé et téléchargement autorisé |
| Logique dupliquée dans les vues | Services et sélecteurs par domaine |
| Fournisseur de paiement couplé | Interface et adaptateur MeSomb |
| Rapports lents | Projection dédiée puis traitement asynchrone si nécessaire |
