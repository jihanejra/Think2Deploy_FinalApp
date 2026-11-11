"""
### Pipeline quotidien des évaluations de formation

Tous les jours à 2h (heure de Paris) :

1. **init_storage** : crée les tables si besoin
2. **ingest** : ingère les CSV déposés dans `data/incoming/` (sans doublon), archive les fichiers
3. **preprocess** : nettoie les nouveaux commentaires, calcule sentiment et nombre de mots
4. **should_retrain** : s'arrête là si aucune nouvelle évaluation (sauf `force_retrain`)
5. **train_topics** : ré-entraîne BERTopic sur tout le corpus (exécution « pending »)
6. **publish** : contrôle qualité ; publiée si elle passe, sinon rejetée et la tâche échoue
   (l'API continue de servir l'exécution précédente)
7. **cleanup** : supprime les anciennes exécutions

Les résultats sont écrits dans `data/warehouse.db`, que l'API FastAPI lit.
"""
from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, get_current_context, task


@dag(
    dag_id="evaluations_daily",
    schedule="0 2 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="Europe/Paris"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    params={"force_retrain": Param(False, type="boolean",
                                   description="Ré-entraîner BERTopic même sans nouvelle évaluation")},
    tags=["evaluations", "nlp", "bertopic"],
    doc_md=__doc__,
)
def evaluations_daily():
    # Les imports du pipeline sont faits dans les tâches : le scheduler analyse ce fichier
    # souvent, il ne doit pas charger pandas, scikit-learn ou PyTorch à chaque fois

    # Première tâche : au démarrage du conteneur, elle peut partir avant que le serveur
    # interne d'Airflow (~25 s) soit prêt. Nouvelles tentatives rapprochées plutôt que 5 min.
    @task(retries=5, retry_delay=timedelta(seconds=30))
    def init_storage():
        from pipeline import db
        db.init_db()

    @task
    def ingest() -> dict:
        from pipeline.ingestion import ingest_incoming
        return ingest_incoming()

    @task
    def preprocess() -> int:
        from pipeline.preprocessing import preprocess_pending
        return preprocess_pending()

    @task.short_circuit
    def should_retrain(ingestion: dict) -> bool:
        from pipeline.topics import needs_retrain
        force = get_current_context()["params"]["force_retrain"]
        return needs_retrain(ingestion["inserted"], force=force)

    @task(execution_timeout=timedelta(hours=1))
    def train_topics() -> str:
        from pipeline.topics import train_topics as train
        return train()

    # Pas de nouvelle tentative : relancer ne changerait pas les métriques.
    # Paramètre nommé topic_run_id : « run_id » est réservé par Airflow (contexte du DAG)
    @task(retries=0)
    def publish(topic_run_id: str) -> dict:
        from pipeline.topics import publish_run
        result = publish_run(topic_run_id)
        if result["status"] != "published":
            raise RuntimeError(f"Exécution {topic_run_id} rejetée par le contrôle qualité : "
                               + "; ".join(result["failures"]))
        return result

    @task
    def cleanup() -> int:
        from pipeline.topics import cleanup_runs
        return cleanup_runs()

    ingestion = ingest()
    preprocessed = preprocess()
    retrain = should_retrain(ingestion)
    topic_run_id = train_topics()

    init_storage() >> ingestion >> preprocessed >> retrain >> topic_run_id
    publish(topic_run_id) >> cleanup()


evaluations_daily()
