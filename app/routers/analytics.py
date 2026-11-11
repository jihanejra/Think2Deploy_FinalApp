"""
Indicateurs agrégés, calculés en SQL sur les évaluations filtrées.
"""
from typing import List, Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies import EvaluationFilters, evaluation_filters, get_conn
from app.schemas import SentimentStats, Summary, TimePoint, TrainerStats, TypeStats
from app.security import require_rh

router = APIRouter(prefix="/analytics", tags=["Analyses"], dependencies=[Depends(require_rh)])

CRITERIA = ["satisfaction", "contenu", "logistique", "applicabilite"]

# Literal est validé par FastAPI (422 sinon) : indispensable, car la métrique et la
# période sont insérées dans le SQL. Query(enum=...) ne ferait que les documenter.
Metric = Literal["note_moyenne", "satisfaction", "contenu", "logistique", "applicabilite"]
Granularity = Literal["day", "week", "month", "quarter"]

# Expressions SQL fixes (jamais construites à partir de la saisie de l'utilisateur)
PERIODS = {
    "day": "date",
    "week": "strftime('%Y-S%W', date)",
    "month": "substr(date, 1, 7)",
    "quarter": "substr(date, 1, 4) || '-T' || ((CAST(substr(date, 6, 2) AS INTEGER) + 2) / 3)",
}

CRITERIA_AVG = ", ".join(f"AVG({c}) AS {c}" for c in CRITERIA)


def _round(x, digits=3):
    return None if x is None else round(x, digits)


def _previous_month(month):
    year, m = map(int, month.split("-"))
    return f"{year - 1}-12" if m == 1 else f"{year}-{m - 1:02d}"


@router.get("/summary", response_model=Summary, summary="Indicateurs clés")
def summary(filters: EvaluationFilters = Depends(evaluation_filters), conn=Depends(get_conn)):
    where, params = filters.where()
    row = conn.execute(
        f"SELECT COUNT(*) AS total, SUM(evaluation_complete) AS complete, {CRITERIA_AVG} "
        f"FROM evaluations e {where}", params).fetchone()

    criteria = {c: _round(row[c]) for c in CRITERIA}
    known = [v for v in criteria.values() if v is not None]

    # Dernier mois DES DONNÉES comparé au mois calendaire précédent
    months = dict(conn.execute(
        f"SELECT substr(date, 1, 7), AVG(note_moyenne) FROM evaluations e {where} "
        "GROUP BY 1 ORDER BY 1 DESC LIMIT 2", params).fetchall())
    last_month = max(months) if months else None
    last_score = months.get(last_month)
    previous_score = months.get(_previous_month(last_month)) if last_month else None
    change = ((last_score - previous_score) / previous_score
              if last_score is not None and previous_score else None)

    return Summary(
        total_evaluations=row["total"],
        completion_rate=_round(row["complete"] / row["total"]) if row["total"] else None,
        criteria=criteria,
        overall_score=_round(sum(known) / len(known)) if known else None,
        last_month=last_month,
        last_month_score=_round(last_score),
        monthly_change=_round(change),
    )


@router.get("/by-type", response_model=List[TypeStats], summary="Indicateurs par type de formation")
def by_type(filters: EvaluationFilters = Depends(evaluation_filters), conn=Depends(get_conn)):
    where, params = filters.where()
    rows = conn.execute(
        f"SELECT type_formation, COUNT(*) AS n, AVG(evaluation_complete) AS completion, "
        f"AVG(note_moyenne) AS note, {CRITERIA_AVG} FROM evaluations e {where} "
        "GROUP BY type_formation ORDER BY note DESC", params).fetchall()
    return [TypeStats(type_formation=r["type_formation"], n_evaluations=r["n"],
                      completion_rate=_round(r["completion"]), note_moyenne=_round(r["note"]),
                      criteria={c: _round(r[c]) for c in CRITERIA})
            for r in rows]


@router.get("/timeseries", response_model=List[TimePoint], summary="Évolution dans le temps")
def timeseries(
    metric: Metric = "note_moyenne",
    granularity: Granularity = "month",
    filters: EvaluationFilters = Depends(evaluation_filters),
    conn=Depends(get_conn),
):
    where, params = filters.where()
    period = PERIODS[granularity]
    rows = conn.execute(
        f"SELECT {period} AS period, AVG({metric}) AS value, COUNT(*) AS n "
        f"FROM evaluations e {where} GROUP BY 1 ORDER BY 1", params).fetchall()
    return [TimePoint(period=r["period"], value=_round(r["value"]), n_evaluations=r["n"])
            for r in rows]


@router.get("/trainers", response_model=List[TrainerStats], summary="Classement des formateurs")
def trainers(
    min_evaluations: int = Query(3, ge=1, description="Écarte les formateurs trop peu évalués"),
    limit: int = Query(20, ge=1, le=100),
    filters: EvaluationFilters = Depends(evaluation_filters),
    conn=Depends(get_conn),
):
    where, params = filters.where()
    rows = conn.execute(
        f"SELECT formateur_id, COUNT(*) AS n, AVG(note_moyenne) AS note, "
        f"AVG(satisfaction) AS satisfaction FROM evaluations e {where} "
        f"{'AND' if where else 'WHERE'} formateur_id IS NOT NULL "
        "GROUP BY formateur_id HAVING COUNT(*) >= ? ORDER BY note DESC LIMIT ?",
        params + [min_evaluations, limit]).fetchall()
    return [TrainerStats(rank=i, formateur_id=r["formateur_id"], n_evaluations=r["n"],
                         note_moyenne=_round(r["note"]), satisfaction=_round(r["satisfaction"]))
            for i, r in enumerate(rows, 1)]


@router.get("/sentiment", response_model=List[SentimentStats], summary="Répartition du sentiment")
def sentiment(filters: EvaluationFilters = Depends(evaluation_filters), conn=Depends(get_conn)):
    where, params = filters.where()
    rows = conn.execute(
        f"SELECT sentiment, COUNT(*) AS n, AVG(satisfaction) AS sat FROM evaluations e {where} "
        f"{'AND' if where else 'WHERE'} sentiment IS NOT NULL "
        "GROUP BY sentiment ORDER BY n DESC", params).fetchall()
    total = sum(r["n"] for r in rows)
    return [SentimentStats(sentiment=r["sentiment"], n_evaluations=r["n"],
                           share=_round(r["n"] / total), avg_satisfaction=_round(r["sat"]))
            for r in rows]
