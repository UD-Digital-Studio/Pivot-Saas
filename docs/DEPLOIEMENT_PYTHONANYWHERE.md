# Déployer PIVOT avec GitHub et PythonAnywhere

## 1. Créer le dépôt dans l'organisation GitHub

Dans GitHub, ouvrez l'organisation cible, puis **New repository** :

- nom conseillé : `pivot-sass` ;
- visibilité : privée ;
- ne créez ni README, ni `.gitignore`, ni licence à cette étape.

Depuis le dossier local du projet :

```powershell
git init
git add .
git commit -m "Initialisation de PIVOT"
git branch -M main
git remote add origin https://github.com/NOM_ORGANISATION/pivot-sass.git
git push -u origin main
```

Avant le premier `push`, vérifier impérativement que `.env`, les bases SQLite et `media/`
ne figurent pas dans `git status`.

## 2. Préparer PythonAnywhere

Pour PIVOT, un compte PythonAnywhere payant est fortement recommandé : MeSomb,
OpenRouter et le serveur SMTP nécessitent des connexions Internet sortantes, tandis que
les comptes gratuits sont limités aux domaines autorisés par PythonAnywhere. Les tâches
persistantes nécessaires à un rapprochement de paiements fréquent sont également une
fonction payante.

Dans **Account > System image**, utiliser l'image `innit`, qui permet Python 3.13. Dans
une console Bash :

```bash
cd ~
git clone https://github.com/NOM_ORGANISATION/pivot-sass.git PIVOT-SASS
python3.13 -m venv ~/.virtualenvs/pivot
source ~/.virtualenvs/pivot/bin/activate
python -m pip install --upgrade pip
pip install -r ~/PIVOT-SASS/requirements.txt
```

Pour un dépôt privé, utiliser l'authentification GitHub proposée par GitHub. Ne jamais
placer un jeton dans une commande conservée dans l'historique du terminal.

## 3. Créer les variables de production

Créer `/home/VOTRE_IDENTIFIANT/PIVOT-SASS/.env` depuis `.env.example`, puis définir au
minimum :

```dotenv
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=UNE_LONGUE_VALEUR_ALEATOIRE
DJANGO_ALLOWED_HOSTS=VOTRE_IDENTIFIANT.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://VOTRE_IDENTIFIANT.pythonanywhere.com
DJANGO_DB_PATH=/home/VOTRE_IDENTIFIANT/PIVOT-SASS/pivot.sqlite3
APP_BASE_URL=https://VOTRE_IDENTIFIANT.pythonanywhere.com
OPENROUTER_SITE_URL=https://VOTRE_IDENTIFIANT.pythonanywhere.com
```

Ajouter ensuite les identifiants SMTP, MeSomb et OpenRouter. Ce fichier ne doit jamais
être envoyé sur GitHub.

## 4. Initialiser Django

```bash
cd ~/PIVOT-SASS
source ~/.virtualenvs/pivot/bin/activate
python manage.py check --deploy --settings=config.settings.production
python manage.py migrate --settings=config.settings.production
python manage.py collectstatic --noinput --settings=config.settings.production
```

Ne pas exécuter de commande de seeds en production sauf si ces données de démonstration
sont réellement souhaitées.

## 5. Configurer l'application Web

Dans **Web**, créer une application avec **Manual configuration** et Python 3.13.

- Source code : `/home/VOTRE_IDENTIFIANT/PIVOT-SASS`
- Working directory : `/home/VOTRE_IDENTIFIANT/PIVOT-SASS`
- Virtualenv : `/home/VOTRE_IDENTIFIANT/.virtualenvs/pivot`

Ouvrir le fichier WSGI indiqué par PythonAnywhere et y copier le contenu de
`deploy/pythonanywhere_wsgi.py`, après remplacement de `VOTRE_IDENTIFIANT`.

Dans la section **Static files**, ajouter :

| URL | Répertoire |
| --- | --- |
| `/static/` | `/home/VOTRE_IDENTIFIANT/PIVOT-SASS/staticfiles` |
| `/media/` | `/home/VOTRE_IDENTIFIANT/PIVOT-SASS/media` |

Recharger ensuite l'application avec le bouton **Reload**.

## 6. Mettre à jour la production

```bash
cd ~/PIVOT-SASS
git pull origin main
source ~/.virtualenvs/pivot/bin/activate
pip install -r requirements.txt
python manage.py migrate --settings=config.settings.production
python manage.py collectstatic --noinput --settings=config.settings.production
```

Puis cliquer sur **Reload** dans l'onglet Web.

## 7. Paiements en attente

La commande de rapprochement est :

```bash
cd ~/PIVOT-SASS && ~/.virtualenvs/pivot/bin/python manage.py reconcile_pending_payments --limit 100 --settings=config.settings.production
```

L'application clôt déjà les tentatives trop anciennes selon sa configuration. Pour une
vérification automatique fréquente, utiliser une tâche PythonAnywhere compatible avec
le type de compte choisi. Une exécution toutes les deux minutes nécessite un mécanisme
de tâche persistante ou un ordonnanceur offrant cette fréquence ; une tâche quotidienne
ne suffit pas.

## 8. Sauvegardes SQLite et médias

SQLite convient à un premier déploiement à faible trafic. Sauvegarder régulièrement :

- `/home/VOTRE_IDENTIFIANT/PIVOT-SASS/pivot.sqlite3` ;
- `/home/VOTRE_IDENTIFIANT/PIVOT-SASS/media/` ;
- les variables de production dans un gestionnaire de secrets.

À mesure que le trafic et les écritures concurrentes augmentent, prévoir une migration
vers PostgreSQL ou MySQL.
