# PIVOT-SASS — Questions ouvertes

## Décisions validées le 2026-08-14

- Refonte moderne de PIVOT.
- SaaS multi-entreprise avec isolation stricte.
- Client : consultation, paiement, documents et commentaires.
- Responsable de chantier : étapes, stock, documents et commentaires.
- Ingénieur : gestion complète et validation des documents/du stock.
- Administrateur : gestion globale et recours.
- XAF comme devise initiale ; MeSomb comme intégration de paiement initiale.
- Python/Django et templates Django imposés ; pas de framework applicatif frontend séparé.
- SQLite3 retenu pour le démarrage et le développement ; migration vers PostgreSQL prévue avant une production SaaS à forte concurrence.
- Isolation multi-entreprise initiale par lignes partagées portant `organization_id`.

## Critiques — à trancher avant l'architecture finale

1. **Abonnements** — La première version facture-t-elle les organisations ou l'abonnement reste-t-il administré manuellement ?
2. **Retraits** — Quels sont les statuts, acteurs, validations et justificatifs d'un retrait ?
3. **Paiements** — Quels opérateurs MeSomb sont activés et quelle procédure de remboursement/annulation appliquer ?
4. **Rapports** — Quel est le contenu contractuel du rapport hebdomadaire, sa langue, son fuseau horaire et sa période de référence ?
5. **Cycle projet** — Quelles transitions de statut sont autorisées et qui peut rouvrir un projet terminé ?
6. **Migration** — Les données, comptes, fichiers et historiques de l'application Django existante doivent-ils être importés ?

## Importantes — à trancher avant le découpage complet

8. L'inscription client publique reste-t-elle ouverte ou uniquement sur invitation ?
9. Un ingénieur peut-il appartenir à plusieurs entreprises ou équipes ?
10. Un utilisateur peut-il cumuler plusieurs rôles ?
11. Quelles règles d'arrondi s'appliquent aux montants XAF ?
12. Les quantités de stock peuvent-elles être fractionnaires ou négatives ?
13. Quels formats et tailles maximales sont permis pour les documents et images ?
14. Faut-il versionner les documents ou seulement conserver la dernière version ?
15. Quelle politique de suppression et de conservation s'applique aux données et fichiers ?
16. Quelles notifications sont réellement nécessaires : e-mail, SMS, in-app ou aucune ?
17. Le thème sombre, le RTL et le panneau de personnalisation font-ils partie du produit ou seulement de l'ancien thème ?

## Non bloquantes pour le cadrage initial

18. Faut-il une recherche globale réellement fonctionnelle ?
19. Faut-il afficher des statistiques avancées sur les tableaux de bord ?
20. Les rapports et exports doivent-ils être générés immédiatement ou en tâche de fond ?
21. Quelles langues l'interface doit-elle supporter ?
22. Quels navigateurs et tailles d'écran sont officiellement supportés ?
