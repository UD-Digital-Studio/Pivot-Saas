# PIVOT-SASS — Epics et user stories

Statut : **rebaseliné pour la trajectoire E16+**  
Version : **1.0**  
Date : **2026-09-04**

## Principes de découpage

- Chaque story livre un comportement vérifiable.
- L'isolation par organisation et les permissions sont testées dans la story qui introduit la donnée concernée.
- SQLite3 est utilisé au démarrage sans SQL spécifique afin de préserver la migration PostgreSQL.
- Toute logique serveur est écrite en Python/Django ; l'interface utilise les templates Django.
- Les epics E1–E15 tracent la SPEC historique ; E16–E22 tracent le PRD canonique `PRD_PIVOT.md`.

## Vue d'ensemble

| Epic | Objectif | Stories | Dépend de |
|---|---|---:|---|
| E1 | Socle Django exploitable | 5 | — |
| E2 | Organisations, comptes et accès | 6 | E1 |
| E3 | Projets et affectations | 5 | E2 |
| E4 | Étapes et calendrier | 4 | E3 |
| E5 | Stock traçable | 5 | E3 |
| E6 | Collaboration de chantier | 5 | E3 |
| E7 | Finances et paiements | 6 | E3 |
| E8 | Rapports et exports | 4 | E4–E7 |
| E9 | Administration, audit et préparation production | 5 | E2–E8 |
| E10 | Finition fonctionnelle et expérience utilisateur | 7 | E3–E8 |
| E11 | Super-administration de la plateforme | 7 | E2–E10 |
| E12 | Administration opérationnelle et actions contrôlées | 7 | E11 |
| E13 | Assistant IA contextuel, sécurisé et piloté par les rôles | 8 | E2–E12 |
| E14 | Routage sémantique fiable et réponses métier garanties | 5 | E13 |
| E15 | Abonnements, pricing et contrôle d’accès SaaS | 9 | E2, E7, E11 |
| E16 | Rebaseline produit et autorité projet | 5 | E2, E3, E11 |
| E17 | Trois routes d’onboarding et activation | 6 | E16 |
| E18 | Capture terrain et registre de preuves | 6 | E16, E17 |
| E19 | Demandes de dépense et paiements autorisés | 7 | E16–E18, E7 |
| E20 | Revue technique et vérification à trois niveaux | 7 | E16, E18 |
| E21 | Rapprochement matières, dépenses et progression | 6 | E18–E20, E5 |
| E22 | Control room pilote et onboarding concierge | 7 | E16–E21, E11 |

## E1 — Socle Django exploitable

Objectif : permettre à l'équipe de développer et vérifier le produit sur une base Django cohérente.

### E1-S1 — Initialiser le projet Django

En tant que développeur, je veux un projet Django exécutable afin de disposer d'un socle reproductible.

Critères d'acceptation :

- Étant donné un environnement Python supporté, lorsque les dépendances sont installées et les migrations exécutées, alors le serveur Django démarre sans erreur.
- La configuration de développement utilise SQLite3.
- Les réglages sont séparés entre base, développement et production.
- Une page de contrôle confirme que l'application répond.
- Aucun secret réel n'est versionné.

Taille : M.

### E1-S2 — Installer la structure modulaire

En tant que développeur, je veux les applications métier déclarées afin que chaque domaine ait une responsabilité claire.

Critères d'acceptation :

- Les applications `core`, `organizations`, `accounts`, `projects`, `finance`, `planning`, `inventory`, `collaboration`, `reporting` et `audit` existent et sont déclarées.
- Chaque application possède un espace de tests.
- Les dépendances entre applications ne créent aucun import circulaire au démarrage.

Taille : S.

### E1-S3 — Créer le gabarit d'interface

En tant qu'utilisateur, je veux une interface responsive cohérente afin de naviguer sur ordinateur et mobile.

Critères d'acceptation :

- Un gabarit Django fournit en-tête, navigation, fil d'Ariane, contenu et messages.
- La navigation devient un tiroir utilisable à 360 px.
- Le focus clavier est visible et aucune action essentielle ne dépend du survol.
- Une page 403, 404 et 500 est disponible.

Taille : M. Traçabilité : exigences UX transversales.

### E1-S4 — Établir la stratégie de tests

En tant que développeur, je veux une commande de tests fiable afin de détecter les régressions.

Critères d'acceptation :

- Une commande documentée exécute tous les tests.
- Les tests utilisent une base isolée.
- Un test de fumée couvre le démarrage, une vue publique et une vue protégée.
- Les tests échouent avec un code non nul en cas de régression.

Taille : S.

### E1-S5 — Configurer les contrôles de qualité

En tant que développeur, je veux des contrôles automatiques afin de maintenir un code Python/Django cohérent.

Critères d'acceptation :

- Les commandes de formatage, lint et vérification Django sont documentées.
- Le projet passe ces commandes à l'état initial.
- Les migrations manquantes peuvent être détectées automatiquement.

Taille : S.

## E2 — Organisations, comptes et accès

Objectif : permettre une authentification sûre et isoler strictement les entreprises. (AUTH-01 à AUTH-09)

### E2-S1 — Modéliser l'organisation et l'utilisateur personnalisé

En tant qu'administrateur, je veux rattacher chaque utilisateur à une organisation afin d'isoler les entreprises.

Critères d'acceptation :

- Le modèle utilisateur personnalisé est configuré avant les migrations métier.
- Les rôles ingénieur, client, responsable et administrateur sont validés côté modèle/formulaire.
- Chaque utilisateur métier appartient à une organisation.
- Deux organisations de test et leurs utilisateurs ne partagent aucune donnée.

Taille : L.

### E2-S2 — Authentifier et déconnecter les utilisateurs

En tant qu'utilisateur, je veux ouvrir et fermer une session afin d'accéder à mon espace en sécurité.

Critères d'acceptation :

- Une connexion valide redirige selon le rôle.
- Des identifiants invalides produisent une erreur non ambiguë sans révéler le compte existant.
- La déconnexion invalide la session et renvoie à la connexion.
- Une vue protégée refuse un utilisateur anonyme. (AUTH-01 à AUTH-03, AUTH-09)

Taille : M.

### E2-S3 — Inscrire et activer un ingénieur

En tant qu'ingénieur, je veux demander un compte afin qu'un administrateur puisse m'autoriser à utiliser PIVOT-SASS.

Critères d'acceptation :

- L'inscription crée un compte ingénieur inactif avec validation des champs.
- L'administrateur peut l'activer.
- Un compte inactif ne peut pas se connecter.
- L'activation est auditée. (AUTH-04, ADMIN-02)

Taille : M.

### E2-S4 — Inviter des membres de l'organisation

En tant qu'ingénieur, je veux inviter un client ou responsable afin de constituer mon équipe projet.

Critères d'acceptation :

- L'invitation impose l'organisation de l'ingénieur et un rôle autorisé.
- Le jeton est limité dans le temps et inutilisable après acceptation.
- L'acceptation permet de définir le mot de passe.
- Une invitation ne peut pas rattacher le compte à une autre organisation. (AUTH-06)

Taille : L.

### E2-S5 — Gérer le profil

En tant qu'utilisateur, je veux mettre à jour mon profil afin de maintenir mes informations exactes.

Critères d'acceptation :

- Les champs prévus par AUTH-07 sont affichés et validés.
- La photo respecte les contraintes de type et taille.
- Un utilisateur ne peut modifier que son profil, sauf privilège administratif explicite.

Taille : M.

### E2-S6 — Réinitialiser le mot de passe

En tant qu'utilisateur, je veux réinitialiser mon mot de passe par e-mail afin de récupérer mon accès.

Critères d'acceptation :

- Le parcours Django de demande, jeton, changement et confirmation fonctionne.
- La réponse à la demande ne révèle pas si l'adresse existe.
- Un jeton expiré ou déjà utilisé est refusé. (AUTH-08)

Taille : S.

## E3 — Projets et affectations

Objectif : permettre à l'ingénieur de créer les chantiers et aux membres de voir uniquement leurs projets. (PROJ-01 à PROJ-08)

### E3-S1 — Créer et modifier un projet `[TERMINÉ]`

Critères d'acceptation :

- L'ingénieur crée un projet dans son organisation avec les champs de PROJ-01.
- Le budget utilise un montant décimal XAF et la date un vrai champ date.
- Seul l'ingénieur responsable ou l'administrateur autorisé peut modifier le projet.
- Un accès direct depuis une autre organisation retourne 404 ou 403 sans fuite d'information.

Taille : L.

### E3-S2 — Affecter les membres `[TERMINÉ]`

Critères d'acceptation :

- L'ingénieur recherche uniquement clients et responsables de son organisation.
- Il peut affecter ou retirer un membre de son projet.
- Une affectation dupliquée est refusée par contrainte.
- Un membre retiré perd immédiatement l'accès au projet. (PROJ-02, PROJ-03)

Taille : M.

### E3-S3 — Afficher les tableaux de bord par rôle `[TERMINÉ]`

Critères d'acceptation :

- L'ingénieur voit ses statistiques et projets.
- Le client et le responsable voient uniquement les projets auxquels ils sont affectés.
- Les listes ont états vide, pagination et filtres de statut.
- Les comptes d'une autre organisation n'influencent aucun indicateur. (PROJ-07, PROJ-08)

Taille : L.

### E3-S4 — Consulter la fiche projet par onglets `[TERMINÉ]`

Critères d'acceptation :

- La fiche fournit l'en-tête et les onglets définis dans l'UX.
- Chaque rôle ne voit que les actions autorisées.
- Les contrôles serveur refusent la manipulation d'URL ou de formulaire.
- L'affichage reste exploitable à 360 px. (PROJ-06)

Taille : L.

### E3-S5 — Gérer le cycle de statut du projet `[TERMINÉ]`

Critères d'acceptation :

- Les statuts en attente, en cours et terminé existent.
- Seul un acteur autorisé change le statut.
- Chaque changement est horodaté et audité.
- La règle de réouverture est encapsulée afin d'être finalisée sans modifier les vues. (PROJ-05)

Taille : M.

## E4 — Étapes et calendrier

Objectif : planifier et suivre l'avancement du chantier. (PLAN-01 à PLAN-08)

### E4-S1 — Gérer les étapes `[TERMINÉ]`

- L'ingénieur et le responsable affecté créent et modifient une étape.
- Le client peut consulter mais pas modifier.
- Les dates, coûts décimaux et statuts sont validés.
- Une date de fin antérieure au début est refusée.
- L'accès croisé organisation/projet est testé.

Taille : L.

### E4-S2 — Afficher la chronologie `[TERMINÉ]`

- Les étapes sont triées et présentées avec statut, dates, coûts et progression.
- Les états vide et retard sont compréhensibles.
- La vue mobile permet au responsable d'ouvrir rapidement une étape.

Taille : M.

### E4-S3 — Afficher le calendrier `[TERMINÉ]`

- Le calendrier reçoit uniquement les événements des projets accessibles.
- L'endpoint JSON refuse l'accès anonyme ou inter-organisation.
- Une interaction calendrier ne constitue jamais la seule manière de consulter une étape. (PLAN-05 à PLAN-07)

Taille : M.

### E4-S4 — Associer une photo et exporter les étapes `[TERMINÉ]`

- Une image autorisée peut être associée à une étape.
- Un utilisateur autorisé exporte en CSV les étapes du projet.
- L'export respecte l'organisation et l'affectation. (PLAN-04, PLAN-08)

Taille : M.

## E5 — Stock traçable

Objectif : connaître les quantités et l'historique de chaque article. (STOCK-01 à STOCK-09)

### E5-S1 — Créer et consulter les articles `[TERMINÉ]`

- L'ingénieur ou le responsable affecté crée un article valide.
- Le prix total est dérivé de quantité × prix unitaire.
- Le client dispose uniquement de la lecture si celle-ci est exposée.
- Les listes sont filtrées par organisation et projet.

Taille : L.

### E5-S2 — Ajuster une quantité avec mouvement `[TERMINÉ]`

- Toute entrée ou sortie crée atomiquement un mouvement.
- Le mouvement contient variation, quantité résultante, motif, auteur et date.
- Une quantité négative est refusée.
- Une nouvelle soumission involontaire ne doit pas être silencieusement comptée deux fois.

Taille : L.

### E5-S3 — Vérifier le stock `[TERMINÉ]`

- L'ingénieur peut faire passer un article en attente à vérifié.
- Le responsable ne peut pas valider sa propre saisie.
- La décision et son auteur sont audités.
- Le statut approuvé reste réservé à l'administrateur en recours jusqu'à décision métier finale.

Taille : M.

### E5-S4 — Importer le stock `[TERMINÉ]`

- Un fichier conforme crée les articles dans le bon projet.
- Les lignes invalides sont rejetées avec numéro et motif.
- Une erreur de ligne ne rattache jamais un article à une autre organisation.
- Le format d'import est téléchargeable. (STOCK-07)

Taille : L.

### E5-S5 — Exporter et consulter l'historique `[TERMINÉ]`

- L'historique est paginé et filtrable par dates.
- L'export CSV utilise exactement le périmètre autorisé.
- Les quantités exportées correspondent aux mouvements persistés. (STOCK-08)

Taille : M.

## E6 — Collaboration de chantier

Objectif : centraliser fichiers, photos et échanges. (COLLAB-01 à COLLAB-08)

### E6-S1 — Déposer et consulter un document `[TERMINÉ]`

- Un membre affecté peut déposer un PDF valide.
- Le document est en attente et appartient au projet/à l'organisation courants.
- Les types et tailles invalides sont refusés.
- Un fichier privé ne peut être téléchargé sans autorisation.

Taille : L.

### E6-S2 — Examiner un document `[TERMINÉ]`

- L'ingénieur approuve ou rejette avec motif.
- L'administrateur peut intervenir en recours.
- La décision est horodatée et auditée.
- Les règles de lecture d'un document en attente sont explicites et testées.

Taille : M.

### E6-S3 — Gérer la galerie d'images `[TERMINÉ]`

- Les membres autorisés ajoutent une image valide.
- L'ingénieur choisit une couverture unique.
- Seul l'auteur selon politique, l'ingénieur ou l'administrateur peut supprimer.
- Les fichiers restent protégés contre les accès croisés.

Taille : M.

### E6-S4 — Ajouter des commentaires `[TERMINÉ]`

- Un membre affecté lit et ajoute un commentaire.
- Les commentaires sont ordonnés du plus récent au plus ancien.
- Le contenu est rendu sans exécuter de code injecté.
- Les mutations appliquent CSRF.

Taille : M.

### E6-S5 — Modifier et supprimer un commentaire `[TERMINÉ]`

- L'auteur peut modifier ou supprimer son commentaire.
- L'ingénieur/modérateur autorisé peut modérer avec audit.
- Un autre membre ordinaire est refusé côté serveur.
- La suppression conserve la trace nécessaire sans exposer le contenu si la politique l'interdit.

Taille : M.

## E7 — Finances et paiements

Objectif : présenter des agrégats exacts et enregistrer les opérations sans double comptabilisation. (FIN-01 à FIN-10)

### E7-S1 — Modéliser les agrégats financiers `[TERMINÉ]`

- Le budget, les paiements réussis, les retraits comptabilisés, le disponible et le reste sont en XAF.
- Les calculs utilisent `Decimal` et une règle centrale.
- Les agrégats sont couverts par les cas zéro, partiel, complet et dépassement interdit.

Taille : L.

### E7-S2 — Créer l'adaptateur de paiement simulé `[TERMINÉ]`

- Une interface de passerelle isole le domaine du fournisseur.
- Un faux adaptateur produit succès, échec, expiration et attente.
- Les tests n'appellent aucun service externe.

Taille : M.

### E7-S3 — Initier un paiement idempotent `[TERMINÉ]`

- Seul un client affecté peut initier un paiement.
- Le montant, l'opérateur et le téléphone sont validés.
- Une transaction en attente et une clé d'idempotence sont créées avant l'appel.
- La répétition de la même requête ne double pas le total payé.

Taille : L.

### E7-S4 — Intégrer MeSomb `[TERMINÉ]`

- L'adaptateur traduit requêtes et statuts MeSomb.
- Les secrets viennent de l'environnement.
- Les réponses enregistrées et journaux sont expurgés.
- Les erreurs réseau laissent une transaction rapprochable et n'affichent pas de détail sensible.

Taille : L.

### E7-S5 — Gérer les retraits `[TERMINÉ]`

- L'ingénieur crée une demande de retrait valide.
- Les transitions et acteurs sont centralisés en attendant la règle finale.
- Seuls les retraits comptabilisés réduisent le disponible.
- Toute décision est auditée.

Taille : L. Bloqué partiellement par la décision sur le workflow des retraits.

### E7-S6 — Afficher l'historique financier `[TERMINÉ]`

- Transactions et retraits sont paginés et filtrés.
- Les statuts et références sont lisibles sans exposer de secret.
- Les indicateurs correspondent aux écritures persistées.
- Aucun accès croisé n'est possible.

Taille : M.

## E8 — Rapports et exports

Objectif : fournir des documents de suivi fiables et autorisés. (REPORT-01 à REPORT-05)

### E8-S1 — Construire la projection du rapport projet `[TERMINÉ]`

- Un service de lecture rassemble les données autorisées sans mutation.
- Le filtre de période utilise des dates typées.
- Les données d'une autre organisation sont exclues.

Taille : L.

### E8-S2 — Générer le PDF projet `[TERMINÉ]`

- Un utilisateur autorisé génère un PDF lisible du projet.
- Le rapport inclut uniquement les sections autorisées disponibles.
- Les volumes et erreurs de média sont gérés proprement.
- Le format hebdomadaire définitif reste remplaçable.

Taille : L.

### E8-S3 — Centraliser les exports CSV `[TERMINÉ]`

- Transactions, retraits, stock et étapes sont exportables selon les permissions.
- Encodage, en-têtes, dates et montants sont cohérents.
- Les filtres visibles correspondent au contenu exporté.

Taille : M.

### E8-S4 — Créer le centre de rapports `[TERMINÉ]`

- La page liste uniquement les projets accessibles.
- Elle permet le choix du projet, de la période et du type de sortie.
- Les états vide, génération et erreur sont définis.

Taille : M.

## E9 — Administration, audit et préparation production

Objectif : administrer le SaaS, observer les actions sensibles et préparer une exploitation sûre. (ADMIN-01 à ADMIN-04)

### E9-S1 — Configurer l'administration Django

- Les modèles utiles sont administrables avec recherche et filtres.
- Un administrateur d'organisation reste limité à son organisation.
- Un superadministrateur explicitement autorisé peut traverser les organisations.
- Les actions sensibles déclenchent un audit.

Taille : L.

### E9-S2 — Consigner les événements d'audit

- Les événements couvrent droits, argent, stock, validation et suppression.
- Ils enregistrent acteur, cible, action et date sans secret.
- Ils ne sont pas modifiables par un utilisateur métier.

Taille : M.

### E9-S3 — Durcir la configuration

- La configuration de production exige les secrets et hôtes attendus.
- HTTPS, cookies sécurisés et paramètres de sécurité sont activables par environnement.
- Les médias privés ne sont pas servis publiquement par défaut.
- Le déploiement échoue clairement si une variable critique manque.

Taille : M.

### E9-S4 — Valider la migration PostgreSQL

- Les migrations Django s'appliquent sur une base PostgreSQL vide.
- La suite de tests critique passe sur PostgreSQL.
- Une procédure de migration SQLite vers PostgreSQL est documentée et répétable.
- Les totaux financiers et de stock sont vérifiés après migration.

Taille : L.

### E9-S5 — Vérifier la préparation à la livraison

- Tous les parcours critiques possèdent des tests.
- Les contrôles d'accès croisé couvrent chaque domaine.
- Les sauvegardes, restauration, rétention, supervision et réponse aux incidents sont documentées.
- Aucune question critique ouverte ne reste sans décision ou exclusion explicite.

Taille : L.

## E10 — Finition fonctionnelle et expérience utilisateur

Objectif : rendre les parcours existants cohérents, bilingues, fluides et accessibles avant la préparation à la production.

### E10-S1 — Finaliser le multilingue français/anglais `[EN COURS]`

- Tous les écrans, modales, libellés de formulaires et messages utilisateur sont traduisibles.
- Le changement de langue conserve la page en cours lorsqu'elle est accessible.
- Les valeurs métier visibles utilisent des libellés traduits sans modifier les valeurs persistées.
- Les parcours critiques sont testés en français et en anglais.

Taille : L.

### E10-S2 — Uniformiser les interfaces `[EN COURS]`

- Les boutons, champs, tableaux, cartes et modales utilisent des composants visuels cohérents.
- Les thèmes clair et sombre restent lisibles sur chaque écran métier.
- La barre latérale ouverte ou réduite conserve un alignement correct du logo et des icônes.
- Les états chargement, vide, erreur et succès sont homogènes.

Taille : L.

### E10-S3 — Améliorer les tableaux de bord `[TERMINÉ]`

- Chaque rôle voit uniquement des indicateurs et actions utiles à son activité.
- Le graphique repose sur les données accessibles et possède une alternative textuelle.
- La recherche et les filtres de projets sont fonctionnels.
- Les indicateurs ne mélangent jamais les organisations.

Taille : M.

### E10-S4 — Ajouter un centre de notifications `[TERMINÉ]`

- Les événements importants génèrent une notification destinée aux bons utilisateurs.
- Un utilisateur peut consulter et marquer ses notifications comme lues.
- Les notifications respectent l'organisation, le projet et les permissions.
- Aucun secret ou contenu privé non autorisé n'est exposé.

Taille : L.

### E10-S5 — Fluidifier la gestion des projets `[TERMINÉ]`

- Les listes offrent recherche, tri, filtres et pagination utilisables.
- La progression et l'activité récente sont compréhensibles depuis la fiche projet.
- Les actions rapides sont adaptées au rôle et à l'état du projet.
- Les états vides guident clairement l'utilisateur vers l'action suivante.

Taille : M.

### E10-S6 — Renforcer les fichiers et commentaires `[TERMINÉ]`

- Les documents approuvés peuvent être prévisualisés lorsque leur format le permet.
- Les documents sont recherchables et classables sans contourner les permissions.
- Les commentaires utilisent une pagination ou un chargement progressif.
- Les compteurs de documents, photos et commentaires correspondent aux données autorisées.

Taille : M.

### E10-S7 — Vérifier le responsive et l'accessibilité `[TERMINÉ]`

- Les parcours critiques restent utilisables à 360 px, sur tablette et sur ordinateur.
- Le clavier, le focus, les libellés accessibles et les contrastes sont vérifiés.
- Les tableaux et modales ne provoquent pas de débordement bloquant.
- Les actions ne dépendent ni uniquement de la couleur ni uniquement du survol.

Taille : L.

## E11 — Super-administration de la plateforme `[TERMINÉ]`

Objectif : fournir aux super-administrateurs PIVOT un espace personnalisé, sécurisé et indépendant des espaces d'organisation pour superviser l'ensemble de la plateforme.

### E11-S1 — Créer le socle et le tableau de bord super-administrateur `[TERMINÉ]`

En tant que super-administrateur, je veux accéder à un espace de pilotage dédié afin de voir rapidement l'état global de la plateforme.

Critères d'acceptation :

- Un espace personnalisé est disponible sous `/super-admin/`, distinct de l'administration Django native.
- Seuls les utilisateurs authentifiés ayant `is_superuser=True` peuvent y accéder ; un administrateur d'organisation ne peut pas y entrer.
- Le tableau de bord affiche des indicateurs globaux utiles : organisations, utilisateurs, projets, validations en attente et volumes financiers.
- La navigation, le logo, les thèmes et le changement de langue sont cohérents avec l'identité PIVOT.
- Les accès autorisés et refusés sont couverts par des tests.

Taille : L.

### E11-S2 — Gérer les organisations `[TERMINÉ]`

En tant que super-administrateur, je veux rechercher et administrer les organisations afin de contrôler les espaces clients de la plateforme.

Critères d'acceptation :

- La liste des organisations propose recherche, filtres, tri et pagination.
- La fiche d'une organisation présente ses responsables, utilisateurs, projets et indicateurs d'activité.
- Le super-administrateur peut activer ou suspendre une organisation après confirmation.
- Une organisation suspendue ne peut plus utiliser les parcours métier, sans suppression de ses données.
- Chaque changement sensible est journalisé.

Taille : L.

### E11-S3 — Gérer les utilisateurs de la plateforme `[TERMINÉ]`

En tant que super-administrateur, je veux administrer les comptes de toutes les organisations afin de traiter les problèmes d'accès et de sécurité.

Critères d'acceptation :

- La liste globale offre recherche et filtres par rôle, organisation, statut et date d'inscription.
- La fiche utilisateur affiche son identité, son rôle, son organisation et son activité utile sans exposer son mot de passe.
- Le super-administrateur peut activer, suspendre ou déclencher une réinitialisation sécurisée du mot de passe.
- Il ne peut pas retirer accidentellement son propre dernier accès super-administrateur.
- Toutes les actions sensibles exigent une confirmation et sont auditées.

Taille : L.

### E11-S4 — Superviser les projets `[TERMINÉ]`

En tant que super-administrateur, je veux consulter les projets de toutes les organisations afin d'assister les utilisateurs et d'identifier les anomalies.

Critères d'acceptation :

- Les projets sont recherchables et filtrables par organisation, statut, responsable et période.
- La fiche de supervision regroupe les informations principales, les affectations, la progression et les compteurs métier.
- L'accès est en lecture seule par défaut ; toute intervention exceptionnelle est explicite, confirmée et auditée.
- Les fichiers restent soumis aux règles de confidentialité et de disponibilité existantes.
- Aucun accès super-administrateur ne modifie silencieusement les données d'une organisation.

Taille : M.

### E11-S5 — Centraliser les validations et la supervision financière `[TERMINÉ]`

En tant que super-administrateur, je veux traiter les dossiers nécessitant une intervention centrale afin de fiabiliser les opérations sensibles.

Critères d'acceptation :

- Une file centrale regroupe les validations et demandes financières nécessitant une action de la plateforme.
- Les entrées sont filtrables par type, organisation, statut, montant et ancienneté.
- Toute approbation ou tout rejet exige un motif, une confirmation et crée une notification appropriée.
- Les montants globaux sont calculés depuis les données autorisées sans mélanger les devises.
- Les transitions invalides, doubles traitements et accès non autorisés sont bloqués et testés.

Taille : L.

### E11-S6 — Consulter le journal d'audit global `[TERMINÉ]`

En tant que super-administrateur, je veux consulter les actions sensibles afin de comprendre qui a fait quoi et quand.

Critères d'acceptation :

- Le journal couvre les connexions sensibles et les changements d'organisation, d'utilisateur, de projet, de validation et de finance.
- Il est recherchable et filtrable par acteur, action, organisation, ressource et période.
- Chaque entrée contient l'acteur, l'horodatage, l'action, la cible et les informations techniques strictement nécessaires.
- Les secrets, mots de passe, jetons et fichiers privés ne sont jamais enregistrés dans l'audit.
- Les entrées d'audit ne peuvent pas être modifiées depuis l'interface.

Taille : L.

### E11-S7 — Gérer les paramètres et la santé de la plateforme `[TERMINÉ]`

En tant que super-administrateur, je veux piloter les paramètres transversaux afin de maintenir la plateforme sans intervention dans le code pour les options prévues.

Critères d'acceptation :

- Une page présente les paramètres fonctionnels autorisés, les intégrations configurées et l'état des services essentiels.
- Les secrets sont masqués et ne peuvent jamais être relus en clair depuis l'interface.
- Les modifications sont validées, confirmées, auditées et prises en compte de manière sûre.
- Les fonctions dangereuses de maintenance ne sont pas exposées comme de simples boutons.
- La page distingue clairement information, avertissement et incident.

Taille : L.

## E12 — Administration opérationnelle et actions contrôlées

Objectif : permettre au super-administrateur d'effectuer toutes les opérations nécessaires sur la plateforme, avec des permissions strictes, une confirmation par modal et une traçabilité complète.

Règles transversales :

- Toute création, modification, suspension, restauration, affectation, transfert, archivage ou suppression est confirmée dans une modal avant son exécution.
- Les actions irréversibles utilisent une confirmation renforcée indiquant précisément la cible et les conséquences.
- Les suppressions définitives sont interdites lorsqu'elles casseraient l'intégrité financière, documentaire ou d'audit ; un archivage est alors utilisé.
- Chaque action sensible est atomique, auditée et protégée contre les doubles soumissions.
- Les messages de réussite et d'erreur décrivent clairement le résultat sans exposer de donnée sensible.

### E12-S1 — Créer et modifier les organisations `[TERMINÉ]`

- Le super-administrateur peut créer une organisation depuis une modal avec son premier compte administrateur ou ingénieur.
- Le nom, l'identifiant et les informations autorisées d'une organisation peuvent être modifiés depuis une modal.
- Les doublons de nom technique, d'identifiant et d'e-mail sont validés avant enregistrement.
- La création et la modification nécessitent une confirmation finale et produisent un événement d'audit.
- Les identifiants temporaires ne sont jamais affichés ou enregistrés en clair dans l'audit.

Taille : L.

### E12-S2 — Archiver, restaurer et encadrer la suppression des organisations `[TERMINÉ]`

- Une organisation sans dépendance métier peut être supprimée après confirmation renforcée.
- Une organisation possédant des projets, finances, fichiers ou audits est archivée plutôt que supprimée.
- Une organisation archivée peut être restaurée depuis une modal de confirmation.
- L'archivage bloque les accès sans supprimer les données ni l'historique.
- Les conséquences exactes sont affichées avant confirmation et chaque opération est auditée.

Taille : L.

### E12-S3 — Créer et modifier les utilisateurs `[TERMINÉ]`

- Le super-administrateur peut créer un utilisateur et l'affecter à une organisation avec un rôle autorisé.
- Les informations d'identité, l'e-mail, le rôle et le statut peuvent être modifiés dans une modal.
- La cohérence entre rôle, organisation, projets et permissions est validée.
- L'utilisateur reçoit un lien sécurisé pour définir son mot de passe ; aucun mot de passe n'est communiqué en clair.
- La création et chaque modification sont confirmées et auditées.

Taille : L.

### E12-S4 — Transférer et réaffecter les utilisateurs `[TERMINÉ]`

- Un utilisateur peut être transféré vers une autre organisation uniquement si ses dépendances sont compatibles.
- Les projets gérés et affectations existantes sont présentés dans la modal avant décision.
- Le super-administrateur choisit explicitement les réaffectations nécessaires ou annule le transfert.
- Aucun transfert partiel ou incohérent n'est enregistré en cas d'erreur.
- Le transfert et toutes les réaffectations sont confirmés, atomiques et audités.

Taille : L.

### E12-S5 — Intervenir exceptionnellement sur les projets `[TERMINÉ]`

- Le super-administrateur peut corriger les informations autorisées d'un projet depuis une modal dédiée.
- Il peut changer le responsable, les membres ou le statut lorsque l'intervention est justifiée.
- Un motif obligatoire explique chaque intervention exceptionnelle.
- Les impacts sur l'organisation, la planification et les permissions sont validés avant l'enregistrement.
- Les valeurs précédentes, les nouvelles valeurs et le motif sont audités sans données sensibles.

Taille : L.

### E12-S6 — Administrer les contenus et opérations rattachés `[TERMINÉ]`

- Les actions nécessaires sur étapes, stocks, documents, photos, commentaires et demandes financières sont disponibles selon leur état.
- Une donnée liée à une opération financière ou à un audit ne peut pas être supprimée silencieusement.
- Les contenus supprimables utilisent une modal de confirmation ; les autres utilisent rejet, annulation ou archivage.
- Le propriétaire et l'organisation de chaque donnée sont vérifiés avant toute action.
- Toutes les interventions sont auditées et notifiées lorsque nécessaire.

Taille : XL.

### E12-S7 — Uniformiser et tester les modales d'administration `[TERMINÉ]`

- Toutes les actions E12 utilisent les composants Tailwind communs de modal.
- Chaque modal indique l'action, la cible, les conséquences et si l'opération est réversible.
- Le focus clavier, la fermeture, les erreurs, le responsive et les doubles clics sont correctement gérés.
- Les actions dangereuses exigent une confirmation renforcée et ne peuvent pas être déclenchées par un simple lien GET.
- Les tests couvrent autorisations, validation, confirmation, atomicité, audit et protection inter-organisations.

Taille : L.

## E13 — Assistant IA contextuel, sécurisé et piloté par les rôles

Objectif : intégrer dans PIVOT un assistant conversationnel utilisant OpenRouter, capable d'expliquer et de consulter les données métier autorisées sans contourner les permissions Django, l'isolation des organisations ni les règles propres aux rôles.

Règles transversales :

- OpenRouter ne reçoit que les données strictement nécessaires à la question et déjà autorisées pour l'utilisateur connecté.
- Le modèle IA n'obtient aucun accès SQL, ORM, système de fichiers ou secret direct.
- Les contrôles d'organisation, de projet et de rôle sont exécutés par Django avant tout appel au fournisseur IA.
- La première version est strictement en lecture seule : elle ne crée, ne modifie, ne valide, ne paie et ne supprime aucune donnée.
- Une réponse ne doit jamais révéler l'existence d'une donnée inaccessible, même indirectement.
- L'assistant distingue une information issue de PIVOT, une explication fonctionnelle et une réponse indisponible.

### E13-S1 — Configurer l'intégration OpenRouter `[TERMINÉ]`

En tant qu'administrateur technique, je veux configurer OpenRouter de manière sécurisée afin de connecter PIVOT à un modèle IA sans exposer les clés ni rendre l'application dépendante d'un modèle unique.

Critères d'acceptation :

- La clé, l'URL d'API, le modèle, le délai d'expiration et les limites sont configurés par variables d'environnement.
- Aucune clé ni contenu sensible n'est écrit dans les journaux, les templates ou la base de données.
- Un service Python/Django centralise les appels, normalise les erreurs et permet de remplacer le modèle configuré.
- Les timeouts, réponses invalides, limites fournisseur et indisponibilités produisent un message utilisateur clair.
- Les appels externes peuvent être simulés dans les tests sans connexion réseau.

Taille : M.

### E13-S2 — Modéliser les conversations et les messages `[TERMINÉ]`

En tant qu'utilisateur connecté, je veux conserver une conversation avec l'assistant afin de poursuivre mes questions sans perdre le contexte utile.

Critères d'acceptation :

- Une conversation appartient à un utilisateur et, le cas échéant, à son organisation.
- Les messages distinguent utilisateur, assistant, statut, horodatage et erreur technique non sensible.
- Un utilisateur ne peut jamais consulter ou continuer la conversation d'un autre utilisateur.
- La taille, le nombre de messages transmis et la durée de conservation sont limités.
- La suppression ou l'archivage d'une conversation respecte les exigences d'audit et de confidentialité.

Taille : M.

### E13-S3 — Créer l'interface flottante de discussion à droite `[TERMINÉ]`

En tant qu'utilisateur connecté, je veux ouvrir l'assistant depuis un bouton flottant afin de l'utiliser sans quitter la page courante.

Critères d'acceptation :

- Un bouton PIVOT avec une véritable icône est fixé en bas à droite des interfaces authentifiées.
- Au clic, une fenêtre verticale s'ouvre sur le côté droit de l'écran, au-dessus ou à proximité du bouton, jamais vers la gauche comme panneau principal.
- La fenêtre comporte un en-tête, l'historique défilant, un état de chargement, une zone de saisie, l'envoi et la fermeture.
- L'interface respecte `#00157f`, le thème clair/sombre, les composants existants et l'accessibilité clavier.
- Sur téléphone, la fenêtre utilise presque tout l'écran sans masquer définitivement la fermeture ni la saisie.
- Le changement de page ne doit pas exposer la conversation d'un autre compte ni casser la navigation.

Taille : L.

### E13-S4 — Construire le catalogue métier depuis les modèles Django `[TERMINÉ]`

En tant qu'utilisateur, je veux que l'assistant comprenne les concepts de PIVOT afin d'obtenir des réponses cohérentes avec les projets, étapes, stocks, documents, finances et utilisateurs.

Critères d'acceptation :

- Un catalogue contrôlé décrit les modèles, champs utiles, relations, statuts et vocabulaires métier issus des `models.py`.
- Le catalogue n'expose ni champs secrets, ni jetons, ni mots de passe, ni données techniques inutiles.
- Les changements significatifs des modèles sont détectés par des tests ou une validation explicite du catalogue.
- L'assistant n'invente pas de modèle, de champ, de statut ou de relation absent du catalogue autorisé.
- Les libellés français et anglais sont pris en compte dans la compréhension et les réponses.

Taille : L.

### E13-S5 — Appliquer les permissions, rôles et frontières d'organisation `[TERMINÉ]`

En tant que responsable de la plateforme, je veux que l'assistant applique les mêmes permissions que les vues Django afin qu'aucune réponse ne contourne les règles de PIVOT.

Critères d'acceptation :

- Chaque demande est évaluée avec l'utilisateur authentifié, son rôle, son organisation et ses projets accessibles.
- Un client ne reçoit aucune donnée ni procédure réservée à l'ingénieur, à l'administrateur ou au super-administrateur.
- Un responsable de chantier, un ingénieur et un administrateur ne voient que le périmètre permis par les sélecteurs métier existants.
- Une question inter-organisation, une référence à un objet inaccessible ou une tentative de changement de rôle est refusée sans fuite d'information.
- Les permissions sont garanties dans le code Django et ne reposent jamais uniquement sur le prompt envoyé au modèle.
- Des tests croisés couvrent chaque rôle, deux organisations et plusieurs affectations de projets.

Taille : XL.

### E13-S6 — Fournir des outils de consultation métier en lecture seule `[TERMINÉ]`

En tant qu'utilisateur autorisé, je veux interroger les données PIVOT en langage naturel afin d'obtenir des synthèses fiables dans mon périmètre.

Critères d'acceptation :

- Des outils Django explicitement autorisés couvrent progressivement projets, étapes, calendrier, stocks, documents, photos, commentaires, rapports et finances.
- Chaque outil utilise les services et sélecteurs existants plutôt qu'une requête générée librement par l'IA.
- Les résultats sont filtrés avant transmission à OpenRouter et limités en volume.
- Les montants, statuts, dates et décomptes importants sont calculés par Django, pas estimés par le modèle.
- Les sources internes utilisées peuvent être indiquées dans la réponse sans révéler d'identifiant ou de donnée inaccessible.
- Aucun outil de cette story ne réalise une écriture ou une opération financière.

Taille : XL.

### E13-S7 — Sécuriser les prompts, les données et les coûts `[TERMINÉ]`

En tant qu'exploitant, je veux contrôler les abus et les coûts de l'assistant afin de préserver la sécurité et la disponibilité de PIVOT.

Critères d'acceptation :

- Les instructions système sont séparées des messages utilisateur et les tentatives d'injection ne peuvent pas activer un outil interdit.
- Les fichiers, commentaires et autres contenus métier sont traités comme données non fiables, jamais comme instructions système.
- Des limites par utilisateur et par période encadrent messages, tokens, fréquence et concurrence.
- Les données personnelles et financières transmises sont minimisées et les secrets sont systématiquement exclus.
- Les erreurs, refus, latences et consommations utiles sont journalisés sans conserver les prompts sensibles en clair.
- Une seconde demande identique ou simultanée ne provoque pas d'appels incontrôlés.

Taille : L.

### E13-S8 — Tester, superviser et documenter l'assistant `[TERMINÉ]`

En tant qu'équipe produit, je veux démontrer la fiabilité de l'assistant afin de le mettre à disposition sans compromettre les fonctions existantes.

Critères d'acceptation :

- Les tests couvrent interface, API, historique, erreurs OpenRouter, timeouts, limites et réponses sans données disponibles.
- Une matrice teste les questions autorisées et interdites pour client, responsable de chantier, ingénieur, administrateur et super-administrateur.
- Les tentatives d'accès inter-organisation et d'injection de prompt sont testées automatiquement.
- Une supervision indique disponibilité, volume, latence et erreurs sans exposer les conversations.
- La configuration, les limites fonctionnelles, la confidentialité et la procédure de désactivation sont documentées.
- L'assistant peut être désactivé globalement sans empêcher l'utilisation normale de PIVOT.

Taille : L.

## E14 — Routage sémantique fiable et réponses métier garanties

Objectif : comprendre les formulations naturelles, sélectionner les lectures Django pertinentes
et produire une réponse fondée sur les données accessibles au rôle connecté.

### E14-S1 — Définir le contrat du routeur sémantique `[TERMINÉ]`

En tant qu’équipe produit, je veux un catalogue explicite des intentions afin que chaque question
métier soit reliée à un domaine Django connu.

Critères d’acceptation :

- Les domaines organisations, utilisateurs, projets, étapes, stocks, documents, photos,
  commentaires, finances et rapports sont déclarés dans un registre unique.
- Le routeur accepte synonymes, variantes françaises et anglaises et fautes courantes.
- Une intention inconnue ne déclenche aucune lecture métier incontrôlée.

### E14-S2 — Sélectionner une ou plusieurs intentions `[TERMINÉ]`

En tant qu’utilisateur, je veux poser une question composée afin que l’assistant consulte tous les
domaines nécessaires sans dépendre d’une expression exacte.

Critères d’acceptation :

- Plusieurs intentions peuvent être détectées dans une même question.
- Les intentions précises ont priorité sur les intentions générales.
- Le résultat du routage est déterministe, limité et testable.

### E14-S3 — Résoudre le périmètre métier autorisé `[TERMINÉ]`

En tant qu’exploitant, je veux que Django décide du périmètre afin qu’OpenRouter ne puisse jamais
élargir les droits du compte.

Critères d’acceptation :

- Le rôle, l’organisation et les projets accessibles sont contrôlés avant chaque outil.
- Un super-administrateur, un administrateur d’organisation et un rôle opérationnel reçoivent des
  périmètres distincts.
- Les demandes inter-organisations sont refusées sans fuite de données.

### E14-S4 — Produire des résultats explicites et sûrs `[TERMINÉ]`

En tant qu’utilisateur, je veux distinguer une absence de données d’un refus afin de comprendre la
réponse obtenue.

Critères d’acceptation :

- Chaque outil retourne son périmètre, son nombre de résultats et une collection éventuellement vide.
- Un accès interdit produit un refus déterministe avant OpenRouter.
- Une collection vide est transmise comme donnée autorisée vide et ne devient pas un faux refus.

### E14-S5 — Valider les formulations et rôles `[TERMINÉ]`

En tant qu’équipe produit, je veux une matrice de non-régression afin que les formulations naturelles
restent compatibles avec les permissions.

Critères d’acceptation :

- Les tests couvrent les cinq profils, les dix domaines, les synonymes, fautes et questions composées.
- Les réponses avec données, sans données et interdites sont testées séparément.
- La suite Django complète passe avant la clôture de l’Epic.

## E15 — Abonnements, pricing et contrôle d’accès SaaS

Objectif : monétiser PIVOT par organisation d’ingénierie avec des forfaits configurables, des quotas compréhensibles, des paiements MeSomb distincts des finances de chantier et une restriction progressive qui protège les données en cas d’impayé.

Règles transversales :

- L’abonnement appartient à l’organisation et est piloté par son ingénieur principal ou son administrateur autorisé.
- Le nombre d’utilisateurs facturés correspond aux membres internes actifs : ingénieurs, responsables de chantier et administrateurs d’organisation. Les clients ne consomment pas ce quota.
- Les paiements d’abonnement sont strictement séparés des paiements, soldes, retraits et rapports financiers des projets.
- Aucun impayé, dépassement de quota ou changement de forfait ne supprime une organisation, un projet, un fichier, une transaction ou un historique.
- Les prix, durées, quotas et fonctions sont configurables ; aucune valeur commerciale sensible n’est codée en dur dans les vues ou templates.
- Toutes les décisions d’accès sont appliquées côté Django et non uniquement par masquage de boutons.
- Toute activation, prolongation, suspension, changement de forfait ou correction manuelle est atomique et auditée.

### E15-S1 — Modéliser les forfaits et abonnements `[TERMINÉ]`

En tant que responsable de la plateforme, je veux définir les forfaits et leur cycle de vie afin de disposer d’une source unique pour les droits commerciaux de chaque organisation.

Critères d’acceptation :

- `SubscriptionPlan` décrit le nom, le code, le prix mensuel et annuel, la devise, les quotas, les fonctions autorisées, l’ordre d’affichage et le statut public/actif.
- `OrganizationSubscription` relie une organisation à un forfait et conserve les dates d’essai, de début, d’échéance, de grâce et le statut courant.
- Les statuts couvrent au minimum : essai, actif, grâce, lecture seule, suspendu, annulé et expiré.
- Une organisation ne possède qu’un abonnement courant effectif à un instant donné.
- Les historiques nécessaires sont conservés sans dépendre des futures modifications du forfait.
- Les contraintes, migrations SQLite3 et tests de modèle empêchent les dates et états incohérents.

Taille : L.

### E15-S2 — Présenter les forfaits et démarrer l’essai `[TERMINÉ]`

En tant qu’ingénieur, je veux comprendre les offres et bénéficier d’un essai afin d’évaluer PIVOT avant de payer.

Critères d’acceptation :

- Une page de pricing responsive présente les forfaits, prix mensuel/annuel, projets actifs, membres internes, stockage et fonctions incluses.
- Les limites expliquent explicitement que les clients ne sont pas comptés parmi les membres internes.
- L’ingénieur peut comparer les offres et choisir une périodicité sans ambiguïté sur la devise ou le renouvellement.
- Après validation du compte ingénieur, une période d’essai de 3 mois calendaires est créée une seule fois pour l’organisation, à compter de sa date d’activation.
- La date de fin est calculée par ajout de 3 mois calendaires, et non par une approximation fixe en nombre de jours.
- L’interface affiche les jours restants et la date exacte de fin d’essai.
- Une organisation ne peut pas recréer des essais successifs par changement de compte principal.

Taille : L.

### E15-S3 — Appliquer les quotas de projets et membres internes `[TERMINÉ]`

En tant qu’ingénieur, je veux connaître mon utilisation et être averti avant la limite afin d’adapter mon forfait sans bloquer mon activité par surprise.

Critères d’acceptation :

- Le quota de membres compte uniquement les ingénieurs, responsables de chantier et administrateurs actifs de l’organisation ; les clients sont exclus.
- Le quota de projets compte les projets actifs selon une définition unique et documentée ; les projets archivés ne le consomment pas.
- L’utilisation et la limite sont visibles dans l’espace abonnement avec avertissements à 80 % et 100 %.
- À la limite, les données existantes restent accessibles, mais toute nouvelle création dépassant le quota est refusée côté serveur avec une explication et un lien vers les forfaits.
- Une invitation interne en attente réserve ou non une place selon une règle explicite et testée ; aucune acceptation ne peut dépasser silencieusement la limite.
- La désactivation d’un membre interne ou l’archivage admissible d’un projet libère la capacité sans effacer son historique.

Taille : XL.

### E15-S4 — Encaisser un abonnement avec MeSomb `[TERMINÉ]`

En tant qu’ingénieur, je veux payer mon forfait par Mobile Money afin d’activer ou renouveler mon organisation.

Critères d’acceptation :

- `SubscriptionPayment` enregistre organisation, forfait, période, montant, devise, opérateur, téléphone, référence, statut et horodatages sans se confondre avec `PaymentTransaction` des projets.
- Le montant est calculé côté Django depuis le forfait et la périodicité sélectionnés ; il ne peut pas être imposé par le navigateur.
- L’initiation MeSomb applique idempotence, timeout explicite, reprise limitée, vérification automatique et blocage des doubles tentatives pendant un état incertain.
- Les états couvrent au minimum : initié, en attente, réussi, refusé, annulé, échoué et expiré.
- Seul un succès confirmé active ou prolonge l’abonnement ; un refus ou une annulation ne modifie pas sa période.
- Les références, clés et erreurs sensibles ne sont jamais exposées dans les templates ou journaux.

Taille : XL.

### E15-S5 — Gérer renouvellement, changement de forfait et échéances `[TERMINÉ]`

En tant qu’ingénieur, je veux renouveler ou changer mon offre afin d’adapter PIVOT à l’évolution de mon entreprise.

Critères d’acceptation :

- Le renouvellement manuel mensuel ou annuel prolonge la période à partir de la bonne date, sans perdre les jours déjà payés.
- Une montée de gamme peut prendre effet immédiatement selon une règle de calcul affichée avant paiement.
- Une baisse de gamme prend effet à l’échéance et ne supprime aucune donnée si l’utilisation dépasse les futures limites.
- Une tâche Django vérifie périodiquement les essais, échéances, périodes de grâce et paiements incertains sans dépendre d’une visite utilisateur.
- Les transitions sont idempotentes et résistent à deux traitements simultanés.
- Toute correction de période conserve l’ancien état dans l’historique d’abonnement.

Taille : XL.

### E15-S6 — Notifier avant et après l’expiration `[TERMINÉ]`

En tant qu’ingénieur principal, je veux être informé des échéances afin de renouveler avant la restriction de mon organisation.

Critères d’acceptation :

- Des notifications dans l’application et des e-mails PIVOT sont envoyés aux échéances configurées, par défaut J-7, J-3, J-1, jour d’expiration et fin de grâce.
- Les destinataires sont l’ingénieur principal et les administrateurs d’organisation autorisés disposant d’une adresse valide.
- Chaque message indique le forfait, la date, l’état, les conséquences et un lien sécurisé vers la facturation.
- Les e-mails utilisent les logos officiels et les modèles bilingues français/anglais.
- Une même échéance ne génère pas de doublons lors de plusieurs exécutions de la tâche.
- Les refus, annulations et succès de paiement produisent une notification adaptée sans divulguer de secret fournisseur.

Taille : L.

### E15-S7 — Restreindre progressivement une organisation impayée `[TERMINÉ]`

En tant qu’utilisateur d’une organisation, je veux conserver l’accès à mes données même lorsque l’abonnement expire afin d’éviter toute perte et comprendre comment réactiver le service.

Critères d’acceptation :

- Pendant l’essai ou l’abonnement actif, les fonctions autorisées par le forfait restent disponibles.
- Pendant une grâce configurable, par défaut 7 jours, l’organisation reste utilisable et affiche un avertissement persistant aux responsables.
- Après la grâce, l’organisation passe en lecture seule : consultation des données et téléchargement des documents déjà approuvés restent possibles.
- En lecture seule, les créations, modifications, invitations, dépôts, commentaires, nouveaux rapports, assistant IA, paiements de projet et retraits sont refusés côté serveur, sauf accès à la facturation et renouvellement.
- Les clients et responsables de chantier peuvent consulter leurs projets autorisés, mais ne peuvent plus contribuer jusqu’à réactivation.
- Aucun contenu ni historique n’est supprimé et les endpoints API/AJAX appliquent la même règle que les pages HTML.
- Après succès du renouvellement, les fonctions sont restaurées automatiquement selon le forfait sans intervention manuelle.

Taille : XL.

### E15-S8 — Administrer les abonnements depuis le super-admin `[TERMINÉ]`

En tant que super-administrateur, je veux superviser les forfaits et abonnements afin de traiter les incidents commerciaux sans modifier directement la base.

Critères d’acceptation :

- Le super-admin peut rechercher et filtrer les abonnements par organisation, forfait, statut, échéance et niveau d’utilisation.
- Il peut créer ou modifier un forfait, le retirer de la vente sans altérer les abonnements existants et prévisualiser son affichage public.
- Il peut accorder une prolongation, changer le forfait, suspendre ou réactiver une organisation depuis une modale avec motif obligatoire.
- Les impacts sur dates, quotas et accès sont affichés avant confirmation.
- Les secrets MeSomb sont masqués et aucune opération ne simule un paiement réussi.
- Toutes les interventions sont confirmées, atomiques, auditées et protégées contre les doubles soumissions.

Taille : XL.

### E15-S9 — Fournir facturation, historique et matrice de tests `[TERMINÉ]`

En tant qu’ingénieur et exploitant, je veux consulter l’historique commercial et disposer de garanties automatisées afin de comprendre chaque période payée et fiabiliser la mise en production.

Critères d’acceptation :

- L’espace abonnement affiche forfait courant, utilisation, prochaine échéance, historique des périodes et paiements avec leurs statuts.
- Un reçu ou justificatif PDF professionnel est généré uniquement pour un paiement confirmé et porte une référence unique.
- Les exports de facturation restent séparés des rapports financiers des chantiers.
- Les tests couvrent essai, quotas, clients non comptés, paiement réussi/refusé/annulé/incertain, renouvellement, changement de forfait, grâce, lecture seule et réactivation.
- Une matrice vérifie les restrictions pour client, responsable de chantier, ingénieur, administrateur d’organisation et super-administrateur, sur pages HTML et endpoints POST/AJAX.
- Les tests garantissent l’isolation entre deux organisations et l’absence de suppression de données après expiration.
- La documentation décrit configuration, tâches planifiées, exploitation, incidents MeSomb et procédure de désactivation du module commercial.

Taille : XL.

## E16 — Rebaseline produit et autorité projet `[TERMINÉ]`

> Périmètre E16–E22 : ces epics transposent uniquement les capacités métier décrites dans le document
> stratégique BLUEPRINT. Les permissions serveur, migrations, contrôles d'intégrité, versionnement et
> audit sont des moyens techniques nécessaires, pas des fonctionnalités produit supplémentaires.
> MeSomb constitue l'unique extension fonctionnelle conservée par décision explicite du propriétaire de PIVOT.

Objectif : aligner PIVOT sur le nouveau PRD sans réécriture destructive, faire du client le
propriétaire du chantier et séparer identité, rôle projet et autorité financière.

Règles transversales :

- Le produit conserve le nom PIVOT.
- Le client est le Project Owner et possède l'autorité financière finale.
- Le créateur du lead ne devient jamais propriétaire implicitement.
- Les migrations préservent les projets et historiques E1–E15.

### E16-S1 — Rebaseliner le PRD PIVOT `[TERMINÉ]`

En tant qu'équipe produit, je veux un PRD canonique conforme à la stratégie afin que toutes les
nouvelles conceptions décrivent le même produit.

Critères d'acceptation :

- Le PRD définit PIVOT, le problème de confiance, les acteurs et les principes non négociables.
- Le client y est explicitement défini comme propriétaire et autorité financière finale.
- MeSomb est conservé après autorisation du client et séparé des paiements d'abonnement.
- Les trois routes d'onboarding, preuves, validations, rapprochements et KPI pilote sont couverts.
- Les anciens documents signalent clairement que ce PRD prévaut pour E16+.

Taille : L.

### E16-S2 — Séparer rôle de compte et rôle projet `[TERMINÉ]`

En tant qu'administrateur, je veux attribuer un rôle contextuel dans chaque projet afin que les droits ne
dépendent pas uniquement du type global du compte.

Critères d'acceptation :

- Les rôles projet couvrent `OWNER`, `CONTRACTOR`, `SITE_MANAGER`, `ENGINEER` et `PIVOT_REVIEWER`.
- Un utilisateur peut avoir des rôles différents dans plusieurs projets sans fuite de permissions.
- Les sélecteurs et services Django utilisent le rôle projet et l'organisation.
- Les migrations initialisent les rôles des membres existants sans perte de données.
- Une matrice de tests couvre toutes les lectures et mutations sensibles.

Taille : XL.

### E16-S3 — Modéliser l'ownership confirmé `[TERMINÉ]`

En tant que client, je veux confirmer officiellement être propriétaire afin que l'autorité du projet soit
explicite et traçable.

Critères d'acceptation :

- Chaque projet actif possède un client propriétaire confirmé.
- La confirmation conserve date, acteur, conditions acceptées et version.
- Le créateur préliminaire ne reçoit aucun droit owner automatiquement.
- Tout changement de propriétaire exige une action contrôlée et un motif.
- Aucun workflow financier ne s'ouvre sans ownership valide.

Taille : L.

### E16-S4 — Migrer les projets existants `[TERMINÉ]`

En tant qu'exploitant, je veux migrer les projets actuels afin de préserver leur continuité dans le nouveau
modèle d'autorité.

Critères d'acceptation :

- Le client unique affecté devient owner selon une règle déterministe et auditée.
- Les projets sans client ou avec plusieurs clients sont signalés pour revue manuelle.
- Aucun projet, fichier, transaction ou historique n'est supprimé.
- La migration est idempotente, testée sur SQLite3 et compatible PostgreSQL.
- Un rapport avant/après permet de contrôler les résultats.

Taille : XL.

### E16-S5 — Rebaseliner permissions et architecture `[TERMINÉ]`

En tant qu'équipe technique, je veux une architecture et une matrice d'accès cohérentes afin d'éviter
toute autorisation héritée de l'ancien cadrage.

Critères d'acceptation :

- Architecture, UX, permissions et modèle conceptuel reflètent le PRD canonique.
- Les droits owner-only sont imposés côté serveur.
- Les routes directes non autorisées échouent sans fuite d'information.
- Les décisions encore ouvertes sont isolées et ne sont pas codées implicitement.
- Les tests de non-régression E1–E15 restent verts ou leurs changements sont documentés.

Taille : L.

## E17 — Trois routes d'onboarding et activation contrôlée

Objectif : permettre à un client, un entrepreneur ou PIVOT d'initier le dossier tout en laissant au client
la confirmation de l'ownership et de l'activation.

### E17-S1 — Implémenter le parcours client-led `[TERMINÉ]`

En tant que client, je veux créer mon projet et inviter l'entrepreneur afin de démarrer directement mon
dossier PIVOT.

Critères d'acceptation :

- Le client crée le projet, confirme son ownership et renseigne les conditions initiales.
- Il invite l'entrepreneur, puis les autres acteurs autorisés.
- L'avancement de l'onboarding et les éléments manquants sont visibles.
- L'activation respecte le gate commun et est auditée.

Taille : L.

### E17-S2 — Implémenter le parcours contractor-led `[TERMINÉ]`

En tant qu'entrepreneur, je veux préparer un workspace préliminaire afin d'inviter le propriétaire sans
m'attribuer ses droits.

Critères d'acceptation :

- Le workspace reste explicitement préliminaire avant confirmation client.
- L'entrepreneur invite un client par un lien sécurisé et expirant.
- Le client confirme projet, ownership, entrepreneur et conditions.
- Les finances restent verrouillées avant activation.

Taille : XL.

### E17-S3 — Implémenter le parcours PIVOT-led `[TERMINÉ]`

En tant qu'agent PIVOT, je veux préparer un onboarding concierge afin d'accompagner les premiers
propriétaires sans usurper leur autorité.

Critères d'acceptation :

- PIVOT peut préparer budget, jalons, documents et invitations.
- Le client doit confirmer lui-même l'ownership et les conditions.
- Chaque intervention PIVOT est visible et auditée.
- Le projet indique sa route d'acquisition pour les KPI.

Taille : L.

### E17-S4 — Confirmer les acteurs et conditions `[TERMINÉ]`

En tant que client, je veux confirmer les acteurs et conditions afin de savoir qui exécute, contrôle et
décide.

Critères d'acceptation :

- L'entrepreneur et l'ingénieur acceptent leur participation.
- Budget, devise, conditions financières et autorité sont versionnés.
- Un refus ou une expiration ne produit pas un projet actif.
- Toute nouvelle version importante exige une nouvelle confirmation ciblée.

Taille : L.

### E17-S5 — Appliquer le gate d'activation `[TERMINÉ]`

En tant que propriétaire, je veux une activation contrôlée afin qu'aucune dépense ne soit demandée sur
un dossier incomplet.

Critères d'acceptation :

- Le gate vérifie owner, budget, conditions, autorité et acteurs requis.
- Les contributions préliminaires autorisées sont clairement distinguées des fonctions actives.
- Les demandes et paiements sont bloqués côté serveur avant activation.
- L'activation est atomique, idempotente et auditée.

Taille : L.

### E17-S6 — Tester les conflits d'onboarding `[TERMINÉ]`

En tant qu'exploitant, je veux gérer doublons et conflits afin qu'un projet réel ne possède pas plusieurs
dossiers concurrents non maîtrisés.

Critères d'acceptation :

- Les invitations expirées, révoquées et déjà acceptées sont couvertes.
- Les doublons probables sont signalés sans fusion automatique destructive.
- Les conflits d'ownership passent par une revue PIVOT.
- Les trois routes sont testées pour chaque résultat d'activation.

Taille : M.

## E18 — Capture terrain mobile-first et registre de preuves

Objectif : transformer les médias et documents en preuves structurées, attribuées, versionnées et
exploitables dans la chaîne de confiance.

### E18-S1 — Modéliser le registre de preuves `[TERMINÉ]`

En tant qu'auditeur, je veux un enregistrement commun des preuves afin de retracer leur origine et leur
usage.

Critères d'acceptation :

- Les types couvrent photo, vidéo, facture, devis, bon de livraison, compte rendu et inspection.
- Chaque preuve référence projet, auteur, étape, demande éventuelle, statut et version.
- Les fichiers existants sont conservés et rattachables au registre.
- Les contraintes empêchent les associations inter-organisations.

Taille : XL.

### E18-S2 — Capturer photos, vidéos et documents terrain `[TERMINÉ]`

En tant que responsable de chantier, je veux déposer rapidement les preuves afin de documenter la
réalité au moment où elle se produit.

Critères d'acceptation :

- L'interface mobile permet type, fichier, étape et description.
- Formats, tailles et contenus sont validés côté serveur.
- La progression d'envoi, le succès et l'erreur sont visibles.
- Les vidéos disposent d'un aperçu ou d'une représentation sûre.

Taille : L.

### E18-S3 — Capturer les métadonnées consenties `[TERMINÉ]`

En tant que propriétaire, je veux connaître le contexte d'une preuve afin d'évaluer sa fiabilité.

Critères d'acceptation :

- Auteur et horodatage serveur sont obligatoires.
- La géolocalisation est demandée uniquement au dépôt et avec consentement.
- L'absence, le refus ou l'imprécision sont enregistrés sans bloquer arbitrairement le dépôt.
- L'accès aux coordonnées respecte les permissions du projet.

Taille : L.

### E18-S4 — Versionner et rendre immuable après validation `[TERMINÉ]`

En tant qu'exploitant, je veux préserver les preuves validées afin que l'historique ne puisse être
réécrit.

Critères d'acceptation :

- Une preuve validée ne peut être écrasée ni supprimée par un utilisateur.
- Une correction crée une nouvelle version avec motif et lien vers l'original.
- Les corrections administratives exceptionnelles sont auditables et non destructives.
- Les aperçus et rapports indiquent la version utilisée.

Taille : XL.

### E18-S5 — Optimiser l'expérience terrain `[TERMINÉ]`

En tant que responsable de chantier, je veux une interface rapide sur téléphone afin de contribuer même
dans des conditions de terrain difficiles.

Critères d'acceptation :

- Les actions prioritaires sont utilisables sur petit écran et connexion lente.
- La compression d'aperçu ne modifie pas le fichier original conservé.
- Les erreurs permettent une reprise sûre sans doublon.
- L'accessibilité clavier et les états de chargement sont testés.

Taille : L.

### E18-S6 — Contrôler l'accès aux preuves `[TERMINÉ]`

En tant que responsable sécurité, je veux une politique de preuve explicite afin de protéger les données
du chantier.

Critères d'acceptation :

- Aperçu, téléchargement et export partagent les mêmes contrôles serveur.
- Les URL de fichiers ne permettent aucun accès transversal.
- L'audit indique les validations et corrections sensibles.

Taille : M.

## E19 — Demandes de dépense et autorité financière client

Objectif : séparer demande, avis, vérification, autorisation et exécution MeSomb afin que seul le client
propriétaire décide de la dépense.

### E19-S1 — Modéliser la demande de dépense `[TERMINÉ]`

En tant qu'entrepreneur, je veux soumettre une demande structurée afin de justifier un besoin financier.

Critères d'acceptation :

- La demande contient montant, devise, objet, bénéficiaire, jalon, échéance et auteur.
- Son cycle couvre brouillon, soumis, en preuve, en revue, vérifié, autorisé, refusé et clos.
- Les transitions sont atomiques, autorisées et auditables.
- Une demande ne constitue jamais automatiquement un paiement.

Taille : XL.

### E19-S2 — Attacher les justificatifs `[TERMINÉ]`

En tant qu'entrepreneur, je veux joindre les pièces nécessaires afin que les contrôleurs disposent du
dossier complet.

Critères d'acceptation :

- Factures, devis, bons et preuves terrain peuvent être liés à la demande.
- Les pièces obligatoires dépendent du type et du montant.
- Une pièce rejetée ou remplacée conserve son historique.
- Le dossier indique clairement les éléments manquants.

Taille : L.

### E19-S3 — Ajouter l'évidence terrain et l'avis technique `[TERMINÉ]`

En tant que client, je veux recevoir la réalité terrain et l'avis de l'ingénieur avant de décider.

Critères d'acceptation :

- Le responsable associe livraisons, travaux et progression à la demande.
- L'ingénieur rend un avis approuvé, conditionnel ou rejeté avec motif.
- L'avis ne vaut pas autorisation financière.
- Toute modification substantielle renvoie le dossier au bon niveau de revue.

Taille : L.

### E19-S4 — Appliquer la vérification PIVOT `[TERMINÉ]`

En tant que gouvernance PIVOT, je veux contrôler les dossiers à risque afin de protéger le propriétaire.

Critères d'acceptation :

- Les règles de risque déterminent si une vérification PIVOT est obligatoire.
- Le vérificateur consulte le dossier complet et motive sa décision.
- Un dossier incomplet ou incohérent ne peut atteindre l'autorisation.
- Les interventions exceptionnelles sont confirmées et auditées.

Taille : L.

### E19-S5 — Autoriser uniquement par le client `[TERMINÉ]`

En tant que client propriétaire, je veux être le seul décideur final afin de garder le contrôle de mon
argent.

Critères d'acceptation :

- Seul le rôle projet owner autorisé voit et exécute approuver/refuser.
- La décision exige la version exacte du dossier et un contrôle anti-concurrence.
- Le refus exige un motif et notifie les acteurs concernés.
- Aucun ingénieur, entrepreneur ou agent PIVOT ne peut contourner cette règle.

Taille : XL.

### E19-S6 — Exécuter avec MeSomb `[TERMINÉ]`

En tant que client, je veux exécuter un paiement autorisé avec MeSomb afin que la transaction reste liée
à la décision.

Critères d'acceptation :

- MeSomb n'est appelé qu'après autorisation owner valide.
- Le montant et le bénéficiaire proviennent de la version autorisée côté Django.
- Idempotence, mode asynchrone, statuts, timeout et rapprochement sont appliqués.
- Un état incertain bloque une seconde tentative sans activer la comptabilisation.
- Les références PIVOT, MeSomb et opérateur sont conservées distinctement.

Taille : XL.

### E19-S7 — Auditer et notifier le cycle financier `[TERMINÉ]`

En tant que propriétaire, je veux comprendre chaque étape de la décision et du paiement afin de pouvoir
la justifier.

Critères d'acceptation :

- Chaque transition indique acteur, date, motif et version du dossier.
- Les notifications ciblent uniquement les acteurs concernés.
- Les logs ne contiennent ni clé ni téléphone complet.
- Les rapports distinguent demande, autorisation, tentative et succès comptabilisé.

Taille : L.

## E20 — Revue technique et vérification à trois niveaux

Objectif : distinguer déclaration, avis technique, vérification numérique et inspection physique.

### E20-S1 — Séparer progression déclarée et vérifiée `[TERMINÉ]`

Critères d'acceptation : les deux valeurs, leurs auteurs, dates et preuves sont distincts ; les tableaux de
bord n'affichent jamais l'une comme l'autre ; les calculs et rapports indiquent leur source.

### E20-S2 — Gérer les décisions techniques `[TERMINÉ]`

Critères d'acceptation : l'ingénieur peut approuver, approuver sous conditions ou rejeter ; un motif et
les actions correctives sont conservés ; une nouvelle preuve peut ouvrir une nouvelle revue.

### E20-S3 — Implémenter Digital Verified `[TERMINÉ]`

Critères d'acceptation : PIVOT contrôle présence, chronologie, acteurs et cohérence documentaire ; le
résultat référence les éléments examinés ; un échec bloque les décisions qui l'exigent.

### E20-S4 — Implémenter Technically Verified `[TERMINÉ]`

Critères d'acceptation : seul l'ingénieur affecté ou un remplaçant autorisé rend l'avis ; quantités,
progression et réserves sont structurées ; la signature logique est auditée.

### E20-S5 — Implémenter PIVOT Site Verified `[TERMINÉ]`

Critères d'acceptation : l'inspection conserve inspecteur, date, localisation, checklist, preuves,
réserves et résultat ; elle ne peut être déclarée sans visite enregistrée.

### E20-S6 — Configurer les règles de risque `[TERMINÉ]`

Critères d'acceptation : les jalons critiques — fondations, ferraillage, structure et toiture — peuvent
imposer une inspection ; une anomalie de progression peut également l'imposer ; aucune dérogation ne
permet de contourner une inspection obligatoire.

### E20-S7 — Produire les rapports de vérification `[TERMINÉ]`

Critères d'acceptation : le PDF distingue les trois niveaux, liste preuves et réserves, porte une référence
unique et applique les permissions du projet.

## E21 — Rapprochement matières, dépenses et progression

Objectif : détecter avant autorisation les écarts entre achats, livraisons, stock, consommation et travaux.

### E21-S1 — Distinguer acheté, livré, consommé et restant `[TERMINÉ]`

Critères d'acceptation : chaque quantité possède sa source et son unité ; les conversions sont explicites ;
le stock restant est dérivé de mouvements traçables.

### E21-S2 — Relier pièces, stock et jalons `[TERMINÉ]`

Critères d'acceptation : factures, bons, mouvements et étapes sont reliés sans duplication ; les liens
inter-projets sont interdits ; les éléments non rapprochés restent visibles.

### E21-S3 — Configurer les plages attendues `[TERMINÉ]`

Critères d'acceptation : l'ingénieur peut définir ou sélectionner une plage versionnée ; la règle indique
unité, ouvrage et hypothèses ; elle assiste sans décider automatiquement.

### E21-S4 — Détecter les anomalies avant paiement `[TERMINÉ]`

Critères d'acceptation : un écart significatif crée une anomalie ; la demande concernée est signalée ou
bloquée selon la règle ; aucune anomalie n'est effacée par simple modification de source.

### E21-S5 — Résoudre les anomalies `[TERMINÉ]`

Critères d'acceptation : un responsable, des preuves et un motif sont requis ; l'ingénieur ou PIVOT valide
la résolution selon le type ; la chronologie complète reste consultable.

### E21-S6 — Afficher les indicateurs de valeur contrôlée `[TERMINÉ]`

Critères d'acceptation : PIVOT calcule dépenses vérifiées, jalons vérifiés, écarts et délais depuis des
données auditables ; les agrégats respectent les permissions et sont testés.

## E22 — Control room pilote et onboarding concierge

Objectif : exploiter 10 à 20 projets de qualité, accompagner chaque acteur et mesurer si la couche de
confiance produit de l'adoption et des recommandations.

### E22-S1 — Superviser les routes et activations `[TERMINÉ]`

Critères d'acceptation : le control room filtre par route, état, ville et blocage ; les actions possibles
sont contrôlées ; chaque intervention PIVOT est auditée.

### E22-S2 — Mesurer adoption et conversion `[TERMINÉ]`

Critères d'acceptation : projets actifs, routes, invitations et conversion contractor→client sont calculés
selon des définitions uniques ; les périodes sont filtrables.

### E22-S3 — Mesurer confiance et valeur contrôlée `[TERMINÉ]`

Critères d'acceptation : valeur suivie, dépenses vérifiées, jalons, anomalies et délais sont visibles ; les
sources sont explicables ; les métriques ne mélangent pas statuts en attente et confirmés.

### E22-S4 — Outiller l'onboarding concierge `[TERMINÉ]`

Critères d'acceptation : checklist budget/jalons/documents/invitations/formation ; propriétaire et agent
PIVOT identifiés ; frictions et actions suivantes suivies jusqu'à activation.

### E22-S5 — Gérer les contestations `[TERMINÉ]`

Critères d'acceptation : une contestation référence l'objet, gèle la décision lorsque requis, accepte les
observations contradictoires et reçoit une résolution motivée sans suppression de preuve.

### E22-S6 — Suivre rétention, recommandation et économie `[TERMINÉ]`

Critères d'acceptation : rétention client/entrepreneur, recommandation, MRR et hypothèses de pricing sont
mesurables ; les définitions et limites du pilote sont documentées.

## Décisions de rebaseline validées

- Le produit s'appelle PIVOT ; « BLUEPRINT » est seulement le document stratégique.
- Le client est le propriétaire du chantier et l'autorité financière finale.
- MeSomb est conservé pour les paiements autorisés et les abonnements.
- L'entrepreneur, le responsable de chantier, l'ingénieur et PIVOT ont des frontières distinctes.
- Aucun paiement chantier ne précède l'autorisation du client.
- Les capacités existantes E1–E15 sont conservées, mais peuvent être adaptées ou placées derrière un
  feature flag lorsqu'elles contredisent le PRD E16+.

## Traçabilité synthétique

| Exigences | Epics |
|---|---|
| AUTH-01…09 | E2 |
| PROJ-01…08 | E3 |
| PLAN-01…08 | E4 |
| STOCK-01…09 | E5 |
| COLLAB-01…08 | E6 |
| FIN-01…10 | E7 |
| REPORT-01…05 | E8 |
| ADMIN-01…04 | E2, E9 |
| I18N, cohérence UX, notifications, responsive, accessibilité | E10 |
| Supervision globale, organisations, utilisateurs, validations et paramètres plateforme | E11 |
| Création, modification, archivage, transfert, intervention et modales de confirmation | E12 |
| Assistant OpenRouter, contexte des modèles Django, interface flottante, permissions IA et lecture seule | E13 |
| Routage sémantique, questions naturelles, sélection multi-domaines et réponses garanties par rôle | E14 |
| Pricing, essais, abonnements, quotas, facturation et restrictions en cas d’impayé | E15 |
| Autorité client, ownership, rôles projet et migration | E16 |
| Onboarding client-led, contractor-led, PIVOT-led et activation | E17 |
| Preuves terrain, métadonnées, versions, immutabilité et mobile | E18 |
| Demandes de dépense, autorisation client et exécution MeSomb | E19 |
| Progression déclarée/vérifiée et trois niveaux de vérification | E20 |
| Achats, livraisons, consommation, stock et anomalies | E21 |
| Control room, onboarding concierge et KPI du pilote | E22 |
 | Sécurité, intégrité, UX, exploitabilité | E1, E2, E9 et critères transversaux de chaque epic |

## Définition de « terminé » pour une story

- Critères d'acceptation démontrés.
- Tests pertinents ajoutés et tous les tests réussissent.
- Permissions et isolation d'organisation testées.
- Migrations incluses lorsqu'un modèle change.
- Interface responsive et erreurs de formulaire traitées.
- Aucune donnée sensible dans les journaux ou le dépôt.
- Documentation utile mise à jour.
