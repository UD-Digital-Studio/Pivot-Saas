# Politique de sécurité des preuves PIVOT

- Toute URL de fichier est résolue à travers le projet accessible à l’utilisateur et son organisation. Une URL d’un autre projet répond `404`.
- L’aperçu, le téléchargement et l’export utilisent la règle serveur unique `can_access_evidence` ; masquer un bouton ne constitue jamais une autorisation.
- Par défaut, l’aperçu est réservé aux membres affectés au projet et le téléchargement/export exige l’approbation de la preuve.
- Les coordonnées sont, par défaut, réservées au propriétaire, aux ingénieurs, aux vérificateurs PIVOT et au super administrateur.
- La rétention minimale est de 1 825 jours. Elle est configurable entre 90 et 3 650 jours dans les paramètres du super administrateur. La date affichée est une échéance minimale et n’entraîne aucune suppression automatique.
- Les téléchargements, exports, validations et corrections versionnées sont inscrits dans le journal d’audit avec l’identifiant et la version concernés.
- Une preuve vérifiée ou approuvée reste immuable pendant et après sa période minimale de conservation. Toute rectification passe par une nouvelle version.
