# PIVOT — Documentation fonctionnelle et structure des interfaces

> **Document historique consolidé jusqu'à E15.** La trajectoire fonctionnelle E16+ est définie dans le
> PRD canonique [`PRD_PIVOT.md`](./_bmad-output/planning-artifacts/PRD_PIVOT.md), rebaseliné le
> 4 septembre 2026 à partir de la stratégie fournie. Le produit conserve le nom PIVOT ; le client est le
> propriétaire du chantier et MeSomb est maintenu après autorisation financière du client.

## 1. Présentation générale

PIVOT est une application web de gestion et de suivi de projets de construction. Elle centralise les informations d’un chantier : acteurs, finances, paiements, retraits, planning, étapes, stock, documents, photos, commentaires et rapports.

L’application est développée avec Django et utilise principalement :

- Django pour le serveur, les comptes, les formulaires, les routes et l’administration ;
- SQLite comme base de données dans la version analysée ;
- des templates HTML Django pour l’interface ;
- Tailwind CSS et les composants du thème graphique pour la mise en page ;
- JavaScript/AJAX pour plusieurs actions sans rechargement ;
- CKEditor 5 pour les descriptions enrichies ;
- FullCalendar pour les calendriers ;
- MeSomb pour les paiements Mobile Money ;
- xhtml2pdf pour produire les rapports PDF ;
- CSV pour plusieurs exports ;
- Django Unfold pour l’interface d’administration.

## 2. Rôles utilisateurs

### 2.1 Ingénieur — `user_type = 1`

L’ingénieur est le propriétaire opérationnel des projets qu’il crée.

Fonctions prévues ou disponibles :

- consulter son tableau de bord ;
- voir le nombre total de projets et leur répartition : en attente, en cours et terminés ;
- créer un projet ;
- modifier ses projets ;
- affecter des clients ou responsables de chantier à un projet ;
- rechercher des utilisateurs par adresse e-mail ;
- créer des comptes utilisateurs et envoyer un e-mail d’accueil ;
- consulter la fiche complète d’un projet ;
- définir le montant du projet et suivre les montants payés, disponibles et restant à payer ;
- enregistrer et suivre les retraits ;
- ajouter, modifier et suivre les étapes du chantier ;
- ajouter des articles en stock et vérifier leur statut ;
- importer du stock depuis un fichier ;
- consulter l’historique du stock ;
- téléverser des documents et des images ;
- supprimer des images ;
- écrire, modifier ou supprimer des commentaires ;
- consulter le calendrier ;
- exporter les données et générer des rapports.

L’inscription d’un ingénieur crée initialement un compte inactif. Un e-mail est envoyé à l’administrateur, qui doit ensuite activer ce compte.

### 2.2 Client — `user_type = 2`

Le client consulte les projets auxquels il est affecté et peut participer au suivi financier et aux échanges.

Fonctions prévues ou disponibles :

- créer un compte client actif ;
- inviter facultativement un ingénieur par e-mail lors de l’inscription ;
- consulter son tableau de bord et ses projets affectés ;
- voir les étapes et le nombre de commentaires ;
- ouvrir la fiche d’un projet affecté ;
- consulter les informations, membres, images, documents, stock, étapes et commentaires ;
- effectuer un paiement Mobile Money ;
- consulter l’historique des transactions ;
- ajouter des commentaires ;
- ajouter ou ajuster du stock via la fiche affectée, selon l’interface actuelle ;
- téléverser des documents, placés initialement au statut « en attente » ;
- consulter le calendrier ;
- générer un rapport PDF pour un projet auquel il appartient.

### 2.3 Responsable de chantier — `user_type = 3`

Le responsable de chantier utilise un espace proche de celui du client, centré sur les projets auxquels il est affecté.

Fonctions prévues ou disponibles :

- consulter son tableau de bord ;
- voir ses projets affectés, leurs étapes et leurs commentaires ;
- accéder à la fiche d’un projet affecté ;
- suivre les informations, le stock, les documents, les images, les étapes et les échanges ;
- ajouter ou ajuster des éléments de stock depuis certaines interfaces ;
- téléverser des documents ;
- commenter ;
- consulter le calendrier et les rapports disponibles.

### 2.4 Administrateur / superutilisateur

L’administrateur utilise l’administration Django personnalisée avec Unfold.

Il peut administrer :

- les utilisateurs ;
- les profils utilisateurs ;
- les projets ;
- les commentaires ;
- les étapes de projet ;
- les documents ;
- les images ;
- les articles de stock ;
- les mouvements de stock ;
- les transactions de paiement.

Il assure notamment l’activation des comptes ingénieurs. Un utilisateur `is_staff` peut aussi modifier un projet via la vue de modification.

## 3. Authentification et gestion des comptes

### 3.1 Connexion

La page de connexion accepte le nom d’utilisateur et le mot de passe. Après authentification, l’utilisateur est dirigé automatiquement selon son rôle :

- ingénieur vers le tableau de bord ingénieur ;
- client vers le tableau de bord client ;
- responsable de chantier vers son tableau de bord.

### 3.2 Déconnexion

La déconnexion détruit la session et renvoie vers la page de connexion.

### 3.3 Inscription

Deux formulaires publics existent dans les routes : inscription ingénieur et inscription client.

- Ingénieur : nom d’utilisateur, e-mail, téléphone et mot de passe ; compte inactif jusqu’à validation administrative.
- Client : mêmes informations principales ; compte immédiatement actif.

### 3.4 Création d’utilisateurs par un ingénieur

L’ingénieur peut créer un utilisateur avec : nom d’utilisateur, e-mail, téléphone, mot de passe et rôle. Le compte est activé automatiquement et un e-mail d’accueil est tenté.

### 3.5 Profil

Chaque utilisateur possède automatiquement un profil associé. Il peut modifier :

- nom d’utilisateur ;
- prénom et nom ;
- localisation ;
- biographie ;
- téléphone ;
- photo de profil.

### 3.6 Réinitialisation du mot de passe

Le parcours comprend : demande par e-mail, lien avec jeton, choix d’un nouveau mot de passe et écran de confirmation.

## 4. Gestion des projets

### 4.1 Données d’un projet

Un projet contient :

- nom ;
- description enrichie ;
- localisation ;
- date affichée sous forme de texte ;
- ingénieur responsable ;
- utilisateurs affectés ;
- image de couverture ;
- statut : en attente, en cours ou terminé ;
- montant total ;
- montant disponible ;
- total payé ;
- reste à payer ;
- liste des retraits ;
- dates de création et de dernière modification.

### 4.2 Création

La création peut être réalisée depuis le tableau de bord, dans une fenêtre modale, ou depuis une page dédiée. Le formulaire permet de saisir les données principales, choisir des utilisateurs et ajouter une ou plusieurs images.

### 4.3 Affectation des membres

Un projet appartient à un ingénieur et peut être affecté à plusieurs utilisateurs. La recherche AJAX ne propose que les clients et les responsables de chantier, filtrés par e-mail.

### 4.4 Modification

L’ingénieur propriétaire ou un membre du personnel peut modifier le projet. La fiche ingénieur permet également une modification AJAX en fenêtre modale.

### 4.5 Statuts

- `Pending` : projet en attente ;
- `On Going` : projet en cours ;
- `Complete` : projet terminé.

## 5. Gestion financière et paiements

### 5.1 Indicateurs financiers

Chaque fiche projet présente quatre cartes :

- montant du projet ;
- total payé ;
- montant disponible ;
- reste à payer.

Le reste à payer est recalculé avec `montant du projet - total payé`. Le montant disponible correspond au total payé moins les retraits considérés comme réalisés.

### 5.2 Paiement Mobile Money

Un utilisateur affecté peut ouvrir une fenêtre de paiement et fournir :

- le montant ;
- le service/opérateur ;
- le numéro du payeur.

L’application appelle MeSomb, enregistre une transaction avec un identifiant unique, puis met à jour les données financières si le paiement réussit. Les échecs et expirations sont également enregistrés.

### 5.3 Retraits

L’ingénieur peut enregistrer un retrait avec un montant. Les retraits sont stockés dans le projet sous forme de données JSON et présentés avec pagination de cinq lignes. Leur statut intervient dans le calcul du montant disponible.

### 5.4 Historique et exports financiers

L’application conserve les transactions de paiement : utilisateur, montant, service, payeur, statut, identifiant et date. Elle permet d’exporter les transactions et les retraits en CSV.

## 6. Planning, étapes et calendrier

Une étape de projet contient :

- titre ;
- description enrichie ;
- date de début ;
- date de fin ;
- coût estimé ;
- coût réel ;
- statut : en attente, active ou terminée.

Fonctions disponibles :

- ajouter une étape ;
- modifier une étape depuis une fenêtre modale ;
- afficher les étapes sous forme de liste/chronologie ;
- associer une image à une étape ;
- afficher les étapes dans FullCalendar ;
- récupérer les événements au format JSON ;
- exporter les étapes d’un projet en CSV.

La page calendrier regroupe les projets accessibles à l’utilisateur, avec une section repliable par projet.

## 7. Gestion du stock

### 7.1 Article de stock

Un article contient :

- nom ;
- unité ;
- prix unitaire ;
- prix total ;
- quantité ;
- statut : en attente, vérifié ou approuvé ;
- projet associé ;
- date de création.

### 7.2 Mouvements de stock

Chaque ajustement crée un mouvement contenant la variation de quantité et sa date. La quantité de l’article est ensuite augmentée ou diminuée.

### 7.3 Fonctions disponibles

- ajouter un article ;
- afficher le stock d’un projet ;
- afficher tous les stocks des projets accessibles ;
- ajuster une quantité ;
- vérifier un article depuis la fiche ingénieur ;
- consulter l’historique des variations ;
- importer des articles depuis un fichier ;
- exporter le stock en CSV, avec filtre par dates.

## 8. Documents, images et commentaires

### 8.1 Documents

Un document possède un titre, un fichier, une date de téléversement et un statut : en attente ou approuvé.

La fiche projet permet de :

- afficher les documents sous forme de cartes ;
- ouvrir un fichier dans un nouvel onglet lorsque son statut l’autorise ;
- téléverser un PDF dans une fenêtre modale ;
- ajouter immédiatement la nouvelle carte à l’interface grâce à AJAX.

### 8.2 Images

Les images peuvent servir de couverture ou alimenter la galerie du projet. Une image peut être rattachée à une étape. L’ingénieur peut téléverser des images, filtrer la galerie et supprimer une image avec confirmation.

### 8.3 Commentaires

Les membres autorisés peuvent lire et écrire des commentaires. Ceux-ci sont affichés du plus récent au plus ancien avec leur auteur et leur date. Des points d’accès AJAX existent pour modifier et supprimer un commentaire.

## 9. Rapports et exports

PIVOT propose :

- un rapport PDF complet par projet ;
- une page de sélection des projets et de la période du rapport ;
- un filtrage par date pour certaines données du PDF ;
- l’inclusion des informations du projet, membres, stock, retraits, transactions, étapes, commentaires et images ;
- un export CSV des retraits ;
- un export CSV des transactions ;
- un export CSV du stock ;
- un export CSV des étapes.

Le modèle PDF principal est présenté comme un « Weekly Site Report » orienté chantier.

## 10. Structure générale des interfaces

### 10.1 Gabarit principal

Les pages authentifiées utilisent un gabarit commun composé de :

1. une barre latérale de navigation ;
2. une barre supérieure ;
3. une zone de titre et de fil d’Ariane ;
4. une zone centrale de contenu ;
5. un pied de page ;
6. un panneau de personnalisation visuelle.

La mise en page est responsive. Le menu latéral peut être réduit ou affiché au survol. L’utilisateur peut choisir un thème clair ou sombre, une direction gauche-droite ou droite-gauche, et différentes variantes de largeur et de navigation.

### 10.2 Barre supérieure

Elle comprend notamment :

- le bouton d’ouverture/fermeture du menu ;
- une zone de recherche visuelle ;
- le plein écran ;
- les notifications ;
- le changement clair/sombre ;
- le menu du compte utilisateur.

Certaines zones, comme les notifications et la recherche globale, sont surtout des composants visuels du thème et ne correspondent pas toutes à une logique métier complète.

### 10.3 Barre latérale

Le menu est adapté au rôle connecté. Il donne accès, selon le profil, à :

- tableau de bord ;
- projets ou rapports de projets ;
- gestion/liste des stocks ;
- calendrier ;
- profil et déconnexion via le menu utilisateur.

## 11. Structure des principaux écrans

### 11.1 Page de connexion et pages d’inscription

Ces écrans utilisent une mise en page d’authentification distincte : illustration/identité visuelle, titre, formulaire central, validation des champs, affichage du mot de passe et messages de succès ou d’erreur.

### 11.2 Tableau de bord ingénieur

L’écran est structuré ainsi :

1. action de création d’un utilisateur ;
2. quatre cartes statistiques : total, en attente, en cours et terminé ;
3. grille de cartes de projets avec image, nom, description, statut et accès à la fiche ;
4. état vide lorsqu’aucun projet n’existe ;
5. fenêtre modale de création d’un projet ;
6. fenêtre/formulaire de création d’un utilisateur.

### 11.3 Tableaux de bord client et responsable de chantier

Ils présentent principalement :

1. les projets affectés sous forme de cartes ;
2. l’image et les informations essentielles de chaque projet ;
3. un accès à la fiche détaillée affectée ;
4. les étapes liées ;
5. un état vide si aucun projet n’est affecté.

### 11.4 Fiche projet ingénieur

C’est l’interface la plus complète. Elle est organisée en blocs :

1. quatre cartes financières ;
2. fenêtre modale de modification du projet ;
3. aperçu : statut, localisation, date et nombre de commentaires ;
4. description et membres du projet ;
5. tableau du stock et actions d’ajout, vérification, historique et export ;
6. documents avec téléversement ;
7. galerie d’images avec téléversement et suppression ;
8. retraits et historique financier ;
9. étapes/chronologie et calendrier ;
10. ajout et modification d’étapes ;
11. formulaire de commentaire et fil des commentaires ;
12. plusieurs fenêtres modales et notifications temporaires pour les actions AJAX.

### 11.5 Fiche projet affectée

Elle reprend presque la même structure, mais met davantage en avant le paiement :

1. indicateurs financiers ;
2. bouton et fenêtre de paiement ;
3. aperçu et membres ;
4. stock et ajustements ;
5. documents ;
6. images ;
7. étapes ;
8. commentaires ;
9. historique des transactions.

### 11.6 Liste des rapports

La page « Projects Reports » liste les projets accessibles. Une fenêtre permet de sélectionner une période avant de générer le PDF. Un état d’avertissement apparaît lorsqu’aucun projet n’est disponible.

### 11.7 Calendrier

La page calendrier affiche une liste accordéon de projets. Chaque panneau contient un calendrier FullCalendar alimenté par les étapes du projet.

### 11.8 Administration

L’administration possède sa propre navigation Unfold. Chaque modèle est présenté sous forme de listes filtrables et de formulaires d’édition, accessibles principalement au superutilisateur.

## 12. Modèle de données simplifié

- `User` possède un `UserProfile`.
- `User` possède un rôle : ingénieur, client ou responsable de chantier.
- `Project` appartient à un ingénieur.
- `Project` est affecté à plusieurs utilisateurs.
- `Project` possède plusieurs commentaires.
- `Project` possède plusieurs transactions de paiement.
- `Project` possède plusieurs étapes.
- `Project` possède plusieurs images.
- `Project` possède plusieurs documents.
- `Project` possède plusieurs articles de stock.
- `StockItem` possède plusieurs mouvements de stock.
- `ProjectImage` peut être associée à une étape.

## 13. Points d’attention constatés dans le code

Cette section décrit l’état réel de la version analysée, sans affirmer que ces comportements sont souhaités.

### 13.1 Contrôles d’accès à renforcer

- Plusieurs fonctions de stock ne portent pas explicitement de décorateur de connexion.
- L’ajout d’un article et certaines consultations utilisent l’identifiant du projet sans vérifier systématiquement l’appartenance de l’utilisateur.
- Les routes AJAX de modification/suppression de commentaires sont exemptées de protection CSRF et ne contrôlent pas actuellement que l’utilisateur est l’auteur.
- La suppression d’une image ne contrôle pas explicitement le propriétaire du projet.
- Plusieurs exports et actions d’étape devraient vérifier uniformément l’accès au projet.
- La vue détaillée ingénieur ne déclare pas de mixin de connexion ni de filtrage explicite du projet par propriétaire.

### 13.2 Cohérence fonctionnelle à vérifier

- Les rôles client et responsable de chantier partagent beaucoup d’actions ; les permissions métier exactes ne sont pas toujours distinguées côté serveur.
- Le statut « approved » du stock existe dans le modèle, mais l’interface analysée fait surtout passer un article de « pending » à « verified ».
- Les documents sont créés en « pending » ; leur approbation semble principalement relever de l’administration.
- Certaines interfaces et scripts sont dupliqués, notamment autour des documents, événements et fenêtres modales.
- Plusieurs blocs de code anciens restent commentés.
- La page de profil affiche des valeurs statiques pour certains compteurs (« Total Project », « Total Task »).
- Des champs financiers sont stockés comme texte, ce qui impose des conversions et peut provoquer des incohérences de calcul.
- Le champ `date` du projet est un texte alors que les dates d’étapes sont de vrais champs date.
- Le calcul du montant disponible ne traite pas les statuts des retraits de manière parfaitement uniforme selon les fonctions.
- Une requête AJAX de stock demande encore un champ `price` qui n’existe plus dans le modèle actuel (`unit_price` et `total_price` existent).
- Certaines vues imposent la présence d’un en-tête HTTP `Referer` interne et déconnectent sinon l’utilisateur ; cela peut produire des déconnexions inattendues.

### 13.3 Sécurité et configuration

- Les clés de paiement, d’e-mail et autres secrets doivent rester dans les variables d’environnement et ne jamais être documentés ou versionnés.
- Les actions de création, modification, suppression, paiement et export devraient toutes appliquer des contrôles d’accès homogènes côté serveur.
- Les entrées financières devraient utiliser des champs décimaux et une validation stricte.

## 14. Arborescence fonctionnelle du code

```text
PIVOT/
├── project/                 Configuration Django, routes globales, WSGI/ASGI
├── accounts/                Comptes, profils, projets, paiements, étapes,
│   ├── models.py            commentaires, images et documents
│   ├── forms.py             Formulaires métier
│   ├── views.py             Logique des écrans et actions
│   ├── urls.py              Routes de l’application
│   ├── admin.py             Administration personnalisée
│   ├── templates/           Pages et composants HTML
│   └── static/              CSS, JavaScript, images et bibliothèques
├── Stock/                   Articles et mouvements de stock
├── templates/               Pages d’erreur 404 et 500
├── media/                   Fichiers envoyés : images et documents
├── staticfiles/             Ressources statiques collectées
├── db.sqlite3               Base de données locale
├── manage.py                Commandes Django
├── requirements.txt         Dépendances Python
└── Dockerfile               Construction du conteneur
```

## 15. Parcours utilisateur résumés

### Parcours ingénieur

1. inscription ;
2. activation par l’administrateur ;
3. connexion et arrivée sur le tableau de bord ;
4. création de clients/responsables et d’un projet ;
5. affectation des membres ;
6. définition du budget ;
7. ajout des étapes, du stock, des documents et des images ;
8. suivi des paiements et retraits ;
9. échanges par commentaires ;
10. génération de rapports et exports.

### Parcours client

1. inscription ou création du compte par un ingénieur ;
2. connexion ;
3. consultation des projets affectés ;
4. ouverture d’une fiche ;
5. consultation de l’avancement, des médias, documents et finances ;
6. paiement Mobile Money ;
7. commentaire et consultation des rapports.

### Parcours responsable de chantier

1. création du compte et affectation à un projet ;
2. connexion ;
3. consultation des projets et du planning ;
4. suivi ou mise à jour du stock selon les droits actuels ;
5. ajout de documents et commentaires ;
6. suivi des étapes et consultation des rapports.

---

Document produit à partir de l’analyse statique du dépôt PIVOT. Il décrit les modèles, formulaires, routes, vues et templates présents dans le code. Les services externes n’ont pas été exécutés et les comportements signalés comme « prévus » peuvent nécessiter une validation en conditions réelles.

---

# Révision fonctionnelle consolidée — août 2026

Cette révision complète le document initial et constitue la référence fonctionnelle pour l’état actuel de PIVOT. En cas de contradiction avec les sections précédentes, les règles ci-dessous prévalent.

## 16. Vision produit actualisée

PIVOT est une application SaaS web de pilotage de chantiers, développée exclusivement avec Django côté serveur et utilisant SQLite3 pour l’environnement local actuel. Elle fournit des espaces isolés par organisation, des parcours adaptés aux rôles, une super-administration personnalisée, des paiements Mobile Money, des notifications par e-mail, une interface bilingue et un assistant IA contextuel.

L’identité visuelle principale repose sur le bleu `#00157f`, les logos officiels PIVOT, Tailwind CSS, des composants applicatifs cohérents et des interfaces responsives. Les actions de création et les actions contextuelles utilisent des modales lorsque cela évite de quitter l’écran courant. Les actions sensibles ou destructrices exigent une modale de confirmation.

## 17. Organisations et isolation des données

Une organisation représente l’espace de travail isolé d’une entreprise d’ingénierie ou de construction. Elle regroupe ses ingénieurs, clients, responsables de chantier, projets et données métier.

Règles fonctionnelles :

- l’inscription d’un ingénieur principal crée une demande de compte et son organisation ;
- le compte ingénieur reste inactif jusqu’à validation par un super-administrateur ;
- les ingénieurs supplémentaires rejoignent normalement une organisation existante par invitation ou affectation contrôlée ;
- un utilisateur métier ne peut consulter que les données de son organisation et les projets auxquels son rôle lui donne accès ;
- une organisation suspendue ou archivée conserve ses données, mais ses parcours métier sont bloqués ;
- les contrôles d’isolation sont appliqués côté Django, indépendamment de l’interface.

## 18. Comptes, invitations et notifications

### 18.1 Inscription et activation des ingénieurs

Après l’envoi du formulaire d’inscription ingénieur :

- le demandeur reçoit un e-mail de confirmation indiquant que son compte attend une validation ;
- chaque super-administrateur actif disposant d’une adresse e-mail reçoit une notification de demande en attente ;
- après activation, l’ingénieur reçoit un e-mail lui indiquant qu’il peut se connecter ;
- les liens publics sont construits à partir de la variable d’environnement `APP_BASE_URL`.

### 18.2 Inscription client

Le client possède un parcours d’inscription séparé, avec une interface cohérente avec la connexion et l’identité PIVOT. Il accède uniquement aux projets auxquels il est affecté.

### 18.3 Invitations

Un responsable autorisé peut inviter un client ou un responsable de chantier par adresse e-mail. L’adresse invitée n’a pas besoin d’exister préalablement dans la base : un lien sécurisé et temporaire permet au destinataire de finaliser son compte. Une invitation active ne peut pas être dupliquée pour la même adresse et peut être annulée par un utilisateur autorisé. Les pages d’invitation et d’acceptation reprennent la présentation des pages d’authentification.

### 18.4 E-mails transactionnels

Les e-mails utilisent des modèles HTML et texte aux couleurs de PIVOT et les logos officiels stockés dans les ressources statiques. Ils sont envoyés notamment pour :

- inscription et validation d’un compte ingénieur ;
- invitation d’un membre et acceptation du compte ;
- bienvenue ou création de compte ;
- réinitialisation du mot de passe ;
- événements métier explicitement configurés, notamment certaines validations.

Les paramètres SMTP et l’adresse d’expédition `DEFAULT_FROM_EMAIL` sont fournis par variables d’environnement. Aucun secret ne doit apparaître dans le dépôt, les templates, les journaux ou l’administration.

## 19. Expérience utilisateur et identité visuelle

### 19.1 Authentification

Les écrans de connexion, d’inscription ingénieur, d’inscription client et d’acceptation d’invitation utilisent une composition commune : panneau de marque bleu, logo officiel, illustration chantier, arrière-plan photographique lissé par transparence, formulaire compact et contrôles de mot de passe avec icône d’affichage/masquage. Les textes techniques standards d’aide au mot de passe ne sont pas affichés en permanence ; les erreurs utiles restent affichées au moment de la validation.

### 19.2 Navigation applicative

La barre latérale comporte de vraies icônes, peut être réduite et conserve un alignement correct du logo dans les deux états. L’élément actif dépend de la route courante et ne reste pas fixé sur le tableau de bord ou la vue d’ensemble. La déconnexion se trouve dans la barre supérieure.

### 19.3 Thèmes et langues

L’utilisateur peut choisir un thème clair ou sombre. Le choix s’applique de manière cohérente aux pages, modales, tableaux, formulaires et composants persistants. L’interface est disponible en français et en anglais avec un sélecteur en menu déroulant utilisant les drapeaux correspondant aux langues. Le changement de langue conserve la page courante lorsque celle-ci reste accessible, au lieu de renvoyer systématiquement vers le tableau de bord.

### 19.4 Responsive et accessibilité

Les parcours critiques restent utilisables sur téléphone, tablette et ordinateur. Les modales gèrent le focus, la touche Échap, la fermeture explicite, les erreurs, les doubles clics et les débordements. Les actions ne dépendent pas uniquement de la couleur ou du survol.

## 20. Projets et collaboration actualisés

La création d’un projet se fait depuis une modale. Le créateur peut immédiatement rechercher et sélectionner plusieurs clients et responsables de chantier au moyen d’un champ d’autocomplétion. Aucune liste complète d’utilisateurs de la base n’est exposée au chargement ; les suggestions sont recherchées à la demande, limitées au périmètre autorisé et filtrées par rôle.

Les projets accessibles apparaissent sur les tableaux de bord et dans le calendrier. La progression est calculée à partir des étapes du projet, de leurs statuts et de leur avancement, et non à partir d’une valeur visuelle arbitraire.

Les commentaires peuvent être modifiés ou supprimés uniquement par leur auteur, sous réserve des règles d’administration exceptionnelles. Leur conteneur possède une hauteur maximale et devient défilable lorsque le volume de messages la dépasse. Toute suppression utilise une confirmation.

La galerie photo dispose d’un aperçu plein écran avec navigation précédente/suivante et bouton de fermeture. Les documents et photos soumis à validation disposent d’un aperçu avant approbation, rejet ou suppression. Un document non encore approuvé ne peut pas être téléchargé par les utilisateurs métier non autorisés.

## 21. Tableaux de bord et indicateurs

Les tableaux de bord présentent les indicateurs réellement utiles au rôle : projets, statuts, progression, échéances, activités et données financières autorisées. Au moins un véritable graphique d’évolution ou de comparaison est prévu lorsque les données le justifient ; les graphiques décoratifs et diagrammes circulaires sans valeur métier sont exclus.

L’ingénieur voit les projets qu’il possède ou auxquels il est affecté selon les règles métier. Le client et le responsable de chantier ne voient que leurs projets affectés. Le super-administrateur voit les agrégats globaux sans mélanger les organisations ni les devises.

## 22. Finances et paiements MeSomb

### 22.1 Paiement

Le paiement est initié depuis une modale compacte demandant le montant en XAF, l’opérateur et le téléphone du payeur. Les boutons d’export CSV, de paiement et de retrait sont placés dans la zone d’actions financières de manière cohérente avec le reste de l’application.

L’intégration MeSomb est configurée uniquement par variables d’environnement : clés d’application et d’accès, URL et paramètres techniques. PIVOT conserve une référence locale unique et l’état du paiement.

### 22.2 Cycle de vie et résilience

Les états fonctionnels comprennent au minimum : initiation, attente, succès, refus, annulation, échec et expiration. Le traitement couvre :

- un délai d’expiration explicite pour l’appel au fournisseur ;
- la vérification automatique de l’état d’une transaction incertaine ou en attente ;
- des tentatives de reprise limitées pour les erreurs transitoires ;
- l’idempotence afin d’éviter un double encaissement ;
- le blocage d’une seconde tentative incompatible pendant qu’un premier paiement reste incertain ;
- la persistance des refus, annulations et expirations ;
- la mise à jour des montants du projet uniquement après succès confirmé.

La version actuelle ne dépend pas d’un webhook MeSomb : la synchronisation repose sur les vérifications serveur prévues. L’utilisateur ne doit pas avoir à comprendre la technique d’actualisation ; l’interface expose simplement l’état connu et les éventuelles actions autorisées.

### 22.3 Retraits

Une demande de retrait est créée depuis une modale contenant le montant et le motif. Les transitions d’état sont contrôlées. Le montant disponible tient compte uniquement des paiements confirmés et des retraits dont le statut doit effectivement réduire le solde.

## 23. Documents, médias, rapports et validations

Les documents et photos sont prévisualisables par les responsables autorisés avant approbation ou suppression. Cette règle s’applique également aux files « Validations et finances » de la super-administration. Les actions impossibles dans l’état courant sont désactivées côté interface et refusées côté serveur.

Les suppressions de documents, photos, commentaires et autres contenus utilisent une modale de confirmation précisant la cible et les conséquences. Lorsqu’une suppression compromettrait l’intégrité financière, documentaire ou d’audit, le système privilégie le rejet, l’annulation ou l’archivage.

Le rapport PDF d’un projet possède une mise en page professionnelle : identité PIVOT, page de garde, informations structurées du chantier, synthèses financières, étapes, stocks, documents, photos, commentaires et pied de page. Seules les données autorisées et compatibles avec les filtres demandés sont incluses.

## 24. Super-administration personnalisée

PIVOT possède un espace distinct sous `/super-admin/`, réservé aux utilisateurs ayant `is_superuser=True`. Il ne s’agit pas simplement de l’administration Django native. Son interface reprend les couleurs, logos, thèmes, langues, composants et navigation de l’application.

### 24.1 Tableau de bord global

Le tableau de bord affiche les organisations, utilisateurs, projets, validations en attente, volumes financiers autorisés, état des intégrations et indicateurs de santé. Les agrégats financiers ne mélangent pas les devises.

### 24.2 Organisations

Le super-administrateur peut rechercher, filtrer, consulter, créer et modifier une organisation. Il peut la suspendre, l’archiver, la restaurer ou, uniquement sans dépendances, la supprimer après confirmation renforcée. Les données d’une organisation archivée sont conservées.

### 24.3 Utilisateurs

Le super-administrateur peut rechercher et filtrer les utilisateurs, consulter leur rôle et organisation, créer ou modifier un compte, activer ou suspendre l’accès, déclencher une réinitialisation de mot de passe et transférer un utilisateur lorsque ses dépendances le permettent. Il ne peut ni consulter un mot de passe ni supprimer accidentellement le dernier accès super-administrateur.

### 24.4 Projets et contenus

La supervision des projets est en lecture seule par défaut. Une intervention exceptionnelle sur le responsable, les membres, le statut ou les informations autorisées exige un motif, une confirmation et un audit. Les actions nécessaires sur étapes, stocks, documents, photos, commentaires et demandes financières sont proposées selon l’état de chaque objet.

### 24.5 Validations et finances

Une file centrale regroupe les comptes ingénieurs, documents, contenus et opérations financières nécessitant une intervention. Toute approbation ou tout rejet affiche l’aperçu disponible, exige une confirmation et, lorsque pertinent, un motif. Les traitements doubles et transitions invalides sont bloqués.

### 24.6 Audit et paramètres

Le journal global indique l’acteur, la date, l’action, l’organisation, la ressource et les informations strictement nécessaires. Il est consultable et filtrable, mais non modifiable. Les mots de passe, clés, jetons et contenus privés inutiles ne sont jamais audités en clair.

La page de santé distingue services configurés, avertissements et incidents. Les secrets y sont masqués et ne peuvent pas être relus en clair. Les opérations dangereuses de maintenance ne sont pas exposées comme de simples boutons.

## 25. Assistant IA PIVOT avec OpenRouter

### 25.1 Objectif et interface

Un bouton flottant en bas à droite ouvre une fenêtre de discussion sur le côté droit de la page. Le composant respecte la marque PIVOT, les thèmes, le responsive et l’accessibilité. Chaque conversation appartient à son utilisateur et, le cas échéant, à son organisation.

### 25.2 Architecture

Le navigateur appelle exclusivement un endpoint Django interne. Django authentifie l’utilisateur, analyse la question, détermine les domaines métier concernés, applique les permissions et exécute les outils de lecture autorisés. OpenRouter est appelé directement par HTTPS pour les questions générales ou la formulation nécessitant un modèle de langage ; aucune connexion MCP n’est requise dans l’architecture actuelle.

OpenRouter est configuré par variables d’environnement : activation, clé API, URL de base, modèle, délais d’expiration, nombre maximal de jetons et température. La clé n’est jamais envoyée au navigateur ni enregistrée dans la base.

### 25.3 Données réelles et réponses déterministes

Les questions portant sur les données existantes sont résolues par Django à partir des modèles et sélecteurs autorisés. Les calculs, noms, listes, statuts, montants, dates et décomptes ne sont pas inventés par le LLM. Les domaines couverts sont :

- organisations et statistiques de plateforme ;
- utilisateurs et rôles ;
- projets ;
- étapes et calendrier ;
- stocks ;
- documents ;
- photos ;
- commentaires ;
- paiements et finances ;
- rapports.

Le routeur reconnaît les formulations françaises et anglaises, synonymes, accents, fautes courantes et questions portant sur plusieurs domaines. Une absence de données est distinguée d’un refus d’accès.

### 25.4 Permissions de l’assistant

L’assistant applique exactement le rôle, l’organisation et les projets accessibles au compte connecté. Un client peut demander ses propres paiements et les informations de ses projets, mais ne peut recevoir une liste globale d’utilisateurs ou une procédure réservée à l’ingénieur. Un ingénieur reste limité à son organisation et à ses projets. Seul le super-administrateur peut interroger les agrégats globaux autorisés.

La première version de l’assistant est en lecture seule : elle n’effectue aucune création, modification, approbation, suppression, invitation, paiement ou retrait.

### 25.5 Sécurité et disponibilité

Les protections comprennent : limitation de fréquence et de jetons, contrôle des demandes simultanées ou dupliquées, expiration des requêtes bloquées, délais réseau, validation des réponses, protection contre l’injection de prompt, minimisation des données et journalisation sans prompt sensible en clair. L’assistant peut être désactivé globalement sans empêcher l’utilisation normale de PIVOT.

## 26. Exigences de sécurité transversales

- Toute vue privée exige une authentification et vérifie le rôle côté serveur.
- Toute ressource métier est filtrée par organisation et, lorsque nécessaire, par affectation au projet.
- Les commentaires ne sont modifiables et supprimables que par leur auteur, hors intervention super-administrateur explicitement auditée.
- Les actions sensibles utilisent POST, la protection CSRF, une transaction atomique et une protection contre les doubles soumissions.
- Les fichiers non approuvés ne sont pas accessibles au téléchargement par un rôle non autorisé.
- Les secrets SMTP, MeSomb et OpenRouter restent dans les variables d’environnement.
- Les erreurs utilisateur ne divulguent ni secret, ni chemin interne, ni existence d’une ressource inaccessible.
- Les données financières utilisent des validations strictes et ne sont mises à jour qu’à partir d’opérations confirmées.

## 27. Configuration externe requise

Le déploiement doit fournir au minimum, selon les fonctions activées :

- configuration Django et URL publique `APP_BASE_URL` ;
- paramètres SMTP et `DEFAULT_FROM_EMAIL` ;
- clés MeSomb ;
- activation, clé et modèle OpenRouter ;
- paramètres de stockage des médias et ressources statiques ;
- paramètres de sécurité propres à l’environnement de production.

Le fichier `.env.example` documente les noms attendus sans contenir de valeur secrète. Le démarrage de l’application doit rester possible lorsque l’assistant IA est désactivé.

## 28. Exigences de tests et définition de terminé

Une fonctionnalité est considérée comme terminée lorsque :

- ses critères d’acceptation sont démontrés ;
- les permissions et l’isolation inter-organisations sont testées ;
- les migrations nécessaires sont présentes ;
- les erreurs de formulaire et états vides sont traités ;
- l’interface est responsive et cohérente en clair et sombre ;
- les actions sensibles sont confirmées, atomiques et auditées ;
- les tests pertinents réussissent ;
- aucune donnée sensible n’est ajoutée au dépôt ou aux journaux.

Pour l’assistant IA, la matrice de tests couvre les cinq profils, les dix domaines métier, les réponses avec données, sans données et interdites, ainsi que les synonymes, fautes, questions composées, délais d’expiration et indisponibilités OpenRouter.

## 29. Traçabilité des évolutions

| Domaine | Couverture fonctionnelle |
|---|---|
| Authentification, rôles, organisations | E1–E2 |
| Projets et affectations | E3 |
| Étapes et calendrier | E4 |
| Stocks et mouvements | E5 |
| Documents, photos et commentaires | E6 |
| Paiements, retraits et finances | E7 |
| Rapports PDF et exports | E8 |
| Administration et sécurité | E9 |
| UX, identité visuelle, langues, thèmes et responsive | E10 |
| Super-administration personnalisée | E11 |
| Actions administratives contrôlées et modales | E12 |
| Assistant IA OpenRouter sécurisé par rôle | E13 |
| Routage sémantique et réponses métier déterministes | E14 |

Les descriptions détaillées et critères d’acceptation de chaque Epic et Story restent maintenus dans `_bmad-output/planning-artifacts/backlog/EPICS_AND_STORIES.md` ; le présent document exprime la vision fonctionnelle consolidée destinée au produit, aux utilisateurs, au développement et à la recette.
