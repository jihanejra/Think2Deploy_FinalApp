import json
import os

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("API_JWT_SECRET", "secret-de-test")

import pytest

from pipeline import config, db

HEADER = ("evaluation_id,formation_id,type_formation,formateur_id,satisfaction,contenu,"
          "logistique,applicabilite,commentaire,langue,date\n")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Dossier de données isolé pour chaque test"""
    paths = {
        "DATA_DIR": tmp_path,
        "DB_PATH": tmp_path / "warehouse.db",
        "INCOMING_DIR": tmp_path / "incoming",
        "ARCHIVE_DIR": tmp_path / "archive",
        "REJECTED_DIR": tmp_path / "rejected",
        "MODELS_DIR": tmp_path / "models",
    }
    for name, value in paths.items():
        monkeypatch.setattr(config, name, value)
    paths["INCOMING_DIR"].mkdir()
    db.init_db()
    return tmp_path


def write_csv(directory, name, lines):
    path = directory / "incoming" / name
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return path


EVALUATIONS = [
    # id, type, formateur, sat, contenu, logistique, applicabilité, commentaire, sentiment, date
    (1, "SAP", "FOR01", 5, 5, 4, 5, "Excellent formateur, très clair", "Positif", "2024-01-10"),
    (2, "SAP", "FOR01", 4, 4, 4, 4, "Salle confortable et équipée", "Positif", "2024-01-20"),
    (3, "SAP", "FOR02", 2, 2, 3, None, "Rythme trop rapide", "Négatif", "2024-02-05"),
    (4, "Python Data", "FOR02", 1, 2, 2, 1, "Formation décevante", "Négatif", "2024-02-15"),
    (5, "Python Data", "FOR03", 3, 3, 3, 3, "Contenu correct", "Neutre", "2024-02-25"),
]


@pytest.fixture
def populated_db(data_dir):
    """5 évaluations connues + une exécution BERTopic publiée (sans entraîner de modèle)"""
    with db.session() as conn:
        for (eid, typ, trainer, sat, cont, log, app, comment, sentiment, date) in EVALUATIONS:
            scores = [s for s in (sat, cont, log, app) if s is not None]
            conn.execute(
                "INSERT INTO evaluations (evaluation_id, formation_id, type_formation, formateur_id, "
                "satisfaction, contenu, logistique, applicabilite, commentaire, langue, date, "
                "note_moyenne, evaluation_complete, commentaire_clean, sentiment, nb_mots, "
                "preprocessed_at, source_file, ingested_at) "
                "VALUES (?, 'F1', ?, ?, ?, ?, ?, ?, ?, 'FR', ?, ?, ?, ?, ?, 3, '2024-03-01', 'test', '2024-03-01')",
                (eid, typ, trainer, sat, cont, log, app, comment, date,
                 sum(scores) / len(scores), int(len(scores) == 4), comment.lower(), sentiment))
        insert_run(conn, "20240301T020000", "published", published_at="2024-03-01T02:10:00")
        conn.executemany(
            "INSERT INTO topics VALUES ('20240301T020000', ?, ?, ?, ?, NULL, NULL)",
            [(-1, "Non classés", "[]", 1),
             (0, "excellent, clair", json.dumps([["excellent", 0.3], ["clair", 0.2]]), 2),
             (1, "rythme, décevante", json.dumps([["rythme", 0.3], ["décevante", 0.2]]), 2)])
        conn.executemany(
            "INSERT INTO topic_assignments VALUES ('20240301T020000', ?, ?, ?)",
            [(1, 0, 0.9), (2, 0, 0.6), (3, 1, 0.8), (4, 1, 0.7), (5, -1, 0.0)])
    return data_dir


def insert_run(conn, run_id, status, published_at=None, n_documents=5, n_topics=2,
               coherence=0.4, outlier_ratio=0.2, created_at=None):
    conn.execute(
        "INSERT INTO topic_runs (run_id, created_at, status, n_documents, n_topics, outlier_ratio, "
        "coherence, diversity, params, model_path, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0.9, '{}', ?, ?)",
        (run_id, created_at or run_id, status, n_documents, n_topics, outlier_ratio, coherence,
         f"models/{run_id}", published_at))
