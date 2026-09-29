"""Modèle du fichier WSGI à copier dans l'onglet Web de PythonAnywhere.

Remplacez VOTRE_IDENTIFIANT avant utilisation.
"""

import os
import sys


project_home = "/home/VOTRE_IDENTIFIANT/PIVOT-SASS"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

from django.core.wsgi import get_wsgi_application  # noqa: E402


application = get_wsgi_application()
