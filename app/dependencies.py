"""
Dépendances communes : connexion à la base, filtres des évaluations.
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from fastapi import HTTPException, Query, status

from pipeline import config, db


def get_conn():
    if not config.DB_PATH.exists():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Base non initialisée : lancez le pipeline (python -m pipeline.cli init --seed)")
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@dataclass
class EvaluationFilters:
    types: Optional[List[str]] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    min_score: Optional[float] = None

    def where(self, alias="e"):
        """Clause WHERE paramétrée (jamais de valeur concaténée dans le SQL)"""
        clauses, params = [], []
        if self.types:
            clauses.append(f"{alias}.type_formation IN ({', '.join('?' * len(self.types))})")
            params += self.types
        if self.date_from:
            clauses.append(f"{alias}.date >= ?")
            params.append(self.date_from.isoformat())
        if self.date_to:
            clauses.append(f"{alias}.date <= ?")
            params.append(self.date_to.isoformat())
        if self.min_score is not None:
            clauses.append(f"{alias}.note_moyenne >= ?")
            params.append(self.min_score)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def evaluation_filters(
    type_formation: Optional[List[str]] = Query(None, description="Un ou plusieurs types de formation"),
    date_from: Optional[date] = Query(None, description="Date de début incluse (AAAA-MM-JJ)"),
    date_to: Optional[date] = Query(None, description="Date de fin incluse (AAAA-MM-JJ)"),
    min_score: Optional[float] = Query(None, ge=1, le=5, description="Note moyenne minimale"),
) -> EvaluationFilters:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from est après date_to")
    return EvaluationFilters(type_formation, date_from, date_to, min_score)
