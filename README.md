# API Évaluations de Formation — FastAPI + Airflow

Dernière version du projet 

- **Airflow** exécute chaque nuit à **2h** le DAG `evaluations_daily` :
  ingestion des CSV déposés, prétraitement, ré-entraînement de BERTopic, contrôle qualité.
- **FastAPI** sert en lecture seule les évaluations, les indicateurs et les thèmes.
- Les deux partagent le dossier `data/` (base SQLite `warehouse.db`, modèles BERTopic).

```
 data/incoming/*.csv ──► [DAG Airflow, 2h] ──► data/warehouse.db ──► [API FastAPI] ──► client
                          ingest                 evaluations           /analytics/*
                          preprocess             topic_runs            /topics/*
                          should_retrain         topics                /evaluations/*
                          train_topics           topic_assignments
                          publish (qualité)
                          cleanup
```

## Structure

```
POC1_Final/
├── pipeline/             
│   ├── config.py         # chemins (EVAL_DATA_DIR), réglages BERTopic, seuils qualité
│   ├── db.py             # schéma SQLite, connexions
│   ├── ingestion.py      # validation et chargement des CSV
│   ├── text.py           # nettoyage, mots vides, sentiment par lexique
│   ├── preprocessing.py  # prétraitement incrémental
│   ├── topics.py         # BERTopic : entraînement, évaluation, publication, nettoyage
│   └── cli.py            # exécution manuelle (même ordre que le DAG)
├── dags/evaluations_daily.py
├── app/                  # API FastAPI
│   ├── main.py, config.py, security.py, dependencies.py, schemas.py
│   └── routers/          # auth, evaluations, analytics, topics, system
├── tests/                # (pytest)
├── docker/               # api.Dockerfile, airflow.Dockerfile
├── docker-compose.yml
└── data/                 # seed/ (jeu initial), incoming/, archive/, rejected/, models/
```

## Lancer avec Docker (Airflow + API)

Prérequis : **Docker Desktop démarré**. Airflow ne fonctionne pas nativement sous Windows,
il tourne dans un conteneur Linux. Environ 5 Go d'espace disque pour les images.

```bash
docker compose up -d --build                                          # 1re fois : construit les images (~10 min)
docker compose exec airflow python -m pipeline.cli init --seed       # 1re fois : charge les 300 évaluations
docker compose exec airflow airflow dags trigger evaluations_daily   # 1re analyse sans attendre 2h
```

- Airflow : http://localhost:8080 (DAG `evaluations_daily`, bouton ▶ pour lancer à la main)
- API : http://localhost:8000/docs (bouton *Authorize* : `rh_user` / `123`)

```bash
docker compose stop        # arrêter (les conteneurs et ./data sont conservés)
docker compose start       # relancer
docker compose logs -f airflow
docker compose down        # supprimer les conteneurs (./data est conservé)
```

Le DAG ne tourne à 2h que si Docker Desktop et le conteneur `airflow` sont démarrés à
cette heure-là. Sinon, la nuit manquée n'est pas rattrapée (`catchup=False`) : lancer le
DAG à la main au redémarrage.

## Lancer sans Docker (développement, Windows)

```bash
python -m venv .venv --system-site-packages
.venv\Scripts\pip install -r requirements-dev.txt --extra-index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pipeline.cli init --seed      # base + jeu initial
.venv\Scripts\python -m pipeline.cli run              # ce que fait le DAG
.venv\Scripts\python -m uvicorn app.main:app --reload  # API sur http://localhost:8000/docs
.venv\Scripts\python -m pytest                        # tests (RUN_SLOW=1 : entraîne BERTopic)
```

## Déposer de nouvelles évaluations

Copier un CSV dans `data/incoming/`, avec les colonnes du jeu initial :
`evaluation_id,formation_id,type_formation,formateur_id,satisfaction,contenu,logistique,applicabilite,commentaire,langue,date`.

À la prochaine exécution du DAG :
- les lignes valides sont ajoutées (un `evaluation_id` déjà connu est ignoré, sans erreur) ;
- les lignes invalides (note hors 1-5, date invalide, colonne en trop...) sont écrites dans
  `data/rejected/<fichier>_rejets.csv` avec leur motif ;
- le fichier est déplacé dans `data/archive/AAAA-MM-JJ/`.

## API

Toutes les routes sauf `/health` et `/auth/token` exigent un jeton ; les données sont
réservées au profil RH (les autres profils reçoivent 403).

| Route | Rôle |
|---|---|
| `POST /auth/token` | connexion (formulaire `username`, `password`) → jeton JWT valable 60 min |
| `GET /auth/me` | utilisateur connecté |
| `GET /health` | état du service, sans authentification |
| `GET /evaluations` | liste paginée ; filtres + `sentiment`, `q` (recherche), `limit`, `offset` |
| `GET /evaluations/{id}` | une évaluation et son thème |
| `GET /analytics/summary` | indicateurs clés, évolution mensuelle |
| `GET /analytics/by-type` | indicateurs par type de formation |
| `GET /analytics/timeseries` | évolution (`metric`, `granularity` : day, week, month, quarter) |
| `GET /analytics/trainers` | classement des formateurs (`min_evaluations`) |
| `GET /analytics/sentiment` | répartition du sentiment et satisfaction associée |
| `GET /topics` | thèmes de la dernière analyse publiée (`run_id` pour l'historique) |
| `GET /topics/{id}` | mots-clés, exemples, sentiment et types de formation d'un thème |
| `GET /topics/runs` | historique des exécutions BERTopic et leurs métriques |
| `GET /pipeline/status` | dernières ingestions et exécutions |

Filtres communs : `type_formation` (répétable), `date_from`, `date_to`, `min_score`.
Sur `/topics`, ils recalculent la taille et la satisfaction des thèmes sur le sous-ensemble.

## Contrôle qualité de BERTopic

Une exécution n'est publiée que si : au moins 3 thèmes, cohérence NPMI ≥ 0,10, au plus
40 % de commentaires non classés (`pipeline/config.py`). Sinon elle est marquée `rejected`,
la tâche `publish` échoue (visible en rouge dans Airflow) et l'API continue de servir
l'exécution précédente.

## Limites connues (POC)

- SQLite et Airflow « standalone » : un seul serveur. En production : PostgreSQL,
  le docker-compose officiel d'Airflow, des comptes utilisateurs réels.
- BERTopic est ré-entraîné sur tout le corpus : les numéros de thèmes changent d'une
  exécution à l'autre. Comparer des thèmes dans le temps demanderait de les aligner.
- Les données sont synthétiques (phrases-types), ce qui explique certains thèmes mixtes.
