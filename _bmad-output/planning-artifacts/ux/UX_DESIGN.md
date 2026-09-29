# PIVOT-SASS — Conception UX fonctionnelle

Statut : rebaseliné E16  
Version : 1.0  
Date : 2026-09-04  
Référence canonique : `../PRD_PIVOT.md` ; la SPEC historique reste informative pour E1–E15.

## 1. Principes d'expérience

1. **Le chantier d'abord** — après connexion, l'utilisateur voit immédiatement les projets et actions utiles à son rôle.
2. **Un contexte toujours visible** — organisation, projet actif, statut et rôle sont identifiables sans ambiguïté.
3. **Une action, une autorisation** — une action interdite n'est pas proposée dans l'interface et reste refusée côté serveur.
4. **Traçabilité visible** — paiements, retraits, mouvements de stock et validations montrent auteur, date et statut.
5. **Progression guidée** — les écrans expliquent l'état vide et proposent la prochaine action autorisée.
6. **Mobile exploitable sur chantier** — consultation, ajout de photo, mise à jour d'étape, stock et commentaire restent utilisables sur petit écran.
7. **Autorité explicite** — rôle projet, propriétaire désigné et état de confirmation restent visibles dans le dossier.
8. **Finance verrouillée** — aucune action de paiement n'est affichée avant confirmation de l'ownership ; les appels directs sont aussi refusés.
9. **Changement contrôlé** — changer de propriétaire utilise une modale, exige un motif et impose une nouvelle confirmation.

## 2. Structure globale

### Navigation authentifiée

- En-tête : organisation active, recherche contextuelle facultative, notifications futures, profil et déconnexion.
- Barre latérale sur ordinateur ; tiroir sur mobile.
- Fil d'Ariane : tableau de bord → projet → section.
- Zone de contenu avec titre, résumé d'état et action principale unique.

### Navigation par rôle

| Entrée | Ingénieur | Client | Responsable | Administrateur |
|---|---:|---:|---:|---:|
| Tableau de bord | Oui | Oui | Oui | Oui |
| Projets | Oui | Oui, affectés | Oui, affectés | Oui |
| Stock global | Oui | Non | Oui, affecté | Oui |
| Calendrier | Oui | Oui, lecture | Oui | Oui |
| Rapports | Oui | Oui, autorisés | Oui, autorisés | Oui |
| Utilisateurs | Oui, périmètre organisation | Non | Non | Oui |
| Administration | Non | Non | Non | Oui |
| Profil | Oui | Oui | Oui | Oui |

## 3. Inventaire des écrans

### Public et authentification

- `AUTH-01` Connexion.
- `AUTH-02` Inscription ingénieur.
- `AUTH-03` Inscription client, si conservée après arbitrage.
- `AUTH-04` Demande de réinitialisation.
- `AUTH-05` Définition du nouveau mot de passe.
- `AUTH-06` Compte en attente d'activation.

### Espace commun

- `COM-01` Profil utilisateur.
- `COM-02` Liste/calendrier des projets accessibles.
- `COM-03` Centre de rapports.
- `COM-04` Pages 403, 404, 500 et session expirée.

### Ingénieur

- `ENG-01` Tableau de bord : indicateurs, projets récents, actions à traiter.
- `ENG-02` Liste des projets avec recherche, filtres et pagination.
- `ENG-03` Création/modification d'un projet.
- `ENG-04` Gestion des utilisateurs de l'organisation.
- `ENG-05` Création/invitation d'un client ou responsable.
- `ENG-06` File de validation des documents et du stock.

### Client

- `CLI-01` Tableau de bord : projets affectés, échéances et dernier paiement.
- `CLI-02` Paiement Mobile Money.
- `CLI-03` Historique des transactions accessibles.

### Responsable de chantier

- `SITE-01` Tableau de bord chantier : étapes actives, alertes de stock, activités récentes.
- `SITE-02` Mise à jour rapide d'une étape.
- `SITE-03` Ajustement de stock.

### Administration

- `ADM-01` Tableau de bord administratif.
- `ADM-02` Organisations et utilisateurs.
- `ADM-03` Activation des ingénieurs.
- `ADM-04` Accès contrôlé aux objets métier et au journal d'audit.

## 4. Fiche projet

La fiche projet est la surface principale. Elle conserve un en-tête stable : nom, localisation, statut, ingénieur responsable, progression et action principale adaptée au rôle.

### Onglets

1. **Aperçu** — description, membres, chiffres clés, prochaine étape et activité récente.
2. **Finances** — montant du projet, total payé, disponible, reste, transactions et retraits.
3. **Étapes** — chronologie, liste et calendrier.
4. **Stock** — articles, statuts, ajustements et historique.
5. **Documents** — fichiers, statuts et validation.
6. **Photos** — galerie, couverture et association à une étape.
7. **Commentaires** — fil d'échanges.
8. **Rapports** — génération PDF et exports CSV.

Sur mobile, les onglets deviennent un sélecteur ou une liste horizontale défilante. Les tableaux deviennent des cartes ou offrent un défilement explicite.

## 5. Parcours critiques

### 5.1 Ingénieur — créer et lancer un projet

1. Depuis le tableau de bord, choisir « Nouveau projet ».
2. Saisir informations générales, budget XAF et image facultative.
3. Rechercher ou inviter les membres.
4. Vérifier un résumé avant création.
5. Arriver sur la fiche avec une liste de démarrage : ajouter une étape, compléter le stock, partager un document.

Le formulaire est découpé en sections, mais reste une soumission serveur Django cohérente. Les erreurs sont affichées près des champs et un résumé apparaît en tête.

### 5.2 Client — effectuer un paiement

1. Ouvrir un projet affecté puis l'onglet Finances.
2. Choisir « Effectuer un paiement ».
3. Saisir montant, opérateur et numéro.
4. Vérifier le récapitulatif XAF et confirmer une seule fois.
5. Afficher un état « en traitement » sans permettre une double soumission.
6. Présenter le résultat : réussi, échoué ou expiré, avec référence.
7. Refléter le paiement réussi dans les indicateurs et l'historique.

### 5.3 Responsable — mettre à jour l'avancement

1. Ouvrir le tableau de bord chantier.
2. Sélectionner une étape active.
3. Modifier statut, dates autorisées, coût réel, description et photo facultative.
4. Confirmer et afficher l'activité dans la chronologie du projet.

### 5.4 Responsable — ajuster le stock

1. Rechercher l'article dans le projet.
2. Choisir entrée ou sortie et saisir la quantité et le motif.
3. Prévisualiser le stock résultant.
4. Refuser une quantité invalide côté interface et serveur.
5. Créer le mouvement et afficher son auteur et son horodatage.

### 5.5 Ingénieur — valider un élément

1. Ouvrir la file « À valider » depuis le tableau de bord.
2. Examiner le document ou l'article dans son contexte projet.
3. Approuver ou rejeter avec motif.
4. Afficher la décision dans l'historique et informer l'auteur selon les canaux disponibles.

## 6. Composants fonctionnels

- Cartes d'indicateurs avec libellé, valeur, contexte et variation facultative.
- Carte projet avec image, statut, progression, membres et prochaine échéance.
- Badge de statut utilisant texte, couleur et icône ; jamais la couleur seule.
- Tableau filtrable et paginé rendu par Django.
- Formulaires Django avec erreurs accessibles et conservation des valeurs valides.
- Fenêtre de confirmation pour suppression, paiement, retrait et validation.
- Fil d'activité pour les événements importants.
- Zone de dépôt de fichiers avec contraintes visibles avant envoi.
- Messages temporaires Django pour succès et erreurs, complétés par une confirmation persistante pour les opérations financières.

## 7. États obligatoires

Chaque écran de données prévoit :

- chargement ou soumission en cours ;
- résultat normal ;
- résultat vide avec action suivante ;
- erreur récupérable ;
- accès refusé ;
- ressource supprimée ou devenue inaccessible ;
- session expirée avec retour vers la connexion ;
- intégration externe indisponible, sans perte ni double traitement.

## 8. Responsive et accessibilité

- Cible mobile minimale : largeur de 360 px.
- Actions tactiles suffisamment grandes et espacées.
- Navigation complète au clavier sur ordinateur.
- Libellés explicites pour les champs et alternatives textuelles pour les images utiles.
- Contraste lisible et focus visible.
- Erreurs annoncées textuellement et reliées aux champs.
- Aucune fonction essentielle dépend d'un survol.
- Les formulaires longs sont regroupés par sections avec progression perceptible.

## 9. Stratégie d'interface Django

- Rendu serveur par templates Django et héritage de gabarits.
- Fragments réutilisables pour cartes, formulaires, badges, pagination et messages.
- `Form` et `ModelForm` Django pour validation et affichage cohérents.
- JavaScript natif limité aux modales, prévisualisations, calendrier, dépôts de fichiers et interactions nécessitant une mise à jour partielle.
- Les parcours critiques restent utilisables par soumission HTTP classique lorsque cela est raisonnable.
- Aucun React, Vue, Angular, Next.js, Nuxt ou backend Node.js.

## 10. Validation UX attendue

La conception est considérée validée lorsque :

1. chaque rôle retrouve ses tâches principales en deux niveaux de navigation maximum ;
2. la fiche projet expose toutes les fonctions sans mélanger les autorisations ;
3. le paiement rend impossible une double confirmation involontaire ;
4. le responsable peut mettre à jour une étape ou un stock sur mobile ;
5. l'ingénieur identifie rapidement les validations en attente ;
6. les états vide, erreur et accès refusé sont définis ;
7. l'interface peut être mise en œuvre avec Django et ses templates sans SPA.

## 11. Points à confirmer pendant l'architecture

- bibliothèque CSS : Tailwind conservé ou autre solution compatible templates Django ;
- calendrier : FullCalendar conservé ou alternative ;
- éditeur riche : CKEditor conservé ou remplacé ;
- méthode de mise à jour partielle : JavaScript natif seul ou bibliothèque légère compatible rendu serveur ;
- génération PDF et traitement asynchrone ;
- stockage des fichiers et limites d'envoi ;
- mécanisme d'isolation multi-entreprise.
