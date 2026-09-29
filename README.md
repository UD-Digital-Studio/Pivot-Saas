# PIVOT-SASS

Application Django de gestion et de suivi de projets de construction.

Le guide de mise en production se trouve dans
[`docs/DEPLOIEMENT_PYTHONANYWHERE.md`](docs/DEPLOIEMENT_PYTHONANYWHERE.md).

## Démarrage local

Prérequis : Python 3.13 et une version compatible de Django.

```powershell
python manage.py migrate
python manage.py runserver
```

La page de contrôle est disponible sur `http://127.0.0.1:8000/health/`.

## Vérifications

```powershell
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
python -m ruff check .
python -m ruff format --check .
```

La configuration de développement utilise SQLite3 dans `pivot.sqlite3`. Ce fichier est local et exclu du versionnement.

## Configuration SMTP et MeSomb

Copiez `.env.example` vers `.env`, puis renseignez uniquement vos vraies valeurs. Le fichier
`.env` est ignoré par Git et chargé automatiquement au démarrage de Django.

Pour les e-mails réels, configurez `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` et le couple TLS/SSL adapté à votre fournisseur.

Pour MeSomb, renseignez `MESOMB_APP_KEY` (ou `MESOMB_APPLICATION_KEY`),
`MESOMB_ACCESS_KEY` et `MESOMB_SECRET_KEY`. Lorsque les trois clés sont présentes,
le fournisseur MeSomb est sélectionné automatiquement. Il peut aussi être imposé avec
`PAYMENT_GATEWAY=mesomb`.

Ne placez jamais de vraies clés dans les fichiers Python ou dans `.env.example`.

### Rapprochement automatique MeSomb

Planifiez la commande suivante toutes les minutes (Planificateur de tâches Windows,
cron ou ordonnanceur de votre hébergeur) afin de traiter les callbacks manqués :

```powershell
python manage.py reconcile_pending_payments --limit 100
```
