# PIVOT-SASS — Plan du Sprint 1

Statut : **TERMINÉ — 6 stories validées**  
Statut de préparation suivant : **PASS**, avec préoccupations différées pour les epics financiers et production  
Objectif : obtenir un socle Django exécutable avec SQLite3, une interface de base, les tests et le modèle initial organisation/utilisateur.

## Périmètre engagé

1. `E1-S1` — Initialiser le projet Django.
2. `E1-S2` — Installer la structure modulaire.
3. `E1-S3` — Créer le gabarit d'interface.
4. `E1-S4` — Établir la stratégie de tests.
5. `E1-S5` — Configurer les contrôles de qualité.
6. `E2-S1` — Modéliser l'organisation et l'utilisateur personnalisé.

## Résultat démontrable

À la fin du sprint :

- le projet se lance localement avec SQLite3 ;
- les applications Django sont structurées ;
- la page d'accueil technique et le gabarit responsive s'affichent ;
- l'utilisateur personnalisé et l'organisation possèdent leurs premières migrations ;
- deux organisations de test démontrent l'isolation des données de base ;
- les commandes de vérification et de tests passent.

## Ordre d'exécution

| Ordre | Story | Dépendance | Statut initial |
|---:|---|---|---|
| 1 | E1-S1 | — | done |
| 2 | E1-S2 | E1-S1 | done |
| 3 | E1-S4 | E1-S1 | done |
| 4 | E1-S5 | E1-S1, E1-S4 | done |
| 5 | E1-S3 | E1-S1, E1-S2 | done |
| 6 | E2-S1 | E1-S1, E1-S2, E1-S4 | done |

## Risques et réponses

| Risque | Réponse dans le sprint |
|---|---|
| Modèle utilisateur ajouté trop tard | E2-S1 est réalisé avant tout autre modèle métier |
| Installation BMAD partielle | Les artefacts locaux servent de contrat ; aucune dépendance d'exécution à BMAD |
| SQLite utilisé comme hypothèse permanente | Interdiction du SQL spécifique et migrations Django obligatoires |
| Isolation d'organisation oubliée | Tests avec deux organisations dès E2-S1 |
| UI surdimensionnée trop tôt | Gabarit et composants essentiels seulement |

## Questions non bloquantes pour ce sprint

- facturation des abonnements ;
- workflow définitif des retraits ;
- opérateurs MeSomb et remboursements ;
- format final du rapport hebdomadaire ;
- migration des données de l'ancien PIVOT.

## Gate de préparation

- SPEC disponible : oui.
- UX disponible : oui.
- Architecture disponible : oui.
- Stories traçables : oui.
- Dépendances du Sprint 1 identifiées : oui.
- Choix de base initiale : SQLite3, validé.
- Questions bloquant le Sprint 1 : aucune.
- Verdict : **PASS**.

## Résultat de clôture

- Les 6 stories engagées sont terminées.
- Django utilise `pivot.sqlite3` avec les migrations natives et les migrations `organizations`/`accounts`.
- Les 10 modules sont déclarés.
- Le gabarit responsive et les pages système sont disponibles.
- Les contrôles Django, migrations, formatage, lint et 9 tests réussissent.

## Prochaine action

Préparer et exécuter `E2-S2` pour l'authentification et la déconnexion avec le modèle utilisateur personnalisé.
