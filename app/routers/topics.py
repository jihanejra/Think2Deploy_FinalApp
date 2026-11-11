"""
Thèmes BERTopic calculés chaque nuit par le DAG Airflow.

Par défaut, la dernière exécution publiée ; `run_id` permet de consulter l'historique.
Les filtres recalculent la taille et la satisfaction de chaque thème sur le sous-ensemble
(ex. les thèmes des formations SAP), sans ré-entraîner le modèle.
"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import EvaluationFilters, evaluation_filters, get_conn
from app.schemas import Keyword, Topic, TopicDetail, TopicList, TopicRun
from app.security import require_rh
from pipeline import db

router = APIRouter(prefix="/topics", tags=["Thèmes (BERTopic)"], dependencies=[Depends(require_rh)])


def _resolve_run(conn, run_id):
    if run_id is None:
        run = db.latest_published_run(conn)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Aucune analyse publiée : le DAG n'a pas encore produit de thèmes")
        return run
    run = conn.execute("SELECT * FROM topic_runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Exécution inconnue : {run_id}")
    return run


def _topic_stats(conn, run_id, filters, topic_id=None):
    """Taille et notes moyennes de chaque thème, sur les évaluations filtrées"""
    where, params = filters.where()
    clauses = ["a.run_id = ?"] + ([where[len("WHERE "):]] if where else [])
    params = [run_id] + params
    if topic_id is not None:
        clauses.append("a.topic_id = ?")
        params.append(topic_id)
    return conn.execute(
        "SELECT a.topic_id, COUNT(*) AS size, AVG(e.satisfaction) AS sat, AVG(e.note_moyenne) AS note "
        "FROM topic_assignments a JOIN evaluations e ON e.evaluation_id = a.evaluation_id "
        f"WHERE {' AND '.join(clauses)} GROUP BY a.topic_id", params).fetchall()


def _round(x):
    return None if x is None else round(x, 3)


def _topic_out(meta, stats, n_documents):
    return Topic(
        topic_id=meta["topic_id"],
        label=meta["label"],
        keywords=[Keyword(word=w, score=round(s, 4)) for w, s in json.loads(meta["keywords"])],
        size=stats["size"],
        share=round(stats["size"] / n_documents, 4) if n_documents else 0.0,
        avg_satisfaction=_round(stats["sat"]),
        avg_note=_round(stats["note"]),
    )


@router.get("", response_model=TopicList, summary="Thèmes de la dernière analyse publiée")
def list_topics(
    run_id: Optional[str] = Query(None, description="Exécution à consulter (défaut : dernière publiée)"),
    filters: EvaluationFilters = Depends(evaluation_filters),
    conn=Depends(get_conn),
):
    run = _resolve_run(conn, run_id)
    stats = {r["topic_id"]: r for r in _topic_stats(conn, run["run_id"], filters)}
    metas = {r["topic_id"]: r for r in conn.execute(
        "SELECT * FROM topics WHERE run_id = ?", (run["run_id"],))}
    n_documents = sum(r["size"] for r in stats.values())

    topics = [_topic_out(metas[t], s, n_documents) for t, s in stats.items() if t != -1]
    topics.sort(key=lambda t: t.size, reverse=True)
    return TopicList(run=TopicRun.from_row(run), n_documents=n_documents,
                     n_outliers=stats[-1]["size"] if -1 in stats else 0, topics=topics)


@router.get("/runs", response_model=List[TopicRun], summary="Historique des exécutions BERTopic")
def list_runs(limit: int = Query(30, ge=1, le=200), conn=Depends(get_conn)):
    rows = conn.execute("SELECT * FROM topic_runs ORDER BY created_at DESC LIMIT ?", (limit,))
    return [TopicRun.from_row(r) for r in rows]


@router.get("/{topic_id}", response_model=TopicDetail, summary="Détail d'un thème")
def get_topic(
    topic_id: int,
    run_id: Optional[str] = Query(None),
    examples: int = Query(5, ge=1, le=50, description="Nombre de commentaires d'exemple"),
    filters: EvaluationFilters = Depends(evaluation_filters),
    conn=Depends(get_conn),
):
    run = _resolve_run(conn, run_id)
    meta = conn.execute("SELECT * FROM topics WHERE run_id = ? AND topic_id = ?",
                        (run["run_id"], topic_id)).fetchone()
    if meta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Thème {topic_id} introuvable")

    all_stats = _topic_stats(conn, run["run_id"], filters)
    n_documents = sum(r["size"] for r in all_stats)
    stats = next((r for r in all_stats if r["topic_id"] == topic_id),
                 {"size": 0, "sat": None, "note": None})

    where, params = filters.where()
    base = ("FROM topic_assignments a JOIN evaluations e ON e.evaluation_id = a.evaluation_id "
            "WHERE a.run_id = ? AND a.topic_id = ?" + (" AND " + where[len("WHERE "):] if where else ""))
    base_params = [run["run_id"], topic_id] + params

    def counts(column):
        return {r[0]: r[1] for r in conn.execute(
            f"SELECT e.{column}, COUNT(*) {base} AND e.{column} IS NOT NULL "
            f"GROUP BY e.{column} ORDER BY 2 DESC", base_params)}

    rows = conn.execute(
        f"SELECT e.evaluation_id, e.commentaire, a.probability, e.satisfaction, e.type_formation, "
        f"e.date {base} ORDER BY a.probability DESC LIMIT ?", base_params + [examples]).fetchall()

    return TopicDetail(run_id=run["run_id"], topic=_topic_out(meta, stats, n_documents),
                       sentiment=counts("sentiment"), by_type=counts("type_formation"),
                       examples=[dict(r) for r in rows])
