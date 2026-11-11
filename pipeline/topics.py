"""
BERTopic : entraînement sur tout le corpus, évaluation, contrôle qualité, publication.

Cycle d'une exécution (run) :
    train_topics()  -> statut 'pending'   (modèle sur disque + résultats en base)
    publish_run()   -> 'published' si le contrôle qualité passe, sinon 'rejected'
L'API ne sert que la dernière exécution 'published'.
"""
import itertools
import json
import os
import shutil
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer

from pipeline import config, db
from pipeline.text import DOMAIN_STOPWORDS, FRENCH_STOPWORDS, TRAINER_ID_PATTERN

# transformers tente de charger TensorFlow s'il est installé (échec avec Keras 3)
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

TOPIC_STOPWORDS = sorted(FRENCH_STOPWORDS | DOMAIN_STOPWORDS)


# ---------------------------------------------------------------------------
# Corpus et modèle
# ---------------------------------------------------------------------------

def load_corpus(conn):
    return pd.read_sql_query(
        "SELECT evaluation_id, commentaire, commentaire_clean, satisfaction, note_moyenne "
        "FROM evaluations WHERE length(commentaire_clean) > ? ORDER BY evaluation_id",
        conn, params=(config.MIN_COMMENT_LENGTH,))


def build_topic_model(embedding_model, min_topic_size=8, n_top_words=10, nr_topics=None):
    """
    - UMAP : réglages par défaut de BERTopic + graine fixe -> résultats reproductibles
    - HDBSCAN : min_samples=3 -> peu de commentaires rejetés en thème -1
    - CountVectorizer : mots vides FR + domaine retirés, paires de mots gardées
    """
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from umap import UMAP

    return BERTopic(
        embedding_model=embedding_model,
        umap_model=UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine",
                        random_state=config.SEED),
        hdbscan_model=HDBSCAN(min_cluster_size=min_topic_size, min_samples=min(3, min_topic_size),
                              metric="euclidean", cluster_selection_method="eom",
                              prediction_data=True),
        vectorizer_model=CountVectorizer(stop_words=TOPIC_STOPWORDS, ngram_range=(1, 2)),
        # Sinon BERTopic (défaut "english") supprime les caractères accentués
        language="multilingual",
        top_n_words=n_top_words,
        nr_topics=nr_topics,
        calculate_probabilities=True,
        verbose=False,
    )


# ---------------------------------------------------------------------------
# Évaluation
# ---------------------------------------------------------------------------

def npmi_coherence(words_per_topic, docs):
    """
    Cohérence NPMI moyenne (-1 à 1) : les mots d'un thème apparaissent-ils ensemble
    dans les mêmes commentaires ? Les paires de mots sont découpées en mots simples.
    """
    cv = CountVectorizer(binary=True)
    X = cv.fit_transform(docs).tocsc()
    vocab = cv.vocabulary_
    n_docs = X.shape[0]
    doc_freq = np.asarray(X.sum(axis=0)).ravel()

    scores = []
    for words in words_per_topic:
        tokens = list(dict.fromkeys(t for w in words for t in w.split() if t in vocab))[:10]
        pair_scores = []
        for a, b in itertools.combinations(tokens, 2):
            ia, ib = vocab[a], vocab[b]
            p_ab = X[:, ia].multiply(X[:, ib]).sum() / n_docs
            if p_ab == 0:
                pair_scores.append(-1.0)
            elif p_ab == 1:
                pair_scores.append(1.0)
            else:
                p_a, p_b = doc_freq[ia] / n_docs, doc_freq[ib] / n_docs
                pair_scores.append(np.log(p_ab / (p_a * p_b)) / -np.log(p_ab))
        if pair_scores:
            scores.append(np.mean(pair_scores))
    return float(np.mean(scores)) if scores else float("nan")


def evaluate_topics(keywords_per_topic, docs, topics):
    """Métriques intrinsèques (un modèle de thèmes n'a pas de vérité terrain)"""
    topics = np.asarray(topics)
    words = [[w for w, _ in kw] for kw in keywords_per_topic]
    flat = [w for ws in words for w in ws]
    return {
        "n_topics": len(words),
        "outlier_ratio": float(np.mean(topics == -1)),
        "coherence": npmi_coherence(words, docs) if words else float("nan"),
        "diversity": len(set(flat)) / len(flat) if flat else float("nan"),
    }


def check_quality(metrics, gate=None):
    """Renvoie la liste des critères non respectés (vide = publiable)"""
    gate = gate or config.QUALITY_GATE
    failures = []
    if metrics["n_topics"] < gate["min_topics"]:
        failures.append(f"{metrics['n_topics']} thèmes < {gate['min_topics']}")
    if not metrics["coherence"] >= gate["min_coherence"]:   # NaN échoue aussi
        failures.append(f"cohérence {metrics['coherence']:.3f} < {gate['min_coherence']}")
    if metrics["outlier_ratio"] > gate["max_outlier_ratio"]:
        failures.append(f"non classés {metrics['outlier_ratio']:.0%} > {gate['max_outlier_ratio']:.0%}")
    return failures


# ---------------------------------------------------------------------------
# Cycle d'une exécution
# ---------------------------------------------------------------------------

def needs_retrain(n_inserted, force=False):
    """Ré-entraîner si de nouvelles évaluations sont arrivées, ou si rien n'est encore publié"""
    if force or n_inserted > 0:
        return True
    with db.session() as conn:
        latest = db.latest_published_run(conn)
        if latest is None:
            return True
        # Corpus modifié en dehors de l'ingestion (re-prétraitement, correction manuelle...)
        return len(load_corpus(conn)) != latest["n_documents"]


def train_topics(params=None):
    """Entraîne BERTopic sur tout le corpus ; renvoie le run_id (statut 'pending')"""
    from sentence_transformers import SentenceTransformer

    params = {**config.TOPIC_PARAMS, **(params or {})}
    with db.session() as conn:
        corpus = load_corpus(conn)
    if len(corpus) < config.MIN_DOCUMENTS:
        raise ValueError(f"{len(corpus)} commentaires exploitables, minimum {config.MIN_DOCUMENTS}")

    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    docs = corpus["commentaire_clean"].tolist()
    # Le modèle de phrases comprend mieux le texte d'origine ; les mots-clés viennent du texte nettoyé
    raw = [TRAINER_ID_PATTERN.sub("", str(t)) for t in corpus["commentaire"].fillna("")]

    embedding_model = SentenceTransformer(config.EMBEDDING_MODEL_NAME, device="cpu")
    embeddings = embedding_model.encode(raw, show_progress_bar=False)
    topic_model = build_topic_model(embedding_model, **params)
    topics, probabilities = topic_model.fit_transform(docs, embeddings=embeddings)

    corpus["topic_id"] = topics
    corpus["probability"] = (probabilities.max(axis=1) if probabilities is not None
                             and probabilities.ndim == 2 else probabilities)
    topic_ids = sorted(set(topics))
    keywords = {t: [(w, float(s)) for w, s in (topic_model.get_topic(t) or [])] for t in topic_ids}
    metrics = evaluate_topics([keywords[t] for t in topic_ids if t != -1], docs, topics)

    # Modèle au format safetensors, sans le modèle d'embeddings (seulement son nom) : ~100 Ko
    model_path = config.MODELS_DIR / run_id
    topic_model.save(str(model_path), serialization="safetensors", save_ctfidf=True,
                     save_embedding_model=config.EMBEDDING_MODEL_NAME)

    with db.session() as conn:
        conn.execute(
            "INSERT INTO topic_runs (run_id, created_at, status, n_documents, n_topics, "
            "outlier_ratio, coherence, diversity, params, model_path) "
            "VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
            (run_id, datetime.now().isoformat(timespec="seconds"), len(corpus),
             metrics["n_topics"], metrics["outlier_ratio"], metrics["coherence"],
             metrics["diversity"], json.dumps(params),
             # Relatif au dossier de données : identique en local et dans les conteneurs
             model_path.relative_to(config.DATA_DIR).as_posix()))

        groups = corpus.groupby("topic_id")
        conn.executemany(
            "INSERT INTO topics (run_id, topic_id, label, keywords, size, avg_satisfaction, avg_note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(run_id, int(t),
              "Non classés" if t == -1 else ", ".join(w for w, _ in keywords[t][:3]),
              json.dumps(keywords[t], ensure_ascii=False),
              int(len(g)),
              _float_or_none(g["satisfaction"].mean()),
              _float_or_none(g["note_moyenne"].mean()))
             for t, g in groups])

        conn.executemany(
            "INSERT INTO topic_assignments (run_id, evaluation_id, topic_id, probability) "
            "VALUES (?, ?, ?, ?)",
            [(run_id, int(r.evaluation_id), int(r.topic_id), _float_or_none(r.probability))
             for r in corpus.itertuples()])
    return run_id


def _float_or_none(x):
    return None if x is None or pd.isna(x) else float(x)


def publish_run(run_id, gate=None):
    """Contrôle qualité puis publication ; renvoie {'run_id', 'status', 'failures'}"""
    with db.session() as conn:
        run = conn.execute("SELECT * FROM topic_runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"exécution inconnue : {run_id}")
        metrics = {k: run[k] if run[k] is not None else float("nan")
                   for k in ("n_topics", "outlier_ratio", "coherence", "diversity")}
        failures = check_quality(metrics, gate)
        status = "rejected" if failures else "published"
        conn.execute(
            "UPDATE topic_runs SET status = ?, message = ?, published_at = ? WHERE run_id = ?",
            (status, "; ".join(failures) or None,
             datetime.now().isoformat(timespec="seconds") if status == "published" else None,
             run_id))
    return {"run_id": run_id, "status": status, "failures": failures, **metrics}


def cleanup_runs(keep=None):
    """Garde les `keep` dernières exécutions publiées ; supprime les autres (base + modèles)"""
    keep = keep or config.KEEP_PUBLISHED_RUNS
    with db.session() as conn:
        kept = {r["run_id"] for r in conn.execute(
            "SELECT run_id FROM topic_runs WHERE status = 'published' "
            "ORDER BY published_at DESC LIMIT ?", (keep,))}
        # Les exécutions 'pending' récentes peuvent être en cours : on ne touche qu'aux anciennes
        to_delete = [r for r in conn.execute(
            "SELECT run_id, status, model_path, created_at FROM topic_runs")
            if r["run_id"] not in kept
            and (r["status"] != "pending" or r["created_at"] < _days_ago(1))]
        for r in to_delete:
            conn.execute("DELETE FROM topic_runs WHERE run_id = ?", (r["run_id"],))
            if r["model_path"]:
                shutil.rmtree(config.DATA_DIR / r["model_path"], ignore_errors=True)
    return len(to_delete)


def _days_ago(days):
    return (datetime.now() - pd.Timedelta(days=days)).isoformat(timespec="seconds")
