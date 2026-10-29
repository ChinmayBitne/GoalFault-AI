from __future__ import annotations
import os
import threading
from pathlib import Path
from functools import lru_cache
from uuid import uuid4
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import ValidationError
from .models import (ComposeRequest,CompileRequest,DiscoverRequest,DomainDraftRequest,DomainReviewRequest,
                     PolicyEdit,PolicyReviewRequest,RepairRequest,ReviewRequest,RunRequest,ReplayRequest,Scenario,SweepRequest)
from .compiler import PolicyDraft,check_draft,check_guard
from .fixtures import interpret_demo,make_scenario,policy_catalog,seed_scenarios,tool_catalog
from .simulator import fixture_run,replay_actions,minimize_failure,executable_actions
from .meta import MetaClient,MetaError,SpendCapError,estimate_cost,price_rates,spend_cap
from .proof import evidence_html, proof_steps, steps_without_replay
from .quality import domain_quality
from . import spec as spec_module
from .spec import DEFAULT_DOMAIN,DomainSpec,SpecError,UnknownDomain,get_spec,registry
from .wizard import check_domain_yaml, install_domain
from .storage import Storage,utc_now

load_dotenv()
ROOT=Path(__file__).resolve().parent.parent
app=FastAPI(title="GoalFault AI",version="0.1.0",description="Evidence-driven crash testing for tool-using agents")
app.mount("/assets",StaticFiles(directory=ROOT/"web"),name="assets")

@lru_cache
def database():
    return Storage(os.getenv("GOALFAULT_DB_PATH",str(ROOT/"data"/"goalfault.db")))


def meta_client()->MetaClient:
    return MetaClient(ledger=database())


def meta_failure(e:MetaError)->HTTPException:
    # 402: the local spend cap refused the call before anything was sent to Meta.
    return HTTPException(402 if isinstance(e,SpendCapError) else 502,str(e))


def get_scenario_or_404(id:str)->Scenario:
    scenario=database().get_scenario(id)
    if not scenario: raise HTTPException(404,"Unknown scenario")
    return scenario


def domain_spec(name:str)->DomainSpec:
    try: return get_spec(name)
    except UnknownDomain: raise HTTPException(404,f"Unknown domain {name!r}") from None


@lru_cache(maxsize=64)
def extended_spec(domain:str,added:tuple)->DomainSpec:
    return get_spec(domain).with_policies([{"id":i,"text":t,"invariant":v,"rule":r} for i,t,v,r in added])


def effective_spec(domain:str,exclude:str|None=None)->DomainSpec:
    """The domain as runs see it: the spec file plus every approved compiled policy, oldest first."""
    base=domain_spec(domain)
    added=tuple((p["policy_id"],p["draft"]["text"],p["draft"]["invariant"],p["draft"]["rule"])
                for p in database().list_policies(domain) if p["status"]=="approved" and p["id"]!=exclude)
    if not added: return base
    try: return extended_spec(domain,added)
    except SpecError as exc:
        raise HTTPException(409,f"An approved policy for {domain} no longer validates against the spec; reject it to continue. {exc}") from exc


def domain_summary(spec:DomainSpec)->dict:
    quality=domain_quality(spec.name)
    return {"name":spec.name,"title":spec.title,"description":spec.description,"default_objective":spec.default_objective,
            "tools":len(spec.tools),"policies":len(spec.policies),"scenarios":len(spec.scenarios),
            "safe_controls":len(spec.safe_controls),"quality":{"passed":quality["passed"],"checks":quality["checks"]}}


def require_write(request:Request):
    token=os.getenv("GOALFAULT_ADMIN_TOKEN","")
    # Local-only development without a token. Do not interpret forwarded headers as trust.
    client_ip=request.client.host if request.client else ""
    is_loopback=client_ip in ("127.0.0.1","::1","testclient")
    if token:
        if request.headers.get("X-GoalFault-Token")!=token:
            raise HTTPException(403,"Valid local admin token required")
    elif not is_loopback or os.getenv("K_SERVICE"):
        raise HTTPException(403,"Public writes disabled. Configure GOALFAULT_ADMIN_TOKEN and protect the service before use.")

@app.get("/",include_in_schema=False)
def index(): return FileResponse(ROOT/"web"/"index.html")

@app.get("/api/health")
def health(): return {"status":"ok","name":"GoalFault AI","version":"0.1.0"}

@app.get("/api/config")
def config(domain:str=DEFAULT_DOMAIN):
    meta=MetaClient()
    spec=effective_spec(domain)
    return {"meta_configured":meta.configured,"model":meta.model,
       "modes":["fixture","muse"],"tool_catalog":tool_catalog(spec),"policies":policy_catalog(spec),
       "domain":{"name":spec.name,"title":spec.title,"description":spec.description,"default_objective":spec.default_objective},
       "note":"Fixture mode replays controlled actions; Muse mode generates real model tool requests inside the same fake sandbox."}

@app.get("/api/domains")
def domains(include_hidden:bool=False):
    """Domains that pass the quality bar; hidden ones only on request, with the checks they fail."""
    found=[domain_summary(spec) for spec in registry().values()]
    return [d for d in found if include_hidden or d["quality"]["passed"]]

@app.get("/api/domains/drafts")
def domain_drafts():
    return database().list_domain_drafts()

@app.post("/api/domains/draft",dependencies=[Depends(require_write)])
def draft_domain(req:DomainDraftRequest):
    """Check a spec and save it as a draft. It is not installed, and nothing can run in it yet."""
    record={"id":"DOM-"+uuid4().hex[:8].upper(),"status":"proposed","source":req.mode,"text":req.text,
            "created_at":utc_now(),"reviewed_at":None,"usage":{},"estimated_model_cost_usd":0,"explanation":""}
    if req.mode=="muse":
        client=meta_client()
        try: yaml_text,explanation,usage=client.draft_domain(req.text)
        except MetaError as e: raise meta_failure(e) from e
        record.update(explanation=explanation,usage=usage,estimated_model_cost_usd=estimate_cost(usage),usage_ids=client.usage_ids)
    else:
        if not req.yaml: raise HTTPException(422,"Manual mode needs the domain YAML")
        yaml_text=req.yaml
    record["yaml"]=yaml_text
    record["report"]=check_domain_yaml(yaml_text)
    database().save_domain_draft(record)
    return record

@app.post("/api/domains/drafts/{draft_id}/review",dependencies=[Depends(require_write)])
def review_domain_draft(draft_id:str,req:DomainReviewRequest):
    record=database().get_domain_draft(draft_id)
    if not record: raise HTTPException(404,"Unknown domain draft")
    if record["status"]!="proposed": raise HTTPException(409,"This draft was already reviewed")
    if not req.approved:
        record.update(status="rejected",reviewed_at=utc_now())
        database().save_domain_draft(record)
        return record
    record["report"]=check_domain_yaml(record["yaml"])
    if not record["report"]["ok"]:
        database().save_domain_draft(record)
        raise HTTPException(409,"Fix the draft before approving it: "+(record["report"]["errors"][0] if record["report"]["errors"] else "not installable"))
    try: spec=install_domain(record["yaml"],spec_module.DOMAINS_DIR)
    except FileExistsError as exc: raise HTTPException(409,f"A domain named {exc} is already installed") from exc
    except (ValueError,SpecError) as exc: raise HTTPException(409,str(exc)) from exc
    for scenario in seed_scenarios(spec):
        if database().get_scenario(scenario.id) is None: database().save_scenario(scenario)
    record.update(status="approved",reviewed_at=utc_now(),label="draft, human-reviewed")
    database().save_domain_draft(record)
    return record

@app.get("/api/usage")
def usage():
    summary=database().usage_summary()
    spent=round(summary["totals"]["cost_usd"],6)
    cap=spend_cap()
    return {"total_cost_usd":spent,"cap_usd":cap,"remaining_usd":round(max(cap-spent,0),6),"cap_reached":spent>=cap,
        "call_count":summary["totals"]["calls"],"tokens":{k:summary["totals"][k] for k in ("prompt_tokens","completion_tokens","reasoning_tokens","total_tokens")},
        "rates_usd_per_million":price_rates(),"recent":summary["recent"]}

@app.get("/api/scenarios")
def scenarios(domain:str|None=None):
    if domain is not None: domain_spec(domain)
    return [s.model_dump() for s in database().list_scenarios(domain)]

def save_proposal(proposal,source:str,client:MetaClient|None,usage:dict,mode:str,spec:DomainSpec)->dict:
    scenario=make_scenario(proposal,source,spec)
    database().save_scenario(scenario)
    if client and client.usage_ids: database().link_usage(client.usage_ids,scenario.id)
    return {"scenario":scenario.model_dump(),"usage":usage,"estimated_model_cost_usd":estimate_cost(usage),"generation_mode":mode}

@app.post("/api/scenarios/compose",dependencies=[Depends(require_write)])
def compose(req:ComposeRequest):
    spec=effective_spec(req.domain)
    client=None
    if req.mode=="muse":
        client=meta_client()
        try: proposal,usage=client.propose(req.text,spec=spec)
        except MetaError as e: raise meta_failure(e) from e
        source="muse"
    else:
        proposal=interpret_demo(req.text,spec)
        usage={}
        source="demo_template"
    return {**save_proposal(proposal,source,client,usage,req.mode,spec),
      "validation":f"The kind is restricted to the {len(spec.kinds)} scenario kinds of {spec.title}; approve and edit before any execution."}

@app.post("/api/scenarios/discover",dependencies=[Depends(require_write)])
def discover(req:DiscoverRequest):
    spec=effective_spec(req.domain)
    if req.mode=="muse":
        client=meta_client()
        try: proposal,usage=client.discover(spec)
        except MetaError as e: raise meta_failure(e) from e
        return save_proposal(proposal,"muse",client,usage,req.mode,spec)
    # Sampled from a fixed catalog, not generated by a model.
    seeds=seed_scenarios(spec)
    scenario=seeds[1%len(seeds)].model_copy(update={"id":"GF-"+uuid4().hex[:8].upper()})
    database().save_scenario(scenario)
    return {"scenario":scenario.model_dump(),"usage":{},"estimated_model_cost_usd":0,"generation_mode":req.mode}

@app.post("/api/scenarios/{scenario_id}/review",dependencies=[Depends(require_write)])
def review(scenario_id:str,req:ReviewRequest):
    s=get_scenario_or_404(scenario_id)
    s=s.model_copy(update={"status":"approved" if req.approved else "rejected",
         "title":req.title or s.title,"user_message":req.user_message or s.user_message,
         "objective":s.objective if req.objective is None else (req.objective.strip() or None),
         "pressure_level":s.pressure_level if req.pressure_level is None else req.pressure_level,
         "reviewed_at":utc_now()})
    database().save_scenario(s)
    return s.model_dump()

def execute_run(s:Scenario,mode:str,guardrails:bool,**extra)->dict:
    """Run an approved scenario once and store it. Raises MetaError for live runs that fail."""
    spec=effective_spec(s.domain)
    run_id="RUN-"+uuid4().hex[:10].upper()
    if mode=="muse":
        result,usage=meta_client().run_agent(s,guardrails,run_id=run_id,spec=spec)
        kind="model_tool_calls"
    else:
        result=fixture_run(s.kind,guardrails,spec)
        usage={}
        kind="scripted_fixture"
    run={"id":run_id,"scenario_id":s.id,"domain":s.domain,"added_policies":[p.id for p in spec.added_policies],
         "created_at":utc_now(),"kind":kind,"source":"muse" if mode=="muse" else "demo_fixture",
         "guardrails":guardrails,"objective":s.objective,"pressure_level":s.pressure_level,
         "usage":usage,"estimated_model_cost_usd":estimate_cost(usage),**extra,
         **result}
    run["minimal_failing_actions"]=minimize_failure(s.kind,result["trace"],spec) if not guardrails else []
    database().save_run(run)
    return run

@app.post("/api/scenarios/{scenario_id}/run",dependencies=[Depends(require_write)])
def run_scenario(scenario_id:str,req:RunRequest):
    s=get_scenario_or_404(scenario_id)
    if s.status!="approved": raise HTTPException(409,"Review and approve this scenario before running it")
    try: return execute_run(s,req.mode,req.guardrails)
    except MetaError as e: raise meta_failure(e) from e

# Fallback when no live run has been recorded yet; replaced by the real average once one exists.
FIRST_RUN_ESTIMATE_USD=0.02

def run_cost_estimate(domain:str)->float:
    costs=[r["estimated_model_cost_usd"] for r in database().list_runs(200)
           if r["source"]=="muse" and r.get("domain")==domain and not r["guardrails"]]
    return sum(costs)/len(costs) if costs else FIRST_RUN_ESTIMATE_USD

def metric_gap(evaluation:dict)->float|None:
    """Proxy minus actual, for domains whose metrics come as a proxy_*/actual_* pair."""
    proxy=next((v for k,v in evaluation.items() if k.startswith("proxy_")),None)
    actual=next((v for k,v in evaluation.items() if k.startswith("actual_")),None)
    return None if proxy is None or actual is None else proxy-actual

def sweep_view(sweep:dict)->dict:
    """Every number is recomputed from the stored runs, so the chart always matches the evidence."""
    runs=[r for r in (database().get_run(i) for i in sweep["run_ids"]) if r]
    levels=[]
    for level in sweep["config"]["levels"]:
        at=[r for r in runs if r["pressure_level"]==level]
        # A violation before an error still happened; a run that errored without one proves nothing either way.
        scored=[r for r in at if not r["evaluation"]["passed"] or r.get("stop_reason")!="error"]
        gaps=[g for g in (metric_gap(r["evaluation"]) for r in scored) if g is not None]
        violated=sum(not r["evaluation"]["passed"] for r in scored)
        levels.append({"level":level,"runs":len(scored),"violated":violated,"errored":len(at)-len(scored),
                       "violation_rate":violated/len(scored) if scored else None,
                       "mean_metric_gap":sum(gaps)/len(gaps) if gaps else None,
                       "run_ids":[r["id"] for r in at]})
    return {**sweep,"levels":levels,"cost_usd":round(sum(r["estimated_model_cost_usd"] for r in runs),6)}

@app.post("/api/sweeps",dependencies=[Depends(require_write)])
def start_sweep(req:SweepRequest):
    """Without confirm this only prices the sweep. With confirm it runs every live run in this request."""
    s=get_scenario_or_404(req.scenario_id)
    if s.status!="approved": raise HTTPException(409,"Review and approve this scenario before sweeping it")
    config=req.model_dump(exclude={"confirm"})
    total=len(req.levels)*req.runs_per_level
    estimate=round(total*run_cost_estimate(s.domain),4)
    remaining=round(max(spend_cap()-database().total_spend(),0),6)
    if not req.confirm:
        return {"config":config,"runs":total,"estimated_cost_usd":estimate,"remaining_usd":remaining}
    if estimate>remaining:
        raise HTTPException(402,f"Estimated ${estimate:.4f} is more than the ${remaining:.4f} left under the spend cap")
    sweep={"id":"SWP-"+uuid4().hex[:8].upper(),"created_at":utc_now(),"scenario_id":s.id,"domain":s.domain,
           "config":config,"estimated_cost_usd":estimate,"run_ids":[],"stop_reason":None}
    # shortcut: runs synchronously in one request (about 10 s per run); move to a background job if sweeps grow past ~40 runs.
    try:
        # Level by level within each round, so an early stop leaves every level with a similar number of runs.
        for _ in range(req.runs_per_level):
            for level in req.levels:
                run=execute_run(s.model_copy(update={"pressure_level":level}),"muse",False,sweep_id=sweep["id"])
                sweep["run_ids"].append(run["id"])
                database().save_sweep(sweep)
    except MetaError as e:
        sweep["stop_reason"]=str(e)
    except Exception as e:
        sweep["stop_reason"]=f"Stopped by an internal error: {type(e).__name__}"
        database().save_sweep(sweep)
        raise
    database().save_sweep(sweep)
    return sweep_view(sweep)

@app.get("/api/sweeps")
def sweeps(): return [sweep_view(s) for s in database().list_sweeps()]

@app.get("/api/sweeps/{sweep_id}")
def get_sweep(sweep_id:str):
    s=database().get_sweep(sweep_id)
    if not s: raise HTTPException(404,"Sweep not found")
    return sweep_view(s)

@app.get("/api/runs")
def runs(): return database().list_runs()

@app.get("/api/runs/{run_id}")
def get_run(run_id:str):
    r=database().get_run(run_id)
    if not r:raise HTTPException(404,"Run not found")
    return r


def proof_for(run:dict)->dict:
    """Action, replayed state change, and the stored rule for each call."""
    scenario=database().get_scenario(run["scenario_id"])
    payload={"run_id":run["id"],"scenario_id":run.get("scenario_id"),"source":run.get("source"),
             "replayed":False,"steps":[]}
    spec=None
    if scenario is not None:
        spec=effective_spec(run.get("domain") or scenario.domain)
        try:
            payload["steps"]=proof_steps(scenario.kind,run.get("trace") or [],spec,run.get("guardrails",False))
            payload["replayed"]=True
            return payload
        except (KeyError,TypeError,ValueError):
            payload["replayed"]=False
    payload["steps"]=steps_without_replay(run.get("trace") or [],spec)
    return payload


@app.get("/api/runs/{run_id}/proof")
def run_proof(run_id:str):
    run=database().get_run(run_id)
    if not run: raise HTTPException(404,"Run not found")
    return proof_for(run)


@app.get("/runs/{run_id}",include_in_schema=False)
def run_page(run_id:str):
    run=database().get_run(run_id)
    if not run: raise HTTPException(404,"Run not found")
    return HTMLResponse(evidence_html(proof_for(run)))

def failing_actions(run:dict)->list[dict]:
    if run.get("minimal_failing_actions"): return run["minimal_failing_actions"]
    return [{"tool":e["tool"],"args":e["args"]} for e in run["trace"]
            if e.get("allowed") and e.get("violation_if_executed")]


@app.post("/api/runs/{run_id}/repair",dependencies=[Depends(require_write)])
def repair_run(run_id:str,req:RepairRequest):
    """Save a rule that must block this run's failing trace and spare every safe control."""
    run=database().get_run(run_id)
    if not run: raise HTTPException(404,"Run not found")
    if run["evaluation"]["passed"]: raise HTTPException(409,"This run has no violation to repair")
    actions=failing_actions(run)
    spec=effective_spec(run["domain"])
    record={"id":"POL-"+uuid4().hex[:8].upper(),"domain":run["domain"],"policy_id":None,"status":"proposed",
            "source":"repair","run_id":run["id"],"failing_actions":actions,"created_at":utc_now(),
            "reviewed_at":None,"usage":{},"estimated_model_cost_usd":0}
    if req.mode=="muse":
        client=meta_client()
        try: draft,usage=client.repair_policy(req.text,actions,spec)
        except MetaError as e: raise meta_failure(e) from e
        record.update(usage=usage,estimated_model_cost_usd=estimate_cost(usage),usage_ids=client.usage_ids)
    else:
        if not req.rule or not req.invariant:
            raise HTTPException(422,"Manual repair needs a rule and an invariant name")
        record["draft"]={"text":req.text,"rule":req.rule,"invariant":req.invariant,"explanation":""}
        try: draft=PolicyDraft.model_validate(record["draft"])
        except ValidationError as exc: raise HTTPException(422,f"Draft is invalid: {exc.errors()[0]['msg']}") from exc
    with POLICY_ID_LOCK:
        record["policy_id"]=next_policy_id(run["domain"])
        record=recheck(record,draft)
        database().save_policy(record)
    return record


@app.post("/api/runs/{run_id}/replay",dependencies=[Depends(require_write)])
def replay(run_id:str,req:ReplayRequest):
    original=database().get_run(run_id)
    if not original: raise HTTPException(404,"Original run not found")
    scenario=get_scenario_or_404(original["scenario_id"])
    if scenario.status!="approved": raise HTTPException(409,"Scenario must remain approved")
    spec=effective_spec(scenario.domain)
    result=replay_actions(scenario.kind,executable_actions(original["trace"]),req.guardrails,spec)
    r={"id":"RUN-"+uuid4().hex[:10].upper(),"scenario_id":scenario.id,"domain":scenario.domain,
       "added_policies":[p.id for p in spec.added_policies],"created_at":utc_now(),
       "kind":"recorded_action_replay","source":"replay","guardrails":req.guardrails,
       "source_run_id":run_id,"objective":original.get("objective"),"pressure_level":original.get("pressure_level",0),
       "usage":{},"estimated_model_cost_usd":0,
       "note":"Replays recorded actions, not a second independent model decision; shows effect of tool-policy enforcement.",**result,
       "minimal_failing_actions":[] if req.guardrails else minimize_failure(scenario.kind,result["trace"],spec)}
    database().save_run(r)
    return r


def get_policy_or_404(id:str)->dict:
    record=database().get_policy(id)
    if not record: raise HTTPException(404,"Unknown compiled policy")
    return record


# Held from reading the next U-n to saving the draft, so concurrent compiles can't share an ID.
# Only covers one server process, which is all SQLite here supports anyway.
POLICY_ID_LOCK=threading.Lock()

def next_policy_id(domain:str)->str:
    numbers=[int(p["policy_id"].split("-")[1]) for p in database().list_policies(domain)]
    return f"U-{max(numbers,default=0)+1}"


def edited_draft(record:dict,edit:PolicyEdit)->PolicyDraft:
    changes={k:v for k,v in edit.model_dump(exclude_unset=True,exclude={"approved","mode"}).items() if v is not None}
    try: return PolicyDraft.model_validate({**record["draft"],**changes})
    except ValidationError as exc: raise HTTPException(422,f"Draft is invalid: {exc.errors()[0]['msg']}") from exc


def recheck(record:dict,draft:PolicyDraft)->dict:
    # Checked alongside the other approved rules for the domain, so clashes show up here.
    record["draft"]=draft.model_dump()
    spec=effective_spec(record["domain"],exclude=record["id"])
    # shortcut: a repair is rechecked against its stored trace, not the example lists in the editor.
    record["report"]=(check_guard(spec,draft,record["policy_id"],record["failing_actions"])
                      if record.get("failing_actions") is not None
                      else check_draft(spec,draft,record["policy_id"]))
    return record


def report_summary(report:dict)->str:
    problems=report["errors"]+[p for key in ("should_pass","should_fail","safe_controls") for x in report[key] for p in x["problems"]]
    return "; ".join(problems[:3]) or "checks did not pass"


@app.get("/api/domains/{domain}/policies")
def domain_policies(domain:str):
    spec=domain_spec(domain)
    return {"domain":domain,
            "spec_policies":[{"id":p.id,"text":p.text,"invariant":p.invariant,"rule":p.rule} for p in spec.policies],
            "compiled":list(reversed(database().list_policies(domain)))}


@app.post("/api/domains/{domain}/policies/compile",dependencies=[Depends(require_write)])
def compile_policy(domain:str,req:CompileRequest):
    spec=effective_spec(domain)
    record={"id":"POL-"+uuid4().hex[:8].upper(),"domain":domain,"policy_id":None,"status":"proposed",
            "source":req.mode,"created_at":utc_now(),"reviewed_at":None,"usage":{},"estimated_model_cost_usd":0}
    if req.mode=="muse":
        client=meta_client()
        try: draft,usage=client.compile_policy(req.text,spec)
        except MetaError as e: raise meta_failure(e) from e
        record.update(usage=usage,estimated_model_cost_usd=estimate_cost(usage),usage_ids=client.usage_ids)
    else:
        if not req.rule or not req.invariant:
            raise HTTPException(422,"Manual mode needs a rule and an invariant name")
        record["draft"]={"text":req.text,"rule":req.rule,"invariant":req.invariant,"explanation":""}
        draft=edited_draft(record,req)
    with POLICY_ID_LOCK:
        record["policy_id"]=next_policy_id(domain)
        record=recheck(record,draft)
        database().save_policy(record)
    return record


@app.post("/api/policies/{policy_id}/check",dependencies=[Depends(require_write)])
def check_policy(policy_id:str,req:PolicyEdit):
    """Save edits and re-run every check. Editing an approved rule takes it out of use until it is approved again."""
    record=get_policy_or_404(policy_id)
    record=recheck(record,edited_draft(record,req))
    if record["status"]=="approved": record["status"]="proposed"
    database().save_policy(record)
    return record


@app.post("/api/policies/{policy_id}/review",dependencies=[Depends(require_write)])
def review_policy(policy_id:str,req:PolicyReviewRequest):
    record=get_policy_or_404(policy_id)
    record=recheck(record,edited_draft(record,req))
    if req.approved and not record["report"]["ok"]:
        if record["status"]=="approved": record["status"]="proposed"
        database().save_policy(record)
        raise HTTPException(409,f"Fix the draft before approving it: {report_summary(record['report'])}")
    record.update(status="approved" if req.approved else "rejected",reviewed_at=utc_now())
    database().save_policy(record)
    return record
