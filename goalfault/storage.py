from __future__ import annotations
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from .fixtures import seed_scenarios
from .models import Scenario


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

class Storage:
    def __init__(self,path: str):
        self.path=path
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS scenarios (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            exists=c.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
            if not exists:
                for scenario in seed_scenarios():
                    c.execute("INSERT INTO scenarios VALUES (?,?)",(scenario.id, scenario.model_dump_json()))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def list_scenarios(self) -> list[Scenario]:
        with self.connect() as c:
            return [Scenario.model_validate_json(row[0]) for row in c.execute("SELECT payload FROM scenarios ORDER BY id")]

    def get_scenario(self,id:str) -> Scenario|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM scenarios WHERE id=?",(id,)).fetchone()
            return Scenario.model_validate_json(row[0]) if row else None

    def save_scenario(self,s:Scenario):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO scenarios(id,payload) VALUES (?,?)",(s.id,s.model_dump_json()))

    def save_run(self,r:dict):
        with self.connect() as c:
            c.execute("INSERT INTO runs(id,scenario_id,created_at,payload) VALUES (?,?,?,?)",
                (r["id"],r["scenario_id"],r["created_at"],json.dumps(r)))

    def get_run(self,id:str)->dict|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM runs WHERE id=?",(id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_runs(self,limit:int=30)->list[dict]:
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?",(limit,))]
