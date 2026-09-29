# PIVOT-SASS — Change Proposal BLUEPRINT

Statut : **TRAJECTOIRE APPROUVÉE — E16-S1 terminé, décisions ciblées encore requises**  
Date : 2026-09-04  
Déclencheur : `BLUEPRINT — Product Access, Trust Architecture & Go-to-Market Strategy`  
Classification : **changement majeur de produit, sans réécriture complète recommandée**

## 1. Résumé exécutif

Le produit implémenté est aujourd'hui un SaaS de gestion de chantier centré sur l'organisation de
l'ingénieur. Le blueprint définit un produit différent dans son autorité métier : une infrastructure de
confiance centrée sur le **client, qui est le Project Owner**, où le créateur du lead n'est pas nécessairement le
propriétaire du projet, où les dépenses sont autorisées uniquement par le propriétaire, et où PIVOT
exerce une fonction de vérification et de gouvernance.

La correction recommandée est une **rebase fonctionnelle additive** : conserver le socle Django et les
modules déjà utiles, introduire les rôles et workflows BLUEPRINT par migrations compatibles, puis
désactiver du MVP les fonctions qui contredisent la stratégie de lancement. Une réécriture ferait perdre
des composants déjà alignés (audit, stock, preuves, rapports, permissions, administration) sans résoudre
plus vite le changement d'autorité.

## 2. Changement déclencheur

Le blueprint introduit les invariants suivants :

1. Le propriétaire du projet est l'autorité ultime, indépendamment de l'acteur qui crée le lead.
2. Trois routes d'accès coexistent : client-led, contractor-led et PIVOT-led.
3. Le contractor devient un rôle métier et un canal d'acquisition, distinct de l'ingénieur.
4. L'activation d'un projet exige la confirmation du propriétaire.
5. Le contractor soumet une demande de paiement ; seul le propriétaire l'autorise.
6. Les preuves terrain précèdent la revue technique, la vérification PIVOT et l'autorisation financière.
7. Les données validées ne sont supprimées par aucun utilisateur ; elles sont versionnées ou compensées.
8. Le MVP privilégie la couche de confiance. L'intégration de paiement, l'IA avancée, les fournisseurs,
   le financement et le BIM appartiennent à la Phase 2.
9. Le lancement vise 10 à 20 projets à forte qualité avec onboarding concierge et mesure des KPI de
   confiance et d'acquisition.

## 3. Analyse d'écart

| Domaine | État actuel | Cible BLUEPRINT | Impact |
|---|---|---|---|
| Autorité projet | Ingénieur propriétaire opérationnel | Project Owner autorité finale | Critique |
| Rôles | Ingénieur, client, responsable, admin | Client/Owner, contractor, site manager, engineer, PIVOT | Critique |
| Création | Principalement engineer-led | Trois routes avec ownership confirmé | Critique |
| Activation | Projet utilisable après création | Confirmation owner + conditions | Élevé |
| Finances | Client initie directement un paiement MeSomb | Contractor demande, preuves/revues, owner autorise | Critique |
| Validation | Document puis ingénieur/super-admin | Preuve → ingénieur → PIVOT → owner | Élevé |
| Stock | Quantité et mouvements traçables | Acheté/livré/utilisé/restant réconciliés | Élevé |
| Progression | Statut d'étape dérivé | Déclaré vs vérifié avec approbation conditionnelle | Élevé |
| Preuves | Photos, PDF, commentaires | Mobile-first, vidéo, horodatage, identité, géolocalisation | Élevé |
| Immutabilité | Certaines suppressions contrôlées existent | Aucune suppression de donnée validée | Élevé |
| Abonnement | E15 et MeSomb actifs | MeSomb conservé pour abonnements et paiements autorisés | Moyen/stratégique |
| IA | Assistant avancé déjà livré | Advanced AI Phase 2 | Moyen |
| Pilotage | Super-admin opérationnel | Control room avec KPI trust/GTM | Élevé |
| Sprint plan | Toujours Sprint 1 | Produit rendu jusqu'à E15 | Critique documentaire |

## 4. Artefacts affectés

### SPEC / PRD

La SPEC 0.2 ne peut plus servir de contrat courant. Les sections acteurs, autorisations, projets,
finances, validations, données, critères de succès et hors périmètre doivent être réécrites. La phrase
« l'ingénieur est le propriétaire opérationnel » doit être remplacée par une séparation explicite entre
ownership juridique/financier, exécution, revue technique et gouvernance PIVOT.

### Architecture

L'architecture reste exploitable, mais son modèle doit évoluer :

- rôle global d'utilisateur séparé du rôle contextuel dans un projet ;
- `ProjectOwnership` ou relation équivalente avec confirmation et historique ;
- `ProjectLead` / onboarding route / état d'activation ;
- rôle projet `OWNER`, `CONTRACTOR`, `SITE_MANAGER`, `ENGINEER`, `PIVOT_REVIEWER` ;
- `ExpenseRequest` et chaîne d'approbation séparées de `PaymentTransaction` ;
- `EvidenceRecord`, métadonnées de capture et versions immuables ;
- progression déclarée, progression vérifiée et décision conditionnelle ;
- niveaux de vérification digital, technique et visite PIVOT ;
- rapprochement matières et anomalies ;
- événements d'audit append-only pour les données validées.

### UX

Les tableaux de bord doivent être redessinés par responsabilité et non seulement par compte global.
L'owner doit voir en priorité décisions en attente, budget, preuves et écarts. Le contractor doit voir
exécution et demandes. Le site manager doit disposer d'une capture mobile rapide. L'ingénieur doit avoir
une file de revue. PIVOT doit disposer d'une file de vérification et d'un control room pilote.

### Backlog et sprint

E1 à E15 restent dans l'historique, mais leur statut « terminé » signifie seulement « livré selon
l'ancien cadrage ». Les fonctionnalités incompatibles ne doivent pas être considérées comme validées
pour BLUEPRINT. Le Sprint Plan 1 doit être archivé et remplacé par un plan de transition.

## 5. Décision de trajectoire recommandée

### Conserver

- Django, SQLite3 pour le développement et la trajectoire PostgreSQL ;
- isolation par organisation et contrôles serveur ;
- projets, invitations, étapes, calendrier, stocks et mouvements ;
- documents, photos, commentaires, rapports PDF et exports ;
- journal d'audit, super-administration, notifications et e-mails ;
- responsive, multilingue et système de design PIVOT ;
- adaptateur MeSomb et abonnement, avec exécution conditionnée par les autorisations métier.

### Modifier

- ownership et rôles projet ;
- onboarding et activation ;
- permissions financières ;
- validation des preuves et progression ;
- politique de suppression après validation ;
- tableaux de bord et métriques ;
- PRD, architecture, UX, backlog et sprint plan.

### Geler ou reporter

- aucune exécution MeSomb avant la fin complète du circuit de demande et l'autorisation du client/owner ;
- assistant IA comme argument central de lancement ;
- automatisations prédictives ;
- marketplace, fournisseurs, financement, assurance et BIM.

Les modules peuvent rester dans le code derrière des flags afin d'éviter une suppression destructive et
de préserver la Phase 2.

## 6. Backlog correctif proposé

## E16 — Rebaseliner le produit et l'autorité projet

- **E16-S1** — Mettre à jour le PRD/SPEC avec la proposition de valeur BLUEPRINT.
- **E16-S2** — Séparer rôle de compte, rôle projet et autorité propriétaire.
- **E16-S3** — Modéliser ownership, confirmation, conditions et historique.
- **E16-S4** — Migrer les projets existants avec une règle explicite et réversible.
- **E16-S5** — Mettre à jour la matrice de permissions et ses tests.

## E17 — Trois routes d'onboarding et activation contrôlée

- **E17-S1** — Implémenter la route owner-led.
- **E17-S2** — Implémenter le workspace préliminaire contractor-led.
- **E17-S3** — Implémenter l'onboarding concierge PIVOT-led.
- **E17-S4** — Confirmer owner, contractor, conditions et autorité financière.
- **E17-S5** — Verrouiller les workflows financiers avant activation.
- **E17-S6** — Tester invitations, expirations, doublons et conflits d'ownership.

## E18 — Capture terrain mobile-first et registre de preuves

- **E18-S1** — Modéliser un registre de preuves typé et append-only.
- **E18-S2** — Capturer photos, vidéos, factures et bons de livraison.
- **E18-S3** — Enregistrer horodatage, auteur et géolocalisation consentie.
- **E18-S4** — Versionner toute correction sans écraser la preuve validée.
- **E18-S5** — Livrer une interface terrain mobile rapide et résiliente.
- **E18-S6** — Encadrer confidentialité, rétention et téléchargement.

## E19 — Demandes de dépense et autorité financière owner-only

- **E19-S1** — Modéliser les demandes de dépense du contractor.
- **E19-S2** — Exiger pièces, montant, objet et jalon concernés.
- **E19-S3** — Attacher l'avis du site manager et la revue ingénieur.
- **E19-S4** — Ajouter la vérification PIVOT selon le niveau de risque.
- **E19-S5** — Réserver l'autorisation finale au client, qui est le Project Owner.
- **E19-S6** — Conserver décisions, motifs, versions et délais dans l'audit.
- **E19-S7** — Exécuter avec MeSomb uniquement après autorisation finale du client/owner, avec idempotence, rapprochement et audit.

## E20 — Revue technique et vérification à trois niveaux

- **E20-S1** — Séparer progression déclarée et progression vérifiée.
- **E20-S2** — Permettre approbation, approbation conditionnelle et rejet motivé.
- **E20-S3** — Implémenter BLUEPRINT Digital Verified.
- **E20-S4** — Implémenter Technically Verified par l'ingénieur.
- **E20-S5** — Implémenter PIVOT Site Verified avec inspection physique.
- **E20-S6** — Configurer les jalons nécessitant une inspection selon le risque.
- **E20-S7** — Produire certificats et rapports de vérification traçables.

## E21 — Rapprochement matières, dépenses et progression

- **E21-S1** — Distinguer acheté, livré, consommé et restant.
- **E21-S2** — Rapprocher factures, bons, mouvements de stock et jalons.
- **E21-S3** — Configurer les plages de consommation attendues.
- **E21-S4** — Signaler les écarts avant autorisation financière.
- **E21-S5** — Fournir une file d'investigation et une résolution auditée.
- **E21-S6** — Ajouter les indicateurs de valeur contrôlée.

## E22 — Control room pilote et exploitation concierge

- **E22-S1** — Suivre projets owner-led, contractor-led et PIVOT-led.
- **E22-S2** — Mesurer activation, conversion contractor→owner et délais d'approbation.
- **E22-S3** — Mesurer valeur suivie, dépenses vérifiées, jalons vérifiés et anomalies.
- **E22-S4** — Outiller l'onboarding concierge des 10 à 20 premiers projets.
- **E22-S5** — Gérer les disputes par dossier formel et chronologie immuable.
- **E22-S6** — Suivre rétention, recommandations, MRR et hypothèses de pricing.
- **E22-S7** — Exporter le dossier pilote pour analyse des 30/60/90 jours.

## 7. Ordre de transition proposé

1. **Gate A — décision produit** : valider terminologie, ownership, acteur payeur et statut du paiement
   intégré dans le pilote.
2. **Sprint T1 — E16** : PRD, architecture, modèles d'autorité et migration.
3. **Sprint T2 — E17** : trois onboardings et activation.
4. **Sprint T3 — E18 + début E20** : preuve mobile et revue technique.
5. **Sprint T4 — E19 + fin E20** : chaîne de décision financière et vérification.
6. **Sprint T5 — E21** : rapprochement et anomalies.
7. **Sprint T6 — E22** : pilotage concierge et lancement contrôlé.

E15 et l'assistant IA restent maintenus mais ne doivent pas retarder ces sprints.

## 8. Risques et mesures

| Risque | Mesure |
|---|---|
| Confondre `client` actuel et Project Owner | Migration explicite, revue manuelle des projets existants |
| Donner au contractor trop de visibilité financière | Permissions projet need-to-know et tests négatifs |
| Perdre l'historique lors du changement de modèle | Migrations additives, audit et aucun renommage destructif initial |
| Surconstruire avant le pilote | Feature flags et priorité stricte E16–E20 |
| Géolocalisation intrusive | Consentement, précision/rétention configurables et politique documentée |
| Fausse immutabilité | Append-only après validation et corrections compensatoires |
| Mélanger autorisation et exécution de paiement | `ExpenseRequest` distinct de `PaymentTransaction` |
| Documents BMAD contradictoires | Rebaseliner SPEC, architecture, UX, backlog et sprint dans le même gate |

## 9. Décisions bloquantes

1. **DÉCIDÉ** — Le produit conserve le nom public **PIVOT**. « BLUEPRINT » désigne uniquement le
   document stratégique à l'origine de cette correction de trajectoire et ne devient pas une marque
   affichée dans l'application.
2. **DÉCIDÉ** — Le rôle `client` représente le Project Owner. Les projets existants devront être migrés
   en préservant cette autorité, avec signalement des projets qui ont plusieurs clients.
3. Un projet peut-il avoir plusieurs propriétaires avec un seul décideur financier ?
4. Le contractor est-il une organisation, un utilisateur, ou les deux selon le cas ?
5. Qui choisit et rémunère l'ingénieur selon chaque type de projet ?
6. Quels jalons imposent une inspection physique au pilote ?
7. **DÉCIDÉ** — MeSomb est conservé. Pour les dépenses chantier, son exécution intervient seulement
   après autorisation finale du client/owner. Les paiements d'abonnement restent séparés.
8. Quelles métadonnées de géolocalisation sont légalement et opérationnellement acceptables ?
9. Quelle règle de résolution s'applique lorsqu'un owner conteste une preuve ou une vérification PIVOT ?

## 10. Critères d'acceptation de la correction de trajectoire

- Le PRD, l'architecture, l'UX, le backlog et le sprint plan décrivent le même produit.
- Aucun acteur autre que le client/Project Owner ne peut autoriser une dépense.
- Les trois routes produisent un projet dont l'ownership est explicitement confirmé.
- Une preuve validée ne peut être supprimée ni écrasée.
- Une demande de dépense conserve toute la chaîne preuve, revue, vérification et décision.
- Les vues financières du contractor respectent le besoin contractuel minimal.
- Les KPI du pilote sont calculables depuis des événements auditables.
- Les fonctions Phase 2 ne bloquent ni l'activation ni le lancement des 10 à 20 projets pilotes.

## 11. Recommandation de décision

**Approuver avec conditions**, puis démarrer par E16-S1 et E16-S2. Ne pas poursuivre de nouvelles
fonctionnalités E15/IA avant la rebase documentaire et la définition de l'ownership. Ne pas supprimer le
code existant : isoler les fonctions Phase 2 derrière des feature flags jusqu'à validation du pilote.
