"""
Prétraitement incrémental : seules les évaluations pas encore traitées le sont.
"""
from datetime import datetime

from pipeline import db
from pipeline.text import clean_text, sentiment_label


def preprocess_pending(reprocess_all=False):
    """Nettoie le commentaire, calcule le sentiment et le nombre de mots ; renvoie le nombre de lignes traitées"""
    where = "" if reprocess_all else "WHERE preprocessed_at IS NULL"
    now = datetime.now().isoformat(timespec="seconds")

    with db.session() as conn:
        rows = conn.execute(f"SELECT evaluation_id, commentaire FROM evaluations {where}").fetchall()
        updates = []
        for r in rows:
            clean = clean_text(r["commentaire"])
            updates.append((clean or None,
                            sentiment_label(clean) if clean else None,
                            len(clean.split()),
                            now,
                            r["evaluation_id"]))
        conn.executemany(
            "UPDATE evaluations SET commentaire_clean = ?, sentiment = ?, nb_mots = ?, "
            "preprocessed_at = ? WHERE evaluation_id = ?", updates)
    return len(updates)
