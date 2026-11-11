from fastapi import APIRouter, Depends

from app.dependencies import get_conn
from app.schemas import Health, IngestionLogEntry, PipelineStatus, TopicRun
from app.security import require_rh
from pipeline import config, db

router = APIRouter(tags=["Système"])


@router.get("/health", response_model=Health, summary="État du service (sans authentification)")
def health():
    if not config.DB_PATH.exists():
        return Health(status="degraded", database=False)
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
        run = db.latest_published_run(conn)
    except Exception:
        return Health(status="degraded", database=False)
    finally:
        conn.close()
    return Health(status="ok" if run else "degraded", database=True, n_evaluations=n,
                  latest_published_run=run["run_id"] if run else None,
                  latest_published_at=run["published_at"] if run else None)


@router.get("/pipeline/status", response_model=PipelineStatus, dependencies=[Depends(require_rh)],
            summary="Suivi du DAG : ingestions et exécutions BERTopic récentes")
def pipeline_status(conn=Depends(get_conn)):
    n, pending = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(preprocessed_at IS NULL), 0) FROM evaluations").fetchone()
    latest = db.latest_published_run(conn)
    runs = conn.execute("SELECT * FROM topic_runs ORDER BY created_at DESC LIMIT 5").fetchall()
    logs = conn.execute("SELECT * FROM ingestion_log ORDER BY id DESC LIMIT 10").fetchall()
    return PipelineStatus(
        n_evaluations=n,
        pending_preprocessing=pending,
        latest_published_run=TopicRun.from_row(latest) if latest else None,
        recent_runs=[TopicRun.from_row(r) for r in runs],
        recent_ingestions=[IngestionLogEntry(**{k: r[k] for k in IngestionLogEntry.model_fields})
                           for r in logs],
    )
