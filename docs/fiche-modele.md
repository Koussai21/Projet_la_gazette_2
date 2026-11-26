# Fiche Modèle — Regroupement thématique *La Gazette*

## 1. Informations générales
- **Modèle** : Clustering non supervisé d'articles de presse (Embeddings denses normalisés + HDBSCAN + nommage TF-IDF).
- **Objectif** : Regrouper automatiquement les articles propres des dernières 24h en thèmes cohérents pour l'édition quotidienne.
- **Propriétaire** : Équipe Data / MLOps *La Gazette*.

## 2. Données et prétraitement
- **Entrée** : Articles validés dans `articles_propres` (titre + extrait) sur la fenêtre `fenetre_heures`.
- **Représentation** : Vecteurs unitaires L2 + suppression des mots vides (`config/mots_vides.txt`) pour le nommage TF-IDF.

## 3. Métriques et seuils (`config/evaluation.yaml`)
- **Score de Silhouette (cosinus)** : $\ge 0.12$
- **Part de bruit maximale** : $\le 45\%$
- **Nombre de thèmes** : entre $3$ et $25$
- **Part maximale d'un thème (garde-fou thème géant)** : $\le 40\%$
- **Relecture humaine** : Échantillon aléatoire de 10 articles évalué manuellement (objectif $\ge 7/10$).

## 4. Limites connues et surveillance de la dérive
- **Actualité monothématique** : Un événement majeur peut concentrer $> 40\%$ des articles et déclencher un rejet automatique (`recale`).
- **Dépêches courtes** : Les articles très courts basculent plus facilement dans le bruit (`-1`).
- **Dérive** : Une hausse de $+20$ points de bruit par rapport aux 7 derniers runs, ou 2 runs consécutifs en anomalie, marque le run en `revue`.

## 5. Gouvernance : Promotion et Retour arrière
- **Qui décide d'une promotion ?** L'équipe via Pull Request sur `config/clustering.yaml`. La promotion est exécutée automatiquement par GitHub Actions au merge sur `main` après validation des seuils.
- **Retour arrière** : Commande `python -m gazette modele-rollback`, exécutable par tout membre de l'équipe pour restaurer immédiatement la dernière version archivée.