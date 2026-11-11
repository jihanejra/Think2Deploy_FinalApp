"""
Exécution manuelle du pipeline, dans le même ordre que le DAG Airflow.

    python -m pipeline.cli init --seed     # crée la base et charge les 300 évaluations initiales
    python -m pipeline.cli run             # ingestion -> prétraitement -> BERTopic -> publication
    python -m pipeline.cli run --force     # ré-entraîne même sans nouvelle évaluation
    python -m pipeline.cli status
"""
import argparse
import json

from pipeline import config, db


def cmd_init(args):
    from pipeline import ingestion

    db.init_db()
    print(f"Base prête : {config.DB_PATH}")
    if args.seed:
        print(json.dumps(ingestion.seed_database(), indent=2, ensure_ascii=False))


def cmd_run(args):
    from pipeline import ingestion, preprocessing, topics

    db.init_db()
    ingested = ingestion.ingest_incoming()
    print("Ingestion :", ingested)
    print("Prétraitement :", preprocessing.preprocess_pending(), "évaluations")
    if not topics.needs_retrain(ingested["inserted"], force=args.force):
        print("Aucune nouvelle évaluation : BERTopic n'est pas ré-entraîné")
        return
    run_id = topics.train_topics()
    print("Publication :", topics.publish_run(run_id))
    print("Exécutions supprimées :", topics.cleanup_runs())


def cmd_status(args):
    with db.session() as conn:
        n = conn.execute("SELECT COUNT(*), SUM(preprocessed_at IS NULL) FROM evaluations").fetchone()
        print(f"Évaluations : {n[0]} (dont {n[1] or 0} à prétraiter)")
        run = db.latest_published_run(conn)
        print("Exécution publiée :", dict(run) if run else "aucune")


def main():
    parser = argparse.ArgumentParser(description="Pipeline des évaluations de formation")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("init", help="crée la base")
    p.add_argument("--seed", action="store_true", help="charge le jeu initial")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("run", help="exécute tout le pipeline")
    p.add_argument("--force", action="store_true", help="ré-entraîne BERTopic sans condition")
    p.set_defaults(func=cmd_run)

    sub.add_parser("status", help="état de la base").set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
