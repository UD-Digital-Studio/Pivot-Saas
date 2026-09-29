# Assistant IA PIVOT

## Fonctionnement

L’assistant utilise OpenRouter depuis le serveur Django. Le navigateur ne reçoit jamais la clé
API. Les données métier sont fournies par des outils Django en lecture seule et filtrées selon
l’utilisateur, son organisation, son rôle et ses projets accessibles.

Les rôles client, responsable de chantier, ingénieur, administrateur d’organisation et
super-administrateur n’obtiennent que les explications et données correspondant à leurs droits.
L’assistant ne réalise aucune écriture, validation, suppression ou opération financière.

Le routeur sémantique local reconnaît les synonymes, variantes françaises et anglaises, fautes
courantes et questions composées. Il peut sélectionner plusieurs domaines, mais les contrôles
Django sont exécutés séparément avant chaque lecture. Une intention précise, comme les
utilisateurs d’une organisation, est prioritaire sur le simple domaine organisation.

## Configuration

Copier les variables de `.env.example` dans `.env`, puis renseigner au minimum :

```env
OPENROUTER_ENABLED=true
OPENROUTER_API_KEY=votre-cle
OPENROUTER_MODEL=openrouter/auto
```

Les délais réseau, la taille des réponses, la rétention, le nombre de messages, la fréquence,
le budget de tokens et la fenêtre anti-duplication se règlent avec les variables
`OPENROUTER_*` et `AI_*` documentées dans `.env.example`. Redémarrer Django après modification.
Une requête interrompue est automatiquement libérée après `AI_REQUEST_STALE_SECONDS` afin de ne
pas bloquer définitivement la conversation.

## Désactivation

Définir `OPENROUTER_ENABLED=false`, puis redémarrer Django. L’API de discussion répond alors
indisponible sans créer de conversation ni appeler OpenRouter. Le reste de PIVOT continue de
fonctionner normalement. La clé peut rester configurée pendant une désactivation temporaire.

## Confidentialité et sécurité

- Les prompts ne sont pas enregistrés dans les journaux de supervision.
- Les requêtes sont identifiées par une empreinte HMAC non réversible.
- La supervision ne contient que des agrégats : volume, succès, erreurs, blocages, latence et
  tokens.
- Les secrets, numéros de payeur et champs techniques sensibles sont exclus des outils.
- Les commentaires, documents et autres textes métier sont traités comme données non fiables.
- Les injections, requêtes simultanées, doublons récents et dépassements de quota sont bloqués.
- Les conversations expirent selon `AI_CONVERSATION_RETENTION_DAYS`.

## Supervision et diagnostic

Le tableau de bord du super-administrateur affiche les indicateurs des dernières 24 heures sans
montrer les conversations. Les états possibles sont :

- `operational` : assistant activé, configuré et sans panne générale observée ;
- `degraded` : erreurs récentes sans réussite sur la période ;
- `misconfigured` : activation demandée mais configuration incomplète ;
- `disabled` : désactivation volontaire.

En cas d’incident, vérifier dans cet ordre : état affiché, présence de la clé, modèle choisi,
timeouts, erreurs agrégées et limites utilisateur. Les codes d’erreur stockés correspondent au
type d’incident et ne contiennent ni clé, ni prompt, ni réponse du fournisseur.

## Limites fonctionnelles

Les réponses peuvent être inexactes et doivent être vérifiées. L’assistant ne remplace pas une
validation humaine, ne lit pas un projet inaccessible, ne contourne pas les rôles et ne déclenche
pas d’action. Une absence de données autorisées doit produire une réponse sans donnée inventée.

## Validation

```powershell
python manage.py test apps.ai_assistant
python manage.py check
python manage.py makemigrations --check --dry-run
```
