"""
Configuration partagée par le pipeline (Airflow) et l'API (FastAPI).

Tous les chemins dérivent de EVAL_DATA_DIR : en local, le dossier data/ du projet ;
dans Docker, le volume monté dans les deux conteneurs.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EVAL_DATA_DIR", PROJECT_ROOT / "data"))

DB_PATH = DATA_DIR / "warehouse.db"
INCOMING_DIR = DATA_DIR / "incoming"      # dépôt des nouveaux CSV
ARCHIVE_DIR = DATA_DIR / "archive"        # CSV traités, rangés par jour
REJECTED_DIR = DATA_DIR / "rejected"      # lignes ou fichiers invalides, avec le motif
MODELS_DIR = DATA_DIR / "models"          # un dossier BERTopic (safetensors) par exécution
SEED_FILE = DATA_DIR / "seed" / "evaluation_formation_francais.csv"

EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
SEED = 42

# Réglages BERTopic (justifiés dans le README : configuration retenue après évaluation)
TOPIC_PARAMS = {"min_topic_size": 8, "n_top_words": 10, "nr_topics": None}
MIN_COMMENT_LENGTH = 10   # caractères, après nettoyage
MIN_DOCUMENTS = 30        # en dessous, BERTopic n'est pas ré-entraîné

# Contrôle qualité : une exécution qui échoue n'est pas publiée,
# l'API continue de servir la précédente
QUALITY_GATE = {"min_topics": 3, "min_coherence": 0.10, "max_outlier_ratio": 0.40}

KEEP_PUBLISHED_RUNS = 7   # historique conservé (modèles et résultats)
