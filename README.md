# La gazette

[![CI](https://github.com/Koussai21/Projet_la_gazette_2/actions/workflows/ci.yml/badge.svg)](https://github.com/Koussai21/Projet_la_gazette_2/actions/workflows/ci.yml)

Chaque matin à 7 h, une édition qui montre de quoi parle la presse française : les thèmes du jour,
les journaux qui les traitent et les liens pour lire la suite. On ne résume pas les articles, on les
regroupe par thèmes. Le besoin, le périmètre et la stack : [docs/cadrage.md](docs/cadrage.md).

## Démarrage rapide

Prérequis : [Docker](https://docs.docker.com/get-docker/) avec Compose v2, et git. Sous Windows,
passer par WSL. Rien d'autre à installer : Python, PostgreSQL et Prefect tournent dans des conteneurs.

```bash
git clone https://github.com/Koussai21/Projet_la_gazette_2.git && cd Projet_la_gazette_2
bin/dev                       # ou : bin/dev --source liberation  (premier passage sur une seule source)
```

`bin/dev` :

1. construit l'image et démarre PostgreSQL, le serveur Prefect et le pipeline planifié ;
2. fait tout de suite un premier passage : collecte → nettoyage → contrôles → thèmes
   (le premier run télécharge le modèle d'embeddings dans `modeles/`, ça prend un moment) ;
3. affiche l'état des sources :

```
source        état     dernière réussite     échecs  passages        sommeils  articles
ladepeche     actif    2026-10-22 10:20 UTC  0       1 (0 en échec)  0         100
lemonde       actif    2026-10-22 10:08 UTC  0       8 (0 en échec)  0         19
lesechos      retirée  jamais                3       3 (3 en échec)  1         0
…
- lesechos : HTTP 403
```

Une source `SOMMEIL` a échoué 3 fois de suite et n'est plus interrogée ; une source `retirée`
n'est plus dans `sources.csv` mais garde son historique.

Ensuite, le pipeline repasse tout seul toutes les 30 min. Pour voir ce qui se passe :

| Quoi | Où |
|---|---|
| Interface Prefect (historique des passages) | http://localhost:4200 |
| Journaux (une ligne JSON par source et par passage) | `docker compose logs -f collecteur` |
| Articles bruts | `articles_bruts/<source>/<id>.json` |
| Rapport de qualité du jour | `rapports/qualite-AAAA-MM-JJ.md` ([comment le lire](docs/qualite.md)) |
| Thèmes du jour | `docker compose run --rm collecteur themes-du-jour` |
| Artefacts des runs de regroupement | `runs/` |

Tout arrêter : `docker compose down` (ajouter `-v` pour effacer aussi la base).

## Ce que fait le pipeline

À chaque passage (toutes les 30 min), orchestré par Prefect ([src/gazette/flows.py](src/gazette/flows.py)) :

- **collecte** : les flux RSS de [sources.csv](sources.csv) sont lus poliment (ETag, backoff), et
  chaque nouvel article est écrit une seule fois dans `articles_bruts/` ;
- **nettoyage** : chaque article est normalisé et passe les règles d'exclusion de
  [regles.toml](regles.toml) (publi, horoscope, programme TV, doublons…), puis va dans la table
  `articles_propres` ou dans `rejets`, avec la règle qui l'a écarté
  ([contrat des données](docs/donnees.md)) ;
- **contrôles** : des contrôles de qualité vérifient les vraies données et alertent l'équipe si un
  fait est faux ;
- **rapport** : ce qui a été rejeté, par règle et par source ;
- **thèmes** (une fois par jour, après 6 h 30) : les articles propres des dernières 24 h sont
  vectorisés (fastembed), regroupés (HDBSCAN) et nommés par leurs mots-clés. Chaque run est tracé
  (données, paramètres, métriques, artefacts) : [docs/mlops.md](docs/mlops.md) ;
- **rétention** : purge selon les durées de conservation.

## Commandes

Toutes passent par `docker compose run --rm collecteur <commande>` :

| Commande | Rôle |
|---|---|
| `collecter [--source X]` | un passage de collecte tout de suite |
| `nettoyer` | brut → `articles_propres` / `rejets`, puis rapport |
| `rejouer` | repasse les rejets d'une règle modifiée |
| `controler` | contrôles de qualité et alerte |
| `rapport` | réécrit le rapport de qualité |
| `themes` | un run de regroupement tracé |
| `themes-du-jour` | les thèmes du dernier run réussi |
| `runs` | les derniers runs |
| `tracer` | sort, source et item brut d'un article |
| `etat` | état de chaque source |
| `reveiller` | sort une source du sommeil |
| `purger` | applique la rétention |
| `migrer` | applique les migrations en attente |

`--help` sur chaque commande donne ses options. Le quotidien (réveil d'une source, fréquence) est
détaillé dans [docs/orchestration.md](docs/orchestration.md).

## Configuration

Les valeurs par défaut suffisent en local. Pour les changer, créer un fichier `.env` à la racine
(jamais commité) :

| Variable | Défaut | Rôle |
|---|---|---|
| `GAZETTE_INTERVALLE_MIN` | `30` | minutes entre deux passages |
| `GAZETTE_DELAI_MIN` | `10` | délai minimal entre deux requêtes à une même source |
| `GAZETTE_ALERTE_WEBHOOK` | vide | webhook Discord ou Slack pour les alertes qualité |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `gazette` | identifiants de la base locale |

Le regroupement se règle dans [config/clustering.yaml](config/clustering.yaml) (et
[config/mots_vides.txt](config/mots_vides.txt)) ; les règles d'exclusion dans
[regles.toml](regles.toml) ; les flux dans [sources.csv](sources.csv).

## Tester

```bash
bin/test
```

Lint (ruff) et tests (pytest) dans un conteneur, avec une vraie base PostgreSQL (dans un schéma
jetable, jamais celui de dev). Les tests n'utilisent jamais Internet : flux enregistrés dans
`tests/fixtures/`, et un serveur HTTP local qui joue l'éditeur (503, 404, ETag…). Parmi eux :

- `test_deux_passages_zero_doublon` : deux passages de suite n'écrivent aucun doublon ;
- `test_source_en_panne_mise_en_sommeil` : une source qui répond 503 est réessayée avec une
  attente croissante, puis mise en sommeil au troisième passage en échec ;
- `test_nos_dix_pollueurs_sont_ecartes` et `test_de_vrais_articles_sont_gardes` : les règles
  d'exclusion, sur de vrais items ;
- `test_un_fait_faux_declenche_une_alerte_une_seule_fois` : les contrôles de qualité et leur alerte ;
- `test_vrai_modele_sur_dix_articles`, `test_meme_entree_memes_themes` : les embeddings et la
  reproductibilité des runs de regroupement.

## Arborescence

```
src/gazette/          le code (python -m gazette <commande>)
  cli.py                les commandes ci-dessus
  flows.py              orchestration Prefect : un passage, ses tâches, la planification
  pipeline.py           les étapes après la collecte, partagées par la CLI et Prefect
  collecteur.py         un passage : chaque source active, compteurs, mise en sommeil
  fetch.py              requête polie : User-Agent, ETag / Last-Modified, timeouts, backoff
  parser.py             flux RSS / Atom → items bruts
  sources.py            lecture de sources.csv
  stockage.py           articles_bruts/<source>/<id>.json, sans doublon
  normalisation.py      une fonction pure par transformation (HTML, encodage, dates…)
  regles.py             règles d'exclusion R01…R15 et dédoublonnage
  nettoyage.py          brut → articles_propres / rejets
  controles.py          contrôles de qualité, alerte (alertes.py)
  rapport.py            rapport de qualité du jour
  retention.py          purge selon les durées de conservation
  embeddings.py         titre + extrait → vecteur (fastembed), cache en base
  themes.py             regroupement HDBSCAN, nommage, runs tracés
  db.py                 PostgreSQL : connexion, migrations
  config.py, journal.py réglages (environnement) et journaux JSON
  migrations/           migrations SQL versionnées
tests/                tests pytest et flux enregistrés (fixtures/)
docs/                 cadrage, veille, données, flux, orchestration, qualité, CI/CD, MLOps
infra/                infrastructure as code (à venir)
bin/                  dev et test : les deux seules commandes à connaître
config/               paramètres du regroupement et mots vides
Dockerfile            multi-étapes : builder → test → runtime (non root)
docker-compose.yml    PostgreSQL, Prefect, pipeline planifié, tests
sources.csv           les 9 flux retenus
regles.toml           motifs et seuils des règles d'exclusion
```

Créés au premier lancement (hors dépôt) : `articles_bruts/`, `rapports/`, `modeles/`, `runs/`.

## Intégration continue

Chaque push sur `main` lance [la CI](.github/workflows/ci.yml) : lint → tests → build de l'image
→ publication sur `ghcr.io/<propriétaire>/<dépôt>:<AAAAMMJJHHMMSS>-<sha>`. Sur une pull request,
les mêmes étapes tournent, mais l'image n'est pas publiée. La stratégie : [docs/ci-cd.md](docs/ci-cd.md).

## Contribuer

Branches, format des commits, revue, qui merge : [CONTRIBUTING.md](CONTRIBUTING.md).
