"""
Schémas des réponses (documentés automatiquement dans /docs).
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# --- Authentification -------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserOut(BaseModel):
    username: str
    name: str
    profil: str


# --- Évaluations ------------------------------------------------------------

class Evaluation(BaseModel):
    evaluation_id: int
    formation_id: Optional[str]
    type_formation: str
    formateur_id: Optional[str]
    satisfaction: Optional[float]
    contenu: Optional[float]
    logistique: Optional[float]
    applicabilite: Optional[float]
    note_moyenne: Optional[float]
    evaluation_complete: bool
    commentaire: Optional[str]
    sentiment: Optional[str]
    langue: Optional[str]
    date: str


class EvaluationDetail(Evaluation):
    topic_id: Optional[int] = Field(None, description="Thème dans la dernière analyse publiée")
    topic_label: Optional[str] = None
    topic_probability: Optional[float] = None


class EvaluationPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[Evaluation]


# --- Analyses ---------------------------------------------------------------

class Summary(BaseModel):
    total_evaluations: int
    completion_rate: Optional[float] = Field(description="Part d'évaluations aux 4 notes renseignées (0-1)")
    criteria: Dict[str, Optional[float]] = Field(description="Note moyenne par critère")
    overall_score: Optional[float]
    last_month: Optional[str] = Field(description="Dernier mois présent dans les données (AAAA-MM)")
    last_month_score: Optional[float]
    monthly_change: Optional[float] = Field(description="Variation relative vs le mois précédent (0.05 = +5 %)")


class TypeStats(BaseModel):
    type_formation: str
    n_evaluations: int
    completion_rate: float
    note_moyenne: Optional[float]
    criteria: Dict[str, Optional[float]]


class TimePoint(BaseModel):
    period: str
    value: Optional[float]
    n_evaluations: int


class TrainerStats(BaseModel):
    rank: int
    formateur_id: str
    n_evaluations: int
    note_moyenne: Optional[float]
    satisfaction: Optional[float]


class SentimentStats(BaseModel):
    sentiment: str
    n_evaluations: int
    share: float
    avg_satisfaction: Optional[float] = Field(description="Permet de vérifier le lexique : "
                                                          "« Positif » doit avoir les meilleures notes")


# --- Thèmes (BERTopic) ------------------------------------------------------

class TopicRun(BaseModel):
    run_id: str
    created_at: str
    status: str
    published_at: Optional[str]
    n_documents: int
    n_topics: Optional[int]
    outlier_ratio: Optional[float]
    coherence: Optional[float]
    diversity: Optional[float]
    params: dict
    message: Optional[str]

    @classmethod
    def from_row(cls, row):
        data = dict(row)
        data["params"] = json.loads(data["params"])
        return cls(**{k: data.get(k) for k in cls.model_fields})


class Keyword(BaseModel):
    word: str
    score: float


class Topic(BaseModel):
    topic_id: int
    label: str
    keywords: List[Keyword]
    size: int = Field(description="Nombre d'évaluations (après filtres)")
    share: float = Field(description="Part des évaluations analysées (après filtres)")
    avg_satisfaction: Optional[float]
    avg_note: Optional[float]


class TopicList(BaseModel):
    run: TopicRun
    n_documents: int = Field(description="Évaluations analysées après filtres")
    n_outliers: int = Field(description="Évaluations non classées (thème -1)")
    topics: List[Topic]


class TopicExample(BaseModel):
    evaluation_id: int
    commentaire: Optional[str]
    probability: Optional[float]
    satisfaction: Optional[float]
    type_formation: str
    date: str


class TopicDetail(BaseModel):
    run_id: str
    topic: Topic
    sentiment: Dict[str, int]
    by_type: Dict[str, int]
    examples: List[TopicExample] = Field(description="Les plus représentatives d'abord")


# --- Système ----------------------------------------------------------------

class IngestionLogEntry(BaseModel):
    file_name: str
    ingested_at: str
    status: str
    n_rows: int
    n_inserted: int
    n_duplicates: int
    n_rejected: int
    message: Optional[str]


class PipelineStatus(BaseModel):
    n_evaluations: int
    pending_preprocessing: int
    latest_published_run: Optional[TopicRun]
    recent_runs: List[TopicRun]
    recent_ingestions: List[IngestionLogEntry]


class Health(BaseModel):
    status: str
    database: bool
    n_evaluations: Optional[int] = None
    latest_published_run: Optional[str] = None
    latest_published_at: Optional[str] = None
