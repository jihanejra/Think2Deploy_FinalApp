import os

import pytest

from pipeline import config, db, ingestion, preprocessing, topics
from pipeline.text import clean_text, sentiment_label
from tests.conftest import insert_run, write_csv

VALID = '301,F011,Tableau,FOR31,5,5.0,4.0,5.0,"Formatrice excellente, je recommande",FR,2025-01-13'


# --- Texte ------------------------------------------------------------------

def test_clean_text_removes_trainer_ids_and_punctuation():
    assert clean_text("Le formateur FOR35 a été très clair !") == "le formateur a été très clair"
    assert clean_text(None) == ""


@pytest.mark.parametrize("text, expected", [
    ("formation excellente et utile", "Positif"),
    ("ce n'est pas utile", "Négatif"),            # négation
    ("manque d'exemples concrets", "Négatif"),
    ("contenu abordé en salle", "Neutre"),
])
def test_sentiment_label(text, expected):
    assert sentiment_label(clean_text(text)) == expected


# --- Ingestion --------------------------------------------------------------

def test_ingestion_splits_valid_duplicate_invalid_and_malformed(data_dir):
    write_csv(data_dir, "lot.csv", [
        VALID,
        VALID,                                                        # doublon dans le fichier
        "302,F010,SAP,FOR28,7,4,4,4,note hors échelle,FR,2025-01-14",
        "303,F010,SAP,FOR28,4,4,4,4,date invalide,FR,pas-une-date",
        "304,F010,SAP,FOR28,4,4,4,4,virgule, non protégée,FR,2025-01-14",  # colonne en trop
        "305,F010,SAP,FOR28,4,,4,4,note manquante,FR,2025-01-14",
    ])
    result = ingestion.ingest_incoming()

    assert result == {"files": 1, "inserted": 2, "duplicates": 0, "rejected_rows": 4,
                      "rejected_files": 0}
    with db.session() as conn:
        row = conn.execute("SELECT * FROM evaluations WHERE evaluation_id = 305").fetchone()
    assert row["note_moyenne"] == 4.0 and row["evaluation_complete"] == 0
    assert not list(config.INCOMING_DIR.glob("*.csv"))                 # fichier archivé
    rejects = next(config.REJECTED_DIR.glob("lot_rejets.csv")).read_text(encoding="utf-8-sig")
    for reason in ("en double", "échelle", "date", "nombre de colonnes"):
        assert reason in rejects


def test_ingestion_is_idempotent(data_dir):
    write_csv(data_dir, "a.csv", [VALID])
    ingestion.ingest_incoming()
    write_csv(data_dir, "a.csv", [VALID])                               # même fichier redéposé
    result = ingestion.ingest_incoming()
    assert result["inserted"] == 0 and result["duplicates"] == 1


def test_file_with_missing_columns_is_rejected_whole(data_dir):
    (config.INCOMING_DIR / "mauvais.csv").write_text("id,note\n1,5\n", encoding="utf-8")
    result = ingestion.ingest_incoming()
    assert result["rejected_files"] == 1
    assert (config.REJECTED_DIR / "mauvais.csv").exists()


def test_preprocessing_is_incremental(data_dir):
    write_csv(data_dir, "a.csv", [VALID])
    ingestion.ingest_incoming()
    assert preprocessing.preprocess_pending() == 1
    assert preprocessing.preprocess_pending() == 0
    with db.session() as conn:
        row = conn.execute("SELECT commentaire_clean, sentiment FROM evaluations").fetchone()
    assert row["commentaire_clean"] == "formatrice excellente je recommande"
    assert row["sentiment"] == "Positif"


# --- Contrôle qualité et cycle des exécutions ----------------------------------

def test_quality_gate():
    good = {"n_topics": 10, "coherence": 0.4, "outlier_ratio": 0.1, "diversity": 0.9}
    assert topics.check_quality(good) == []
    bad = {"n_topics": 2, "coherence": float("nan"), "outlier_ratio": 0.6, "diversity": 0.9}
    assert len(topics.check_quality(bad)) == 3


def test_rejected_run_does_not_replace_published_one(data_dir):
    with db.session() as conn:
        insert_run(conn, "r1", "published", published_at="2024-01-01T02:00:00")
        insert_run(conn, "r2", "pending", n_topics=1)                   # sous le seuil
    assert topics.publish_run("r2")["status"] == "rejected"
    with db.session() as conn:
        assert db.latest_published_run(conn)["run_id"] == "r1"


def test_needs_retrain(data_dir):
    assert topics.needs_retrain(0)                                       # rien de publié
    with db.session() as conn:
        insert_run(conn, "r1", "published", published_at="2024-01-01", n_documents=0)
    assert not topics.needs_retrain(0)                                   # corpus inchangé
    assert topics.needs_retrain(3)
    assert topics.needs_retrain(0, force=True)


def test_cleanup_keeps_latest_published_runs(data_dir):
    with db.session() as conn:
        for i in range(5):
            insert_run(conn, f"r{i}", "published", published_at=f"2024-01-0{i + 1}",
                       created_at="2024-01-01")
            (config.MODELS_DIR / f"r{i}").mkdir(parents=True)
    assert topics.cleanup_runs(keep=2) == 3
    assert sorted(p.name for p in config.MODELS_DIR.iterdir()) == ["r3", "r4"]


@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="entraîne BERTopic (~1 min) : RUN_SLOW=1")
def test_full_pipeline_on_seed(data_dir, monkeypatch):
    monkeypatch.setattr(config, "SEED_FILE", config.PROJECT_ROOT / "data/seed/evaluation_formation_francais.csv")
    ingestion.seed_database()
    preprocessing.preprocess_pending()
    result = topics.publish_run(topics.train_topics())
    assert result["status"] == "published", result["failures"]
    assert result["n_topics"] >= 10 and result["coherence"] > 0.3
