# Exploitation des abonnements PIVOT

## Configuration

Les paramètres commerciaux sont lus depuis `.env` :

```env
SUBSCRIPTIONS_ENABLED=true
SUBSCRIPTION_TRIAL_MONTHS=3
SUBSCRIPTION_TRIAL_PLAN_CODE=professional
SUBSCRIPTION_GRACE_DAYS=7
SUBSCRIPTION_NOTICE_DAYS=7,3,1
SUBSCRIPTION_PAYMENT_RECHECK_MINUTES=2
PAYMENT_GATEWAY=mesomb
MESOMB_APPLICATION_KEY=
MESOMB_ACCESS_KEY=
MESOMB_SECRET_KEY=
MESOMB_COUNTRY=CM
MESOMB_CURRENCY=XAF
MESOMB_CONNECT_TIMEOUT=5
MESOMB_READ_TIMEOUT=30
MESOMB_MAX_RETRIES=2
```

Les secrets MeSomb ne doivent jamais être placés dans le dépôt, les templates ou les journaux. Après modification de `.env`, redémarrer le serveur Django et le traitement planifié.

## Tâche planifiée

La commande idempotente à exécuter périodiquement est :

```powershell
python manage.py process_subscriptions
```

Elle vérifie les essais, échéances, périodes de grâce, changements de forfait programmés, notifications et paiements incertains. En production, la planifier toutes les cinq minutes avec le planificateur de tâches Windows, cron ou le scheduler de l’hébergeur, depuis le dossier du projet et avec le même environnement virtuel que Django. Une seule exécution suffit ; les verrous et preuves de livraison empêchent les doubles transitions et notifications.

## Exploitation quotidienne

- Espace organisation : `/tarifs/facturation/`.
- Console opérateur : `/super-admin/abonnements/`.
- Les reçus PDF existent uniquement pour les paiements `success` et portent une référence `PIVOT-…` unique.
- Les paiements d’abonnement restent séparés des paiements et rapports financiers des chantiers.
- Toute intervention manuelle exige un motif et crée un événement d’abonnement ainsi qu’un événement d’audit.
- Une baisse de gamme ne supprime jamais les données dépassant les futurs quotas.

## Incident MeSomb

1. Ne pas demander immédiatement une seconde collecte lorsqu’un paiement est `pending`.
2. Vérifier la présence des trois clés, le pays, la devise et les délais réseau sans afficher les valeurs des clés.
3. Laisser `process_subscriptions` rapprocher automatiquement la transaction ou utiliser « Vérifier le statut ».
4. Un timeout de lecture est considéré comme incertain : la collecte n’est pas répétée, car le téléphone peut déjà avoir été débité.
5. En cas d’indisponibilité durable, conserver la transaction en attente, corriger la connectivité puis relancer la commande.
6. Un refus, une annulation ou un échec ne doit jamais être transformé manuellement en succès. Toute mesure commerciale passe par une intervention auditée du super-admin.

## Désactivation contrôlée du module commercial

Pour neutraliser temporairement les restrictions et empêcher de nouveaux paiements :

1. définir `SUBSCRIPTIONS_ENABLED=false` ;
2. arrêter la tâche planifiée `process_subscriptions` ;
3. redémarrer les processus Django ;
4. vérifier qu’une tentative de paiement affiche « module commercial temporairement désactivé » ;
5. conserver les tables et historiques : aucune migration inverse ni suppression de données n’est nécessaire.

Pour réactiver, remettre `SUBSCRIPTIONS_ENABLED=true`, redémarrer Django, relancer la tâche puis contrôler les abonnements dans la console super-admin.

## Vérifications avant mise en production

```powershell
python manage.py check
python manage.py migrate --noinput
python manage.py test apps.subscriptions.tests
python manage.py process_subscriptions
```

Contrôler ensuite un paiement de faible montant dans l’environnement MeSomb approprié, le reçu, les e-mails, la lecture seule et la réactivation après renouvellement.
