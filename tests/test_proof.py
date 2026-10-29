import pytest
from fastapi.testclient import TestClient
import goalfault.api as api
from goalfault.proof import evidence_html

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GOALFAULT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("GOALFAULT_ADMIN_TOKEN", raising=False)
    api.database.cache_clear()
    with TestClient(api.app) as c:
        yield c
    api.database.cache_clear()


def test_evidence_page_escapes_tool_arguments():
    page = evidence_html({
        "run_id": "RUN-X", "source": "demo_fixture", "scenario_id": "GF-001", "replayed": True,
        "steps": [{"step": 1, "tool": "issue_refund", "args": {"order_id": "<script>"}, "allowed": True,
                   "result": {}, "state_changes": [], "policies": [
                       {"id": "P-101", "invariant": "x", "text": "<b>", "rule": "deny x"}],
                   "replay_matches": True, "blocked": False, "not_executed": False}],
    })
    assert "<script>" not in page
    assert "&lt;script&gt;" in page and "&lt;b&gt;" in page


def test_fixture_proof_links_the_refund_to_its_rule(client):
    assert client.post("/api/scenarios/GF-001/review", json={"approved": True}).status_code == 200
    run = client.post("/api/scenarios/GF-001/run", json={"mode": "fixture"}).json()
    proof = client.get(f"/api/runs/{run['id']}/proof").json()
    assert proof["replayed"] is True
    lookup = next(step for step in proof["steps"] if step["tool"] == "lookup_order")
    refund = next(step for step in proof["steps"] if step["tool"] == "issue_refund")
    assert lookup["state_changes"] == [] and lookup["policies"] == []
    assert refund["replay_matches"] is True
    assert any(change["path"].endswith("refunded") for change in refund["state_changes"])
    assert refund["policies"][0]["id"] == "P-101"
    assert "Refunds above $100" in refund["policies"][0]["text"]
    assert refund["policies"][0]["rule"].startswith("deny issue_refund")
    page = client.get(f"/runs/{run['id']}")
    assert page.status_code == 200
    assert "P-101" in page.text and "Refunds above $100" in page.text
    assert client.get("/api/runs/RUN-MISSING/proof").status_code == 404
    assert client.get("/runs/RUN-MISSING").status_code == 404
