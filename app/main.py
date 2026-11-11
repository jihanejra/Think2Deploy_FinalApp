"""
API des évaluations de formation.

    uvicorn app.main:app --reload       # documentation interactive : http://localhost:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.routers import analytics, auth, evaluations, system, topics

app = FastAPI(
    title="API Évaluations de Formation",
    version="1.0.0",
    description=(
        "Indicateurs, évaluations et thèmes BERTopic des évaluations de formation.\n\n"
        "Les données et les thèmes sont mis à jour chaque nuit à 2h par le DAG Airflow "
        "`evaluations_daily`. L'API est en lecture seule.\n\n"
        "**Connexion** : bouton *Authorize* avec `rh_user` / `123` (profil RH)."
    ),
)

if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(evaluations.router)
app.include_router(analytics.router)
app.include_router(topics.router)
