import pytest
from fastapi.testclient import TestClient
import goalfault.api as api

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("GOALFAULT_DB_PATH",str(tmp_path/"test.db"))
    monkeypatch.delenv("GOALFAULT_ADMIN_TOKEN",raising=False)
    api.database.cache_clear()
    with TestClient(api.app) as c: yield c
    api.database.cache_clear()

def test_health_and_config(client):
    assert client.get("/api/health").json()["status"]=="ok"
    assert len(client.get("/api/scenarios").json())==3

def test_requires_approval(client):
    resp=client.post("/api/scenarios/GF-001/run",json={"mode":"fixture","guardrails":False})
    assert resp.status_code==409

def test_approve_execute_guard_replay(client):
    assert client.post("/api/scenarios/GF-001/review",json={"approved":True}).status_code==200
    r=client.post("/api/scenarios/GF-001/run",json={"mode":"fixture","guardrails":False})
    assert r.status_code==200
    data=r.json()
    assert data["source"]=="demo_fixture"
    assert not data["evaluation"]["passed"]
    assert len(data["minimal_failing_actions"])==1
    replay=client.post(f"/api/runs/{data['id']}/replay",json={"guardrails":True}).json()
    assert replay["evaluation"]["passed"]
    assert replay["source"]=="replay"

def test_natural_language_proposal_is_reviewable(client):
    r=client.post("/api/scenarios/compose",json={"text":"Test a $180 refund without manager approval","mode":"demo"})
    assert r.status_code==200
    assert r.json()["scenario"]["status"]=="proposed"
    assert r.json()["generation_mode"]=="demo"
    id=r.json()["scenario"]["id"]
    updated=client.post(f"/api/scenarios/{id}/review",json={"approved":False}).json()
    assert updated["status"]=="rejected"

def test_remote_write_denied_without_admin_token(client,monkeypatch):
    monkeypatch.setenv("GOALFAULT_ADMIN_TOKEN","example-secret")
    resp=client.post("/api/scenarios/GF-001/review",json={"approved":True})
    assert resp.status_code==403
    ok=client.post("/api/scenarios/GF-001/review",json={"approved":True},headers={"X-GoalFault-Token":"example-secret"})
    assert ok.status_code==200
