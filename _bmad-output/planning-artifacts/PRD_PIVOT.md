# PIVOT — Product Requirements Document

Version : **1.0 — rebaseline stratégique**  
Date : **2026-09-04**  
Statut : **Référence produit canonique pour la trajectoire E16+**  
Source stratégique : `BLUEPRINT — Product Access, Trust Architecture & Go-to-Market Strategy`  
Produit : **PIVOT**

## 1. Vision

PIVOT est une plateforme de confiance pour les projets de construction, particulièrement adaptée aux
propriétaires qui pilotent leur chantier à distance. Elle réunit dans un dossier projet traçable les
acteurs, budgets, demandes de dépense, preuves terrain, livraisons, stocks, travaux, validations et
décisions.

La promesse de PIVOT est : **savoir où va l'argent et savoir ce qui a réellement été construit**.

PIVOT ne remplace ni le contrat de construction, ni le jugement professionnel de l'ingénieur, ni
l'autorité du propriétaire. La plateforme structure les informations, impose les frontières d'accès,
rend les décisions vérifiables et conserve leur historique.

## 2. Problème

Un propriétaire à distance reçoit souvent des informations fragmentées : messages WhatsApp, photos
isolées, factures, appels et demandes de transfert. Il lui est difficile de relier avec certitude :

- ce qui a été acheté ;
- ce qui a été livré ;
- ce qui a été consommé ;
- ce qui a été construit ;
- ce qui a été vérifié ;
- ce qui justifie la prochaine dépense.

Cette fragmentation crée une dépendance à la confiance aveugle. PIVOT doit transformer ces éléments en
un dossier cohérent, horodaté, attribué et auditable avant l'autorisation financière.

## 3. Principes non négociables

1. Le **client est le propriétaire du chantier** et l'autorité finale du projet.
2. La personne ou l'organisation qui crée le lead ne devient pas automatiquement propriétaire.
3. Seul le client/propriétaire peut autoriser une demande de paiement chantier.
4. MeSomb est conservé pour exécuter les paiements autorisés et les paiements d'abonnement.
5. Autoriser une dépense et exécuter un paiement sont deux opérations distinctes.
6. Toute décision sensible est contrôlée côté Django, jamais seulement par l'interface.
7. Une donnée validée n'est ni écrasée ni supprimée ; une correction crée une version ou une écriture
   compensatoire.
8. Chaque preuve et décision indique au minimum qui, quoi et quand ; un motif est exigé lorsque la
   décision ou la correction le nécessite.
9. Les organisations et projets restent strictement isolés.
10. Le MVP doit prouver la confiance sur 10 à 20 projets avant d'élargir l'écosystème.

## 4. Acteurs

### 4.1 Client / Project Owner

Le client est le propriétaire du chantier. Il :

- confirme le projet et son statut de propriétaire ;
- confirme l'entrepreneur et les conditions initiales ;
- consulte toutes les informations financières autorisées de son projet ;
- examine preuves, avis techniques, vérifications et anomalies ;
- approuve ou refuse les demandes de dépense ;
- déclenche ou confirme l'exécution MeSomb lorsqu'elle est disponible ;
- ouvre une contestation et suit sa résolution ;
- ne peut supprimer une preuve ou décision déjà validée.

### 4.2 Entrepreneur / Contractor

L'entrepreneur exécute les travaux et organise son équipe. Il :

- peut préparer un workspace préliminaire ;
- invite le client à confirmer le projet ;
- déclare les activités et l'avancement ;
- soumet les demandes de dépense ;
- fournit factures, devis et autres justificatifs ;
- consulte uniquement les informations financières nécessaires à son contrat ;
- ne peut ni s'attribuer l'ownership ni autoriser sa propre demande.

La cible recommande une organisation entrepreneur possédant plusieurs utilisateurs, tout en conservant
des rôles contextuels par projet.

### 4.3 Responsable de chantier / Site Manager

Le responsable de chantier capture la réalité terrain. Il :

- enregistre activités, livraisons, consommations et progression déclarée ;
- dépose photos, vidéos, factures et bons de livraison ;
- associe les preuves aux étapes et demandes ;
- corrige par nouvelle version lorsque la donnée initiale est déjà validée ;
- ne réalise pas la validation technique finale et n'autorise aucun paiement.

### 4.4 Ingénieur

L'ingénieur exerce une revue technique indépendante. Il :

- vérifie quantités, qualité, progression et cohérence constructive ;
- distingue progression déclarée et progression techniquement vérifiée ;
- approuve, approuve sous conditions ou rejette avec un motif ;
- signale les corrections et inspections nécessaires ;
- fournit un avis sur une demande de dépense sans disposer de l'autorité financière finale.

### 4.5 PIVOT

PIVOT représente la gouvernance et la vérification de la plateforme. Les utilisateurs PIVOT autorisés :

- orchestrent l'onboarding concierge ;
- effectuent les contrôles numériques ;
- programment et consignent les inspections physiques ;
- vérifient les dossiers sensibles selon les règles de risque ;
- supervisent les anomalies et contestations ;
- administrent la plateforme avec actions confirmées et auditées ;
- ne remplacent pas l'autorisation financière du client.

## 5. Rôle de compte et rôle projet

Le rôle global d'un compte ne doit pas être la seule source d'autorisation. PIVOT doit distinguer :

- l'identité et l'organisation de l'utilisateur ;
- ses capacités globales ;
- son rôle dans chaque projet ;
- les délégations temporaires ;
- l'état du projet et de son onboarding.

Les rôles projet cibles sont : `OWNER`, `CONTRACTOR`, `SITE_MANAGER`, `ENGINEER` et
`PIVOT_REVIEWER`. Un même utilisateur peut intervenir différemment sur plusieurs projets, mais un projet
doit toujours avoir une autorité propriétaire identifiable.

## 6. Trois routes d'onboarding

### ONB-01 — Client-led

Le client crée son compte, crée son projet, confirme son ownership, sélectionne les conditions
applicables et invite l'entrepreneur. Il peut ensuite inviter ou confirmer le responsable de chantier et
l'ingénieur.

### ONB-02 — Contractor-led

L'entrepreneur crée un workspace préliminaire et invite le client. Le client crée ou ouvre son compte,
confirme le projet, son ownership, l'entrepreneur et les conditions. Le projet ne devient actif qu'après
cette confirmation.

### ONB-03 — PIVOT-led

PIVOT prépare le dossier dans le cadre d'un onboarding concierge, invite le propriétaire, puis coordonne
l'ajout de l'entrepreneur, du responsable et de l'ingénieur. Le client conserve la confirmation finale.

### ONB-04 — Gate d'activation

Avant activation, le projet doit au minimum posséder :

- un client/propriétaire confirmé ;
- un budget ou une enveloppe initiale ;
- des conditions financières acceptées ;
- une autorité financière explicite ;
- les principaux acteurs acceptés ou clairement indiqués comme à compléter ;
- un premier découpage de jalons lorsque le type de projet l'exige.

Les workflows financiers restent verrouillés avant ce gate.

## 7. Dossier projet et registre de preuves

### EVID-01 — Preuves typées

PIVOT accepte au minimum photos, vidéos, PDF, factures, devis, bons de livraison, comptes rendus et
preuves d'inspection.

### EVID-02 — Métadonnées

Chaque preuve conserve projet, auteur, horodatage serveur, type, description, étape concernée, demande
concernée et version. La géolocalisation est capturée avec consentement au moment du dépôt, sans suivi
continu.

### EVID-03 — Immutabilité après validation

Avant validation, une correction contrôlée peut être permise selon le rôle. Après validation, le fichier
et ses métadonnées critiques deviennent immuables. Toute correction référence l'ancienne version et
explique son motif.

### EVID-04 — Accès

Les preuves ne sont accessibles qu'aux acteurs autorisés du projet. Les fichiers en attente respectent la
chaîne de revue. Les téléchargements, aperçus et exports appliquent les mêmes permissions.

### EVID-05 — Mobile-first

Le parcours terrain privilégie une capture rapide sur téléphone : type, étape, fichier, commentaire et
géolocalisation consentie, avec retour clair sur l'envoi et la validation.

## 8. Progression et revue technique

### VER-01 — Deux valeurs de progression

Une étape peut porter une progression déclarée par le terrain et une progression vérifiée par
l'ingénieur. Elles ne doivent jamais être confondues.

### VER-02 — Décisions techniques

L'ingénieur peut :

- approuver ;
- approuver sous conditions avec actions correctives ;
- rejeter avec motif.

### VER-03 — Niveaux de vérification

PIVOT doit supporter :

1. **Digital Verified** : cohérence des documents, preuves, dates, acteurs et transactions ;
2. **Technically Verified** : revue technique de l'ingénieur ;
3. **PIVOT Site Verified** : inspection physique consignée par PIVOT.

### VER-04 — Inspections basées sur le risque

Les jalons imposant une inspection sont configurables. La base pilote recommandée couvre implantation,
fondations, ferraillage avant bétonnage, dalle/plancher, charpente/toiture et réception provisoire.

## 9. Demandes de dépense et paiements MeSomb

### PAY-01 — Demande structurée

L'entrepreneur soumet une demande avec montant, devise, motif, bénéficiaire, jalon, échéance et pièces.

### PAY-02 — Chaîne de décision

Le workflow cible est :

`Entrepreneur → preuves terrain → avis ingénieur → vérification PIVOT requise → autorisation client`.

Le niveau de vérification PIVOT peut dépendre du montant, du jalon, des anomalies et du risque.

### PAY-03 — Autorité owner-only

Seul le client/propriétaire autorise ou refuse la demande. Une délégation éventuelle devra être
explicite, limitée dans le temps et auditée ; elle reste une décision produit à finaliser.

### PAY-04 — Exécution MeSomb

Après autorisation, PIVOT peut initier une collecte ou l'opération MeSomb correspondant au modèle
financier validé. L'exécution doit conserver :

- idempotence ;
- référence PIVOT et référence MeSomb distinctes ;
- mode asynchrone ;
- statuts initié, en attente, réussi, refusé, annulé, échoué et expiré ;
- rapprochement automatique ;
- blocage d'une seconde tentative lorsque l'état est incertain ;
- journalisation sans clés ni numéro complet ;
- aucune comptabilisation avant succès confirmé.

### PAY-05 — Abonnements séparés

Les paiements d'abonnement de l'organisation restent séparés des dépenses et paiements d'un chantier.
Une réussite d'abonnement ne modifie aucun solde projet.

## 10. Rapprochement matières et progression

### RECON-01 — États quantitatifs

Pour chaque matériau, PIVOT distingue acheté, livré, consommé et restant.

### RECON-02 — Sources

Le rapprochement relie commandes ou factures, bons de livraison, entrées/sorties de stock, étapes et
progression déclarée/vérifiée.

### RECON-03 — Plages attendues

Une règle configurable peut définir une plage de consommation attendue pour un ouvrage. Elle assiste la
revue sans remplacer l'ingénieur.

### RECON-04 — Anomalies

Tout écart significatif produit une anomalie visible avant autorisation financière. Sa résolution exige
un responsable, un motif, des preuves et un historique.

## 11. Contestations

Une contestation doit :

- référencer la preuve, validation, demande ou transaction contestée ;
- conserver l'auteur, le motif et la chronologie ;
- geler la décision concernée lorsque nécessaire ;
- accepter des observations et justificatifs contradictoires ;
- solliciter l'avis technique de l'ingénieur ;
- recevoir une résolution PIVOT motivée ;
- ne jamais supprimer les éléments originaux.

## 12. Tableaux de bord

### Client

Décisions en attente, budget, dépenses, preuves récentes, progression déclarée/vérifiée, anomalies,
inspections et paiements.

### Entrepreneur

Exécution, demandes, justificatifs manquants, jalons, équipe et informations financières strictement
nécessaires.

### Responsable de chantier

Capture rapide, activités du jour, livraisons, stock, preuves manquantes et corrections demandées.

### Ingénieur

File de revues techniques, écarts de progression, demandes attendant un avis et inspections.

### PIVOT Control Room

Onboardings, projets bloqués, preuves non vérifiées, demandes, anomalies, inspections, contestations et
KPI pilote.

## 13. KPI du pilote

PIVOT doit rendre mesurables :

- projets actifs et route d'acquisition ;
- conversion entrepreneur vers client activé ;
- valeur totale des projets suivis ;
- dépenses vérifiées ;
- jalons vérifiés ;
- anomalies détectées avant paiement ;
- délais de revue, vérification et autorisation ;
- rétention client et entrepreneur ;
- taux de recommandation ;
- MRR et hypothèses de pricing lorsque l'abonnement est actif.

L'objectif initial est 10 à 20 projets de qualité dans le corridor France/Belgique vers Yaoundé/Douala,
avec onboarding concierge et apprentissage documenté sur 90 jours.

## 14. Périmètre MVP rebaseliné

Le MVP inclut :

- comptes et permissions par rôle projet ;
- trois routes d'onboarding ;
- confirmation du client/propriétaire ;
- dossier projet et invitations ;
- budget et demandes de dépense ;
- stock et mouvements ;
- preuves terrain ;
- jalons et progression déclarée/vérifiée ;
- revue ingénieur et vérification PIVOT ;
- autorisation owner-only ;
- exécution et rapprochement MeSomb ;
- audit immuable ;
- rapports PDF ;
- interface mobile ;
- control room pour l'onboarding concierge.

## 15. Capacités conservées mais non prioritaires

Les capacités déjà livrées restent maintenues sans devenir le centre du lancement :

- assistant IA OpenRouter ;
- pricing et quotas SaaS avancés ;
- thèmes et personnalisation secondaire ;
- fonctions analytiques non indispensables au dossier de confiance.

Les fournisseurs vérifiés, marketplaces, détection avancée d'anomalies, financement, assurances,
garanties et BIM restent des extensions futures.

## 16. Exigences non fonctionnelles

### Sécurité et confidentialité

- isolation stricte organisation/projet ;
- autorisation serveur pour chaque lecture et mutation ;
- CSRF, validation de fichiers et limitation des tailles ;
- secrets uniquement dans l'environnement ;
- téléphone et données sensibles masqués dans les logs ;
- consentement et minimisation pour la géolocalisation ;
- permissions identiques pour interfaces, endpoints, téléchargements et exports.

### Intégrité

- migrations additives et réversibles autant que possible ;
- montants décimaux et devises explicites ;
- transitions atomiques et idempotentes ;
- audit append-only des décisions sensibles ;
- corrections par version ou compensation ;
- aucune activation financière sur un statut fournisseur incertain.

### Exploitabilité

- logs structurés pour MeSomb et intégrations externes ;
- rapprochement planifié indépendant des visites utilisateur ;
- sauvegarde, restauration et rétention définies avant production ;
- passage PostgreSQL avant charge de production ;
- feature flags pour les capacités risquées ou non prioritaires.

### Expérience

- interface Django/Tailwind responsive ;
- capture terrain mobile-first ;
- français et anglais ;
- états vide, chargement, erreur, attente et succès compréhensibles ;
- navigation clavier et modales accessibles sur les parcours critiques.

## 17. Critères de succès

Le rebaseline sera fonctionnellement démontré lorsqu'un projet pourra :

1. être initié par le client, l'entrepreneur ou PIVOT ;
2. être confirmé et activé par le client/propriétaire ;
3. recevoir des preuves terrain attribuées et horodatées ;
4. distinguer progression déclarée et vérifiée ;
5. produire une demande de dépense documentée ;
6. passer par la revue ingénieur et la vérification PIVOT requise ;
7. être autorisé uniquement par le client ;
8. exécuter et rapprocher le paiement MeSomb sans double comptabilisation ;
9. détecter et résoudre un écart matière ;
10. conserver toute la chaîne dans un audit non destructif ;
11. alimenter les KPI du pilote et un rapport compréhensible par le propriétaire.

## 18. Décisions déjà validées

- Le produit conserve le nom **PIVOT**.
- Le client est le propriétaire du chantier.
- MeSomb est conservé.
- Le client possède l'autorité financière finale.
- L'ingénieur donne un avis technique sans autoriser le paiement.
- PIVOT assure la gouvernance et les vérifications configurées.

## 19. Décisions restant à finaliser

1. Modèle de copropriété et désignation du décideur financier principal.
2. Modèle exact de l'organisation entrepreneur et de ses employés.
3. Sélection, contractualisation et rémunération de l'ingénieur.
4. Liste définitive des inspections obligatoires par type de projet.
5. Précision, consentement et durée de conservation de la géolocalisation.
6. Règle contractuelle de délégation de l'autorité financière.
7. Autorité finale et délais de traitement des contestations.

Ces décisions doivent être finalisées avant les stories qui dépendent directement d'elles ; elles ne
bloquent pas la mise à jour documentaire E16-S1.

## 20. Traçabilité de transition

- E1–E15 décrivent les capacités livrées sous l'ancien cadrage.
- E16 rebaseline l'autorité, les rôles et la documentation.
- E17 couvre les trois routes d'onboarding.
- E18 couvre le registre de preuves mobile-first.
- E19 couvre les demandes, l'autorisation owner-only et MeSomb.
- E20 couvre la revue et les trois niveaux de vérification.
- E21 couvre le rapprochement et les anomalies.
- E22 couvre le control room et le pilote concierge.

En cas de contradiction, ce PRD prévaut pour toute nouvelle conception E16+ après validation des
décisions concernées.
