from __future__ import annotations
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from .fixtures import all_seed_scenarios
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
            c.execute("CREATE TABLE IF NOT EXISTS meta_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
                "purpose TEXT NOT NULL, scenario_id TEXT, run_id TEXT, model TEXT NOT NULL, prompt_tokens INTEGER NOT NULL, "
                "completion_tokens INTEGER NOT NULL, reasoning_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL, "
                "cost_usd REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, domain TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS sweeps (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS domain_drafts (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            # Seeds that already exist keep their reviews; a newly added domain gets its seeds on the next start.
            c.executemany("INSERT OR IGNORE INTO scenarios VALUES (?,?)",[(s.id,s.model_dump_json()) for s in all_seed_scenarios()])

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def list_scenarios(self,domain:str|None=None) -> list[Scenario]:
        with self.connect() as c:
            found=[Scenario.model_validate_json(row[0]) for row in c.execute("SELECT payload FROM scenarios ORDER BY id")]
        return [s for s in found if domain is None or s.domain==domain]

    def get_scenario(self,id:str) -> Scenario|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM scenarios WHERE id=?",(id,)).fetchone()
            return Scenario.model_validate_json(row[0]) if row else None

    def save_scenario(self,s:Scenario):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO scenarios(id,payload) VALUES (?,?)",(s.id,s.model_dump_json()))

    def save_run(self,r:dict):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO runs(id,scenario_id,created_at,payload) VALUES (?,?,?,?)",
                (r["id"],r["scenario_id"],r["created_at"],json.dumps(r)))

    def get_run(self,id:str)->dict|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM runs WHERE id=?",(id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_runs(self,limit:int=30)->list[dict]:
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?",(limit,))]

    def save_policy(self,p:dict):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO policies(id,domain,created_at,payload) VALUES (?,?,?,?)",
                (p["id"],p["domain"],p["created_at"],json.dumps(p)))

    def get_policy(self,id:str)->dict|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM policies WHERE id=?",(id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_policies(self,domain:str)->list[dict]:
        """Compiled policies for a domain, oldest first, so approved rules apply in a stable order."""
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT payload FROM policies WHERE domain=? ORDER BY created_at, id",(domain,))]

    def save_sweep(self,s:dict):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO sweeps(id,created_at,payload) VALUES (?,?,?)",(s["id"],s["created_at"],json.dumps(s)))

    def get_sweep(self,id:str)->dict|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM sweeps WHERE id=?",(id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_domain_draft(self,d:dict):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO domain_drafts(id,created_at,payload) VALUES (?,?,?)",
                (d["id"],d["created_at"],json.dumps(d)))

    def get_domain_draft(self,id:str)->dict|None:
        with self.connect() as c:
            row=c.execute("SELECT payload FROM domain_drafts WHERE id=?",(id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_domain_drafts(self,limit:int=20)->list[dict]:
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT payload FROM domain_drafts ORDER BY created_at DESC LIMIT ?",(limit,))]

    def list_sweeps(self,limit:int=20)->list[dict]:
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute("SELECT payload FROM sweeps ORDER BY created_at DESC LIMIT ?",(limit,))]

    def log_usage(self,row:dict)->int:
        cols=("created_at","purpose","scenario_id","run_id","model","prompt_tokens","completion_tokens",
              "reasoning_tokens","total_tokens","cost_usd","attempts")
        with self.connect() as c:
            cur=c.execute(f"INSERT INTO meta_usage({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                tuple(row.get(k) for k in cols))
            return cur.lastrowid

    def link_usage(self,ids:list[int],scenario_id:str):
        with self.connect() as c:
            c.executemany("UPDATE meta_usage SET scenario_id=? WHERE id=? AND scenario_id IS NULL",[(scenario_id,i) for i in ids])

    def total_spend(self)->float:
        with self.connect() as c:
            return float(c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM meta_usage").fetchone()[0])

    def usage_summary(self,limit:int=20)->dict:
        with self.connect() as c:
            c.row_factory=sqlite3.Row
            totals=dict(c.execute("SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS cost_usd, "
                "COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
                "COALESCE(SUM(reasoning_tokens),0) AS reasoning_tokens, COALESCE(SUM(total_tokens),0) AS total_tokens FROM meta_usage").fetchone())
            recent=[dict(r) for r in c.execute("SELECT * FROM meta_usage ORDER BY id DESC LIMIT ?",(limit,))]
        return {"totals":totals,"recent":recent}
