import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def token_for(username, password="123"):
    r = client.post("/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def rh(populated_db):
    return token_for("rh_user")


# --- Authentification et droits ---------------------------------------------

def test_health_is_public(populated_db):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["n_evaluations"] == 5
    assert body["latest_published_run"] == "20240301T020000"


def test_wrong_password_is_rejected(populated_db):
    assert client.post("/auth/token", data={"username": "rh_user", "password": "x"}).status_code == 401
    assert client.post("/auth/token", data={"username": "inconnu", "password": "123"}).status_code == 401


def test_routes_require_token(populated_db):
    assert client.get("/analytics/summary").status_code == 401
    assert client.get("/analytics/summary",
                      headers={"Authorization": "Bearer faux"}).status_code == 401


def test_non_rh_profile_is_forbidden(populated_db):
    headers = token_for("user.cdi")
    assert client.get("/auth/me", headers=headers).json()["profil"] == "CDI"
    assert client.get("/topics", headers=headers).status_code == 403


# --- Analyses ---------------------------------------------------------------

def test_summary(rh):
    body = client.get("/analytics/summary", headers=rh).json()
    assert body["total_evaluations"] == 5
    assert body["completion_rate"] == 0.8
    assert body["criteria"]["satisfaction"] == 3.0
    assert body["last_month"] == "2024-02"
    # janvier : (4.75 + 4) / 2 = 4.375 ; février : (2.333 + 1.5 + 3) / 3 = 2.278
    assert body["monthly_change"] == pytest.approx(-0.479, abs=1e-3)


def test_filters(rh):
    body = client.get("/analytics/summary?type_formation=SAP", headers=rh).json()
    assert body["total_evaluations"] == 3
    body = client.get("/analytics/summary?date_from=2024-02-01&min_score=2", headers=rh).json()
    assert body["total_evaluations"] == 2
    assert client.get("/analytics/summary?date_from=2024-03-01&date_to=2024-01-01",
                      headers=rh).status_code == 422


def test_by_type_and_trainers(rh):
    types = client.get("/analytics/by-type", headers=rh).json()
    assert [t["type_formation"] for t in types] == ["SAP", "Python Data"]
    trainers = client.get("/analytics/trainers?min_evaluations=2", headers=rh).json()
    assert [t["formateur_id"] for t in trainers] == ["FOR01", "FOR02"]


def test_timeseries_rejects_unknown_metric(rh):
    points = client.get("/analytics/timeseries?granularity=month&metric=satisfaction", headers=rh).json()
    assert [(p["period"], p["value"]) for p in points] == [("2024-01", 4.5), ("2024-02", 2.0)]
    # La métrique est insérée dans le SQL : toute valeur hors liste doit être refusée
    r = client.get("/analytics/timeseries?metric=satisfaction);DROP TABLE evaluations;--", headers=rh)
    assert r.status_code == 422


def test_sentiment(rh):
    stats = {s["sentiment"]: s for s in client.get("/analytics/sentiment", headers=rh).json()}
    assert stats["Positif"]["n_evaluations"] == 2 and stats["Positif"]["avg_satisfaction"] == 4.5


# --- Évaluations ------------------------------------------------------------

def test_evaluations_pagination_and_search(rh):
    page = client.get("/evaluations?limit=2", headers=rh).json()
    assert page["total"] == 5 and [e["evaluation_id"] for e in page["items"]] == [5, 4]
    found = client.get("/evaluations?q=salle", headers=rh).json()
    assert [e["evaluation_id"] for e in found["items"]] == [2]


def test_evaluation_detail_includes_topic(rh):
    body = client.get("/evaluations/3", headers=rh).json()
    assert body["topic_id"] == 1 and body["topic_label"] == "rythme, décevante"
    assert client.get("/evaluations/999", headers=rh).status_code == 404


# --- Thèmes -----------------------------------------------------------------

def test_topics_list(rh):
    body = client.get("/topics", headers=rh).json()
    assert body["run"]["run_id"] == "20240301T020000"
    assert body["n_documents"] == 5 and body["n_outliers"] == 1
    assert [(t["topic_id"], t["size"]) for t in body["topics"]] == [(0, 2), (1, 2)]
    assert body["topics"][0]["keywords"][0] == {"word": "excellent", "score": 0.3}


def test_topics_are_recomputed_on_filtered_subset(rh):
    body = client.get("/topics?type_formation=Python Data", headers=rh).json()
    assert [(t["topic_id"], t["size"]) for t in body["topics"]] == [(1, 1)]
    assert body["topics"][0]["avg_satisfaction"] == 1.0


def test_topic_detail(rh):
    body = client.get("/topics/1", headers=rh).json()
    assert [e["evaluation_id"] for e in body["examples"]] == [3, 4]   # par probabilité
    assert body["sentiment"] == {"Négatif": 2}
    assert body["by_type"] == {"SAP": 1, "Python Data": 1}
    assert client.get("/topics/42", headers=rh).status_code == 404


def test_topics_404_when_nothing_published(data_dir):
    headers = token_for("rh_user")
    assert client.get("/topics", headers=headers).status_code == 404


def test_pipeline_status(rh):
    body = client.get("/pipeline/status", headers=rh).json()
    assert body["n_evaluations"] == 5 and body["pending_preprocessing"] == 0
    assert body["latest_published_run"]["run_id"] == "20240301T020000"
