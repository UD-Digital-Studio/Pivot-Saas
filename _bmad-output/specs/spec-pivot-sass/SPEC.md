# PIVOT-SASS — Spécification fonctionnelle

> **Avis de rebaseline (2026-09-04)** — Cette SPEC décrit le cadrage historique E1–E15. Le PRD
> canonique pour la trajectoire E16+ est
> [`PRD_PIVOT.md`](../../planning-artifacts/PRD_PIVOT.md). En cas de contradiction sur l'ownership,
> les rôles projet, les demandes de dépense, les validations ou MeSomb, le PRD rebaseliné prévaut.

Statut : cadrage fonctionnel validé pour conception UX  
Version : 0.2  
Date : 2026-08-14  
Source principale : `DOCUMENTATION_FONCTIONNELLE_PIVOT.md`

## 1. Objet

PIVOT-SASS est une application web de gestion et de suivi de projets de construction. Elle doit fournir un espace partagé et sécurisé aux ingénieurs, clients, responsables de chantier et administrateurs afin de centraliser :

- les projets et leurs participants ;
- le budget, les paiements et les retraits ;
- les étapes et le calendrier ;
- le stock et ses mouvements ;
- les documents, images et commentaires ;
- les rapports PDF et exports CSV.

Cette spécification formalise une refonte moderne de PIVOT sous forme de SaaS multi-entreprise. Elle reprend les fonctions utiles de l'existant sans imposer la reproduction de son code ni de ses anomalies. Les décisions encore ouvertes sont listées dans `OPEN_QUESTIONS.md`.

## 1.1 Décisions produit validées

- PIVOT-SASS est une refonte moderne, et non une copie exacte de l'application existante.
- Le produit est multi-entreprise : les données de chaque organisation sont strictement isolées.
- L'ingénieur gère intégralement les projets dont son organisation lui confie la responsabilité.
- Le client consulte, paie, dépose des documents et participe aux commentaires.
- Le responsable de chantier gère les étapes et le stock, dépose des documents et participe aux commentaires.
- L'administrateur dispose d'une gestion globale contrôlée et auditée.
- La devise initiale est le XAF.
- Les paiements initiaux passent par MeSomb et doivent être idempotents.
- Les documents et les opérations de validation du stock sont approuvés par l'ingénieur ; l'administrateur peut intervenir en recours.
- La logique applicative est développée exclusivement en Python avec Django. L'interface utilise les templates Django, HTML, CSS et le minimum de JavaScript natif requis, sans framework applicatif frontend ni backend Node.js.

## 2. Résultats attendus

Le produit doit permettre :

1. à un ingénieur de créer et piloter ses chantiers de bout en bout ;
2. aux personnes affectées de suivre l'avancement et de collaborer selon leurs droits ;
3. aux clients autorisés de payer et de consulter les opérations financières ;
4. à l'administration de gérer les comptes et les données sensibles ;
5. à chaque utilisateur de ne voir et modifier que les ressources auxquelles il est autorisé ;
6. de produire une trace exploitable des mouvements financiers, du stock et de l'avancement.

## 3. Acteurs et périmètres

### 3.1 Ingénieur

L'ingénieur est le propriétaire opérationnel des projets qu'il crée. Il peut :

- consulter son tableau de bord et les statistiques de ses projets ;
- créer et modifier ses projets ;
- créer des comptes client ou responsable de chantier ;
- rechercher et affecter des utilisateurs ;
- gérer le budget, les retraits, les étapes, le stock et les médias ;
- consulter les transactions ;
- commenter et produire des rapports ou exports.

Son inscription publique crée un compte inactif jusqu'à activation administrative.

### 3.2 Client

Le client accède uniquement aux projets auxquels il est affecté. Il peut au minimum :

- consulter les informations, membres, étapes, stock, médias et commentaires ;
- effectuer un paiement Mobile Money lorsqu'il y est autorisé ;
- consulter l'historique des transactions visible pour le projet ;
- téléverser des documents soumis à validation ;
- commenter ;
- consulter le calendrier et générer un rapport autorisé.

Le client ne modifie ni les étapes ni le stock.

### 3.3 Responsable de chantier

Le responsable de chantier accède uniquement aux projets auxquels il est affecté. Il consulte l'avancement, le planning, les médias, les commentaires et les rapports. Il peut créer et mettre à jour les étapes, ajouter ou ajuster le stock, déposer des documents et commenter. La validation finale du stock appartient à l'ingénieur.

### 3.4 Administrateur

L'administrateur gère les utilisateurs, profils, projets et objets métier dans une interface dédiée. Il active notamment les comptes ingénieur. Les privilèges de personnel et de superutilisateur doivent être explicitement séparés lors de la conception des permissions.

## 4. Exigences fonctionnelles

### AUTH — Authentification et comptes

- **AUTH-01** — Le système doit authentifier un utilisateur par identifiant et mot de passe.
- **AUTH-02** — Après connexion, le système doit orienter l'utilisateur vers l'espace correspondant à son rôle.
- **AUTH-03** — La déconnexion doit invalider la session active.
- **AUTH-04** — Un visiteur doit pouvoir demander un compte ingénieur ; ce compte reste inactif jusqu'à activation administrative.
- **AUTH-05** — Un visiteur doit pouvoir créer un compte client actif, sous réserve de confirmation de cette politique.
- **AUTH-06** — Un ingénieur doit pouvoir créer un utilisateur client ou responsable avec les champs requis et déclencher un e-mail d'accueil.
- **AUTH-07** — Chaque utilisateur doit disposer d'un profil modifiable : identifiant, prénom, nom, localisation, biographie, téléphone et photo.
- **AUTH-08** — Le système doit fournir un parcours de réinitialisation du mot de passe par jeton envoyé par e-mail.
- **AUTH-09** — Toute route authentifiée doit refuser un utilisateur anonyme côté serveur.

### PROJ — Projets et affectations

- **PROJ-01** — Un ingénieur doit pouvoir créer un projet avec nom, description, localisation, date, image, statut, montant et membres affectés.
- **PROJ-02** — Un projet doit avoir exactement un ingénieur responsable et zéro ou plusieurs membres affectés.
- **PROJ-03** — La recherche d'affectation doit proposer uniquement les utilisateurs éligibles et permettre une recherche par e-mail.
- **PROJ-04** — Seul l'ingénieur propriétaire ou un rôle administratif explicitement autorisé doit pouvoir modifier un projet.
- **PROJ-05** — Les statuts métier minimum sont : en attente, en cours et terminé.
- **PROJ-06** — Un utilisateur affecté doit pouvoir consulter la fiche du projet selon une vue et des actions adaptées à son rôle.
- **PROJ-07** — Le tableau de bord ingénieur doit afficher le total des projets et leur répartition par statut.
- **PROJ-08** — Les tableaux de bord client et responsable doivent afficher uniquement leurs projets affectés.

### FIN — Finances, paiements et retraits

- **FIN-01** — Une fiche projet doit présenter le montant du projet, le total payé, le montant disponible et le reste à payer.
- **FIN-02** — Le reste à payer doit être calculé à partir de montants décimaux selon une règle unique et testée.
- **FIN-03** — Le montant disponible doit être calculé selon une règle unique tenant compte uniquement des retraits dont le statut est admissible.
- **FIN-04** — Un membre autorisé doit pouvoir initier un paiement Mobile Money avec montant, opérateur et numéro payeur.
- **FIN-05** — Chaque tentative de paiement doit créer une transaction avec identifiant unique, auteur, montant, opérateur, payeur, statut et horodatage.
- **FIN-06** — Les succès, échecs et expirations doivent être enregistrés sans double comptabilisation.
- **FIN-07** — L'intégration de paiement doit être idempotente face aux doubles soumissions et rappels du fournisseur.
- **FIN-08** — Un ingénieur autorisé doit pouvoir enregistrer un retrait et consulter son historique paginé.
- **FIN-09** — Le système doit exporter les transactions et retraits autorisés au format CSV.
- **FIN-10** — Toute opération financière doit être contrôlée côté serveur et être traçable.

### PLAN — Étapes et calendrier

- **PLAN-01** — Un utilisateur autorisé doit pouvoir créer et modifier une étape avec titre, description, dates, coûts estimé et réel, et statut.
- **PLAN-02** — Les statuts minimum d'une étape sont : en attente, active et terminée.
- **PLAN-03** — La date de fin d'une étape ne doit pas précéder sa date de début.
- **PLAN-04** — Une image peut être associée à une étape.
- **PLAN-05** — Les étapes doivent être visibles en liste ou chronologie et dans un calendrier.
- **PLAN-06** — Le calendrier doit agréger uniquement les projets accessibles à l'utilisateur.
- **PLAN-07** — Les événements de calendrier doivent être accessibles sous une forme structurée exploitable par l'interface.
- **PLAN-08** — Les étapes d'un projet doivent être exportables en CSV par un utilisateur autorisé.

### STOCK — Stock et mouvements

- **STOCK-01** — Un utilisateur autorisé doit pouvoir créer un article avec nom, unité, prix unitaire, quantité, statut et projet.
- **STOCK-02** — Le prix total doit être dérivé de la quantité et du prix unitaire selon une règle unique.
- **STOCK-03** — Chaque ajustement de quantité doit créer un mouvement horodaté indiquant la variation, l'auteur et le stock résultant.
- **STOCK-04** — Une opération ne doit pas produire de quantité négative sauf règle métier explicitement validée.
- **STOCK-05** — L'ingénieur doit pouvoir vérifier un article de ses projets.
- **STOCK-06** — Le système doit conserver les statuts en attente, vérifié et approuvé tant que le workflow cible n'est pas clarifié.
- **STOCK-07** — Le système doit permettre l'import d'articles avec validation et rapport des lignes rejetées.
- **STOCK-08** — Le stock et son historique doivent être exportables en CSV avec filtre de dates.
- **STOCK-09** — Toutes les lectures et mutations de stock doivent vérifier l'accès au projet côté serveur.

### COLLAB — Documents, images et commentaires

- **COLLAB-01** — Un membre autorisé doit pouvoir téléverser un document rattaché à un projet.
- **COLLAB-02** — Un nouveau document doit recevoir le statut en attente ; l'accès au fichier doit respecter son statut et le rôle du lecteur.
- **COLLAB-03** — Le produit doit accepter au minimum les PDF pour les documents, avec validation du type et de la taille.
- **COLLAB-04** — Un utilisateur autorisé doit pouvoir ajouter des images de couverture ou de galerie.
- **COLLAB-05** — Seul un utilisateur expressément autorisé doit pouvoir supprimer une image.
- **COLLAB-06** — Les membres autorisés doivent pouvoir lire et ajouter des commentaires sur un projet.
- **COLLAB-07** — Seul l'auteur d'un commentaire ou un modérateur autorisé doit pouvoir le modifier ou le supprimer.
- **COLLAB-08** — Les mutations par navigateur doivent appliquer les protections CSRF appropriées.

### REPORT — Rapports et exports

- **REPORT-01** — Un utilisateur autorisé doit pouvoir générer un rapport PDF pour un projet accessible.
- **REPORT-02** — Le rapport doit pouvoir être filtré par période lorsqu'une donnée possède une date exploitable.
- **REPORT-03** — Le rapport complet peut inclure informations du projet, membres, stock, retraits, transactions, étapes, commentaires et images selon les permissions.
- **REPORT-04** — Une présentation de type « Weekly Site Report » doit être disponible, sous réserve de validation du format cible.
- **REPORT-05** — Tout export doit appliquer les mêmes règles d'accès que l'écran source.

### ADMIN — Administration

- **ADMIN-01** — L'administration doit permettre la gestion des utilisateurs, profils, projets, commentaires, étapes, documents, images, stocks, mouvements et transactions.
- **ADMIN-02** — Un administrateur autorisé doit pouvoir activer un compte ingénieur.
- **ADMIN-03** — Les opérations administratives sensibles doivent être journalisées.
- **ADMIN-04** — Les rôles administratifs ne doivent pas dépendre uniquement de l'affichage de l'interface ; les contrôles sont imposés côté serveur.

## 5. Règles d'autorisation minimales

| Ressource/action | Ingénieur propriétaire | Client affecté | Responsable affecté | Administrateur autorisé |
|---|---:|---:|---:|---:|
| Consulter le projet | Oui | Oui | Oui | Oui |
| Modifier le projet | Oui | Non | Non | Oui |
| Affecter des membres | Oui | Non | Non | Oui |
| Initier un paiement | Non par défaut | Oui | Non | Non par défaut |
| Enregistrer un retrait | Oui | Non | Non | Oui en recours |
| Créer/modifier une étape | Oui | Non | Oui | Oui |
| Ajouter/ajuster le stock | Oui | Non | Oui | Oui |
| Vérifier le stock | Oui | Non | Non | Oui en recours |
| Ajouter un document | Oui | Oui | Oui | Oui |
| Approuver un document | Oui | Non | Non | Oui en recours |
| Commenter | Oui | Oui | Oui | Oui |
| Modifier/supprimer un commentaire | Auteur/modérateur | Auteur | Auteur | Oui |

Les autorisations sont toujours limitées à l'organisation et aux projets accessibles de l'utilisateur.

## 6. Modèle conceptuel

- Une `Organisation` possède des utilisateurs et des projets ; toutes les données métier sont rattachées directement ou indirectement à une organisation.
- Un `Utilisateur` possède exactement un `Profil`, appartient à une organisation et possède un rôle métier.
- Un `Projet` appartient à un `Utilisateur` ingénieur.
- Un `Projet` possède plusieurs membres affectés.
- Un `Projet` possède des `Étapes`, `Documents`, `Images`, `Commentaires`, `ArticlesStock`, `Transactions` et `Retraits`.
- Un `ArticleStock` possède plusieurs `MouvementsStock`.
- Une `ImageProjet` peut être associée à une `Étape`.
- Les objets financiers utilisent des montants décimaux en XAF pour la première version.
- Les retraits doivent être des enregistrements structurés, et non un champ JSON opaque, si PIVOT-SASS est une refonte.

## 7. Exigences transversales

### Sécurité

- Autorisation systématique au niveau de chaque ressource et de chaque mutation.
- Protection CSRF des opérations basées sur une session navigateur.
- Validation serveur de tous les fichiers, montants, dates et quantités.
- Secrets de paiement et d'e-mail exclusivement fournis par la configuration d'environnement.
- Aucune décision d'accès ne doit dépendre de l'en-tête HTTP `Referer`.
- Journal d'audit pour les opérations financières, administratives et les mutations sensibles.

### Intégrité des données

- Montants persistés dans des types décimaux avec devise et règle d'arrondi définies.
- Dates persistées dans des types date/heure appropriés.
- Calculs financiers centralisés et couverts par des tests.
- Transactions de paiement et mouvements de stock immuables ou corrigés par écritures compensatoires.

### Expérience utilisateur

- Interface responsive sur les principaux parcours authentifiés.
- Navigation et actions adaptées au rôle.
- États vide, chargement, succès et erreur visibles.
- Thèmes clair et sombre facultatifs ; le support RTL reste hors engagement tant qu'il n'est pas validé.

### Exploitabilité

- Les échecs d'intégration externe doivent être journalisés sans exposer de secret.
- Les exports et rapports volumineux ne doivent pas rendre l'application indisponible.
- Les sauvegardes, la rétention et la restauration doivent être définies avant mise en production.

## 8. Critères de succès du périmètre initial

Le périmètre initial est acceptable lorsque :

1. chaque rôle peut se connecter et ne voit que ses projets autorisés ;
2. un ingénieur peut créer un projet, affecter des membres et suivre son avancement ;
3. les paiements sont enregistrés de façon idempotente et les agrégats financiers sont exacts ;
4. chaque variation de stock est traçable ;
5. les membres peuvent échanger documents, images et commentaires selon leurs droits ;
6. les étapes apparaissent dans le calendrier ;
7. un rapport PDF et les exports CSV autorisés peuvent être produits ;
8. les scénarios d'accès direct non autorisé échouent côté serveur ;
9. aucun secret applicatif n'est versionné ;
10. les décisions critiques de `OPEN_QUESTIONS.md` ont été tranchées.

## 9. Hors périmètre non confirmé

Les éléments suivants ne sont pas engagés par la source et nécessitent une demande explicite :

- facturation automatisée de l'abonnement SaaS ;
- application mobile native ;
- mode hors ligne ;
- messagerie temps réel ;
- notifications métier complètes ;
- recherche globale ;
- prise en charge de plusieurs devises ou pays ;
- comptabilité réglementaire ;
- portail fournisseur ou sous-traitant ;
- API publique.

## 10. Contraintes et héritage observés

La version documentée utilise Django, SQLite, templates Django, Tailwind CSS, JavaScript/AJAX, CKEditor 5, FullCalendar, MeSomb, xhtml2pdf, CSV et Django Unfold. PIVOT-SASS conserve Python/Django et les templates Django comme socle imposé. Le choix de la base de données et des bibliothèques Django spécialisées sera arrêté dans l'architecture. Aucun framework applicatif frontend distinct ne sera introduit.

Les anomalies observées à ne pas reproduire sont notamment : contrôles d'accès incomplets, endpoints sans protection CSRF, champs financiers textuels, dates de projet textuelles, retraits JSON, calculs financiers divergents, champ de stock obsolète, dépendance au `Referer`, duplication de scripts et valeurs de profil statiques.

## 11. Traçabilité et validation

La correspondance entre la source et les groupes d'exigences se trouve dans `SOURCE_MAP.md`. Les décisions ouvertes sont consignées dans `OPEN_QUESTIONS.md`.

Cette version est un contrat fonctionnel provisoire. Elle peut soutenir l'UX exploratoire, mais l'architecture et le découpage en stories doivent traiter les questions critiques avant d'être considérés prêts à implémenter.
