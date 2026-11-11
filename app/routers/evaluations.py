from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import EvaluationFilters, evaluation_filters, get_conn
from app.schemas import EvaluationDetail, EvaluationPage
from app.security import require_rh
from pipeline import db

router = APIRouter(prefix="/evaluations", tags=["Évaluations"], dependencies=[Depends(require_rh)])

COLUMNS = ("evaluation_id, formation_id, type_formation, formateur_id, satisfaction, contenu, "
           "logistique, applicabilite, note_moyenne, evaluation_complete, commentaire, "
           "sentiment, langue, date")


@router.get("", response_model=EvaluationPage, summary="Liste paginée des évaluations")
def list_evaluations(
    filters: EvaluationFilters = Depends(evaluation_filters),
    sentiment: Optional[str] = Query(None, pattern="^(Positif|Négatif|Neutre)$"),
    q: Optional[str] = Query(None, min_length=2, description="Recherche dans le commentaire"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    where, params = filters.where(alias="evaluations")
    extra = []
    if sentiment:
        extra.append("sentiment = ?")
        params.append(sentiment)
    if q:
        extra.append("commentaire LIKE ?")
        params.append(f"%{q}%")
    if extra:
        where = (where + " AND " if where else "WHERE ") + " AND ".join(extra)

    total = conn.execute(f"SELECT COUNT(*) FROM evaluations {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM evaluations {where} ORDER BY date DESC, evaluation_id DESC "
        "LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    return EvaluationPage(total=total, limit=limit, offset=offset, items=[dict(r) for r in rows])


@router.get("/{evaluation_id}", response_model=EvaluationDetail, summary="Une évaluation et son thème")
def get_evaluation(evaluation_id: int, conn=Depends(get_conn)):
    row = conn.execute(f"SELECT {COLUMNS} FROM evaluations WHERE evaluation_id = ?",
                       (evaluation_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Évaluation introuvable")
    result = dict(row)

    run = db.latest_published_run(conn)
    if run is not None:
        topic = conn.execute(
            "SELECT a.topic_id, a.probability, t.label FROM topic_assignments a "
            "JOIN topics t ON t.run_id = a.run_id AND t.topic_id = a.topic_id "
            "WHERE a.run_id = ? AND a.evaluation_id = ?", (run["run_id"], evaluation_id)).fetchone()
        if topic is not None:
            result.update(topic_id=topic["topic_id"], topic_label=topic["label"],
                          topic_probability=topic["probability"])
    return result
