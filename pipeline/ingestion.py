"""
Ingestion des nouvelles évaluations déposées en CSV dans data/incoming/.

Pour chaque fichier : validation ligne par ligne, insertion des lignes valides
(les evaluation_id déjà connus sont ignorés), lignes invalides écrites dans
data/rejected/ avec leur motif, puis fichier archivé dans data/archive/AAAA-MM-JJ/.

Idempotent : ré-ingérer un fichier n'insère aucun doublon.
"""
import csv
import shutil
from datetime import datetime

import pandas as pd

from pipeline import config, db

EXPECTED_COLUMNS = ["evaluation_id", "formation_id", "type_formation", "formateur_id",
                    "satisfaction", "contenu", "logistique", "applicabilite",
                    "commentaire", "langue", "date"]
SCORE_COLUMNS = ["satisfaction", "contenu", "logistique", "applicabilite"]
TEXT_COLUMNS = ["formation_id", "type_formation", "formateur_id", "commentaire", "langue"]

INSERT_SQL = f"""
INSERT OR IGNORE INTO evaluations
    ({", ".join(EXPECTED_COLUMNS)}, note_moyenne, evaluation_complete, source_file, ingested_at)
VALUES ({", ".join("?" * (len(EXPECTED_COLUMNS) + 4))})
"""


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def validate(raw):
    """
    Sépare les lignes valides des invalides.
    Renvoie (valides normalisées, invalides avec une colonne 'motif_rejet').
    """
    df = raw.copy()
    reasons = pd.Series("", index=df.index)

    def reject(mask, reason):
        reasons[mask & (reasons == "")] = reason

    ids = pd.to_numeric(df["evaluation_id"], errors="coerce")
    reject(ids.isna() | (ids % 1 != 0), "evaluation_id manquant ou non entier")
    reject(ids.duplicated(keep="first") & ids.notna(), "evaluation_id en double dans le fichier")

    dates = pd.to_datetime(df["date"], errors="coerce", format="mixed")
    reject(dates.isna(), "date manquante ou invalide")

    reject(df["type_formation"].fillna("").astype(str).str.strip() == "", "type_formation manquant")

    for col in SCORE_COLUMNS:
        values = pd.to_numeric(df[col], errors="coerce")
        bad = (df[col].notna() & values.isna()) | (values.notna() & ~values.between(1, 5))
        reject(bad, f"{col} hors de l'échelle 1-5")
        df[col] = values

    valid = df[reasons == ""].copy()
    valid["evaluation_id"] = ids[reasons == ""].astype(int)
    valid["date"] = dates[reasons == ""].dt.strftime("%Y-%m-%d")
    for col in TEXT_COLUMNS:
        valid[col] = valid[col].where(valid[col].notna(), None)
    valid["note_moyenne"] = valid[SCORE_COLUMNS].mean(axis=1, skipna=True)
    valid["evaluation_complete"] = valid[SCORE_COLUMNS].notna().all(axis=1).astype(int)

    rejected = raw[reasons != ""].copy()
    rejected["motif_rejet"] = reasons[reasons != ""]
    return valid, rejected


def _to_sql_value(value):
    return None if pd.isna(value) else (value.item() if hasattr(value, "item") else value)


def _unique_path(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if target.exists():
        target = directory / f"{datetime.now():%H%M%S}_{name}"
    return target


def read_csv_strict(path):
    """
    Lit le CSV en écartant les lignes dont le nombre de champs diffère de l'en-tête
    (virgule non protégée...). pandas.read_csv les tronquerait ou décalerait les
    colonnes sans erreur, et une ligne décalée pourrait passer la validation.
    Renvoie (DataFrame de chaînes, lignes écartées).
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.reader(f) if r]
    if not rows:
        raise ValueError("fichier vide")
    header, body = rows[0], rows[1:]
    good = [r for r in body if len(r) == len(header)]
    bad = [r for r in body if len(r) != len(header)]
    df = pd.DataFrame(good, columns=header, dtype=str).replace("", None)
    return df, bad


def ingest_file(conn, path):
    """Ingère un fichier CSV ; renvoie le résumé enregistré dans ingestion_log"""
    summary = {"file_name": path.name, "ingested_at": now_iso(), "status": "success",
               "n_rows": 0, "n_inserted": 0, "n_duplicates": 0, "n_rejected": 0, "message": None}
    try:
        raw, bad_lines = read_csv_strict(path)
        missing = [c for c in EXPECTED_COLUMNS if c not in raw.columns]
        if missing:
            raise ValueError(f"colonnes manquantes : {', '.join(missing)}")
    except Exception as e:
        # Fichier illisible ou mauvais format : il est mis de côté tel quel
        summary.update(status="rejected", message=str(e))
        shutil.move(path, _unique_path(config.REJECTED_DIR, path.name))
        _log(conn, summary)
        return summary

    valid, rejected = validate(raw)
    if bad_lines:
        malformed = pd.DataFrame({"ligne_brute": [",".join(f) for f in bad_lines],
                                  "motif_rejet": "nombre de colonnes incorrect"})
        rejected = pd.concat([rejected, malformed], ignore_index=True)
    rows = [tuple(_to_sql_value(r[c]) for c in EXPECTED_COLUMNS)
            + (_to_sql_value(r["note_moyenne"]), int(r["evaluation_complete"]), path.name,
               summary["ingested_at"])
            for _, r in valid.iterrows()]

    before = conn.total_changes
    conn.executemany(INSERT_SQL, rows)
    inserted = conn.total_changes - before

    summary.update(n_rows=len(raw) + len(bad_lines), n_inserted=inserted,
                   n_duplicates=len(valid) - inserted, n_rejected=len(rejected))
    if len(rejected):
        rejected.to_csv(_unique_path(config.REJECTED_DIR, f"{path.stem}_rejets.csv"),
                        index=False, encoding="utf-8-sig")
    # _log valide la transaction (insertions + journal). Le fichier n'est archivé
    # qu'ensuite : en cas d'arrêt entre les deux, il sera ré-ingéré sans doublon
    _log(conn, summary)
    shutil.move(path, _unique_path(config.ARCHIVE_DIR / f"{datetime.now():%Y-%m-%d}", path.name))
    return summary


def _log(conn, summary):
    conn.execute(
        "INSERT INTO ingestion_log (file_name, ingested_at, status, n_rows, n_inserted, "
        "n_duplicates, n_rejected, message) VALUES (:file_name, :ingested_at, :status, "
        ":n_rows, :n_inserted, :n_duplicates, :n_rejected, :message)", summary)
    conn.commit()


def ingest_incoming():
    """
    Ingère tous les CSV de data/incoming/ (ordre alphabétique).
    Les fichiers doivent être déposés complets (écrire en .tmp puis renommer en .csv).
    """
    files = sorted(config.INCOMING_DIR.glob("*.csv"))
    totals = {"files": len(files), "inserted": 0, "duplicates": 0, "rejected_rows": 0,
              "rejected_files": 0}
    with db.session() as conn:
        for path in files:
            s = ingest_file(conn, path)
            totals["inserted"] += s["n_inserted"]
            totals["duplicates"] += s["n_duplicates"]
            totals["rejected_rows"] += s["n_rejected"]
            totals["rejected_files"] += s["status"] == "rejected"
    return totals


def seed_database():
    """Charge le jeu initial (300 évaluations de 2024) sans le déplacer"""
    tmp = config.INCOMING_DIR / "_seed.csv"
    config.INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(config.SEED_FILE, tmp)
    with db.session() as conn:
        return ingest_file(conn, tmp)
