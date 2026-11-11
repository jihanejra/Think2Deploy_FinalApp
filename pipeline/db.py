"""
Stockage SQLite partagé : le pipeline écrit, l'API lit.

Une exécution BERTopic n'est visible qu'une fois publiée (transaction validée +
statut 'published').

Journal en mode DELETE, et non WAL : le WAL repose sur une mémoire partagée
(fichier -shm) qui ne fonctionne pas de façon fiable sur un dossier partagé entre
conteneurs (montage Docker d'un dossier Windows, système de fichiers réseau). En
mode DELETE, un lecteur ne crée aucun fichier : l'API ne fait que lire.
"""
import sqlite3
from contextlib import contextmanager

from pipeline import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id       INTEGER PRIMARY KEY,
    formation_id        TEXT,
    type_formation      TEXT NOT NULL,
    formateur_id        TEXT,
    satisfaction        REAL,
    contenu             REAL,
    logistique          REAL,
    applicabilite       REAL,
    commentaire         TEXT,
    langue              TEXT,
    date                TEXT NOT NULL,          -- AAAA-MM-JJ
    note_moyenne        REAL,
    evaluation_complete INTEGER NOT NULL,
    commentaire_clean   TEXT,                   -- rempli par le prétraitement
    sentiment           TEXT,
    nb_mots             INTEGER,
    preprocessed_at     TEXT,
    source_file         TEXT,
    ingested_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluations_date ON evaluations(date);
CREATE INDEX IF NOT EXISTS idx_evaluations_type ON evaluations(type_formation);
CREATE INDEX IF NOT EXISTS idx_evaluations_pending ON evaluations(preprocessed_at);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name    TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    status       TEXT NOT NULL,                 -- 'success' | 'rejected'
    n_rows       INTEGER NOT NULL DEFAULT 0,
    n_inserted   INTEGER NOT NULL DEFAULT 0,
    n_duplicates INTEGER NOT NULL DEFAULT 0,
    n_rejected   INTEGER NOT NULL DEFAULT 0,
    message      TEXT
);

CREATE TABLE IF NOT EXISTS topic_runs (
    run_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'published', 'rejected')),
    n_documents   INTEGER NOT NULL,
    n_topics      INTEGER,
    outlier_ratio REAL,
    coherence     REAL,
    diversity     REAL,
    params        TEXT NOT NULL,                -- JSON
    model_path    TEXT,
    message       TEXT,
    published_at  TEXT
);

CREATE TABLE IF NOT EXISTS topics (
    run_id           TEXT NOT NULL REFERENCES topic_runs(run_id) ON DELETE CASCADE,
    topic_id         INTEGER NOT NULL,          -- -1 = commentaires non classés
    label            TEXT NOT NULL,
    keywords         TEXT NOT NULL,             -- JSON [[mot, score], ...]
    size             INTEGER NOT NULL,
    avg_satisfaction REAL,
    avg_note         REAL,
    PRIMARY KEY (run_id, topic_id)
);

CREATE TABLE IF NOT EXISTS topic_assignments (
    run_id        TEXT NOT NULL REFERENCES topic_runs(run_id) ON DELETE CASCADE,
    evaluation_id INTEGER NOT NULL,
    topic_id      INTEGER NOT NULL,
    probability   REAL,
    PRIMARY KEY (run_id, evaluation_id)
);
CREATE INDEX IF NOT EXISTS idx_assignments_topic ON topic_assignments(run_id, topic_id);
"""


def connect(db_path=None):
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(db_path=None):
    """Connexion avec commit à la sortie, rollback en cas d'erreur"""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    """Crée les tables si besoin (idempotent)"""
    with session(db_path) as conn:
        conn.executescript(SCHEMA)


def latest_published_run(conn):
    return conn.execute(
        "SELECT * FROM topic_runs WHERE status = 'published' ORDER BY published_at DESC LIMIT 1"
    ).fetchone()
