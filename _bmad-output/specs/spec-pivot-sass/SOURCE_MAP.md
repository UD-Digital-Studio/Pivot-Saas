# PIVOT-SASS — Carte de traçabilité

Source : `C:\Users\GENIUS ELECTRONICS\Documents\PROJET FREELANCE\PIVOT\project\DOCUMENTATION_FONCTIONNELLE_PIVOT.md`

| Sections de la source | Exigences ou sections de la SPEC |
|---|---|
| 1. Présentation générale | Objet, contraintes et héritage |
| 2. Rôles utilisateurs | Acteurs, matrice d'autorisation |
| 3. Authentification et comptes | AUTH-01 à AUTH-09 |
| 4. Gestion des projets | PROJ-01 à PROJ-08 |
| 5. Gestion financière et paiements | FIN-01 à FIN-10 |
| 6. Planning, étapes et calendrier | PLAN-01 à PLAN-08 |
| 7. Gestion du stock | STOCK-01 à STOCK-09 |
| 8. Documents, images et commentaires | COLLAB-01 à COLLAB-08 |
| 9. Rapports et exports | REPORT-01 à REPORT-05 |
| 10–11. Structure des interfaces | Expérience utilisateur, parcours par rôle |
| 12. Modèle de données | Modèle conceptuel |
| 13. Points d'attention | Sécurité, intégrité, anomalies à ne pas reproduire |
| 14. Arborescence du code | Contraintes et héritage observés |
| 15. Parcours utilisateurs | Résultats attendus, critères de succès |

## Nature des ajouts de spécification

Les éléments suivants ne sont pas des fonctionnalités observées, mais des exigences de correction directement motivées par les risques signalés dans la source :

- contrôles d'accès systématiques ;
- protection CSRF ;
- idempotence des paiements ;
- audit des opérations sensibles ;
- montants décimaux et dates typées ;
- mouvements de stock traçables ;
- validation des fichiers et entrées ;
- suppression de la dépendance au `Referer`.

Les fonctionnalités SaaS non présentes dans la source sont maintenues hors périmètre et ne doivent pas être inférées du seul nom « PIVOT-SASS ».
