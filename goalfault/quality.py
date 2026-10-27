"""The bar a domain pack has to clear before the dashboard lists it.

Everything here is deterministic: fixtures and safe controls are replayed in the sandbox,
no model is called. Whether the data is synthetic is a human review item and is not checked.
"""
from __future__ import annotations
from functools import lru_cache
from .simulator import executable_actions, fixture_run, minimize_failure, replay_actions
from .spec import DomainSpec, get_spec

MIN_TOOLS=4
MIN_POLICIES=3
MIN_FAILING_SCENARIOS=3
MIN_SAFE_CONTROLS=2


def blocked(trace:list[dict])->bool:
    return any(e["result"].get("error")=="policy_blocked" for e in trace)


def scenario_check(spec:DomainSpec,kind:str)->dict:
    invariant=spec.invariant_for(kind)
    baseline=fixture_run(kind,spec=spec)
    flagged={v["invariant"] for v in baseline["evaluation"]["violations"]}
    actions=len(spec.scenario(kind).fixture)
    shrunk=minimize_failure(kind,baseline["trace"],spec) if not baseline["evaluation"]["passed"] else []
    guarded=replay_actions(kind,executable_actions(baseline["trace"]),True,spec)
    problems=[]
    if invariant not in flagged: problems.append(f"fixture does not break {invariant}")
    if not shrunk: problems.append("shrinking found no failing actions")
    if not guarded["evaluation"]["passed"] or not blocked(guarded["trace"]): problems.append("guarded replay does not block it")
    return {"kind":kind,"ok":not problems,"problems":problems,"fixture_actions":actions,"shrunk_actions":len(shrunk)}


def control_check(spec:DomainSpec,control)->dict:
    actions=[a.model_dump() for a in control.actions]
    baseline=replay_actions(control.name,actions,spec=spec)
    guarded=replay_actions(control.name,actions,True,spec)
    problems=[]
    flags=baseline["evaluation"]["violations"]
    if flags: problems.append("flagged: "+", ".join(sorted({v["invariant"] for v in flags})))
    refused=[e for e in baseline["trace"] if not e["allowed"]]
    if refused: problems.append(f"step {refused[0]['step']} did not execute ({refused[0]['result'].get('error')})")
    if blocked(guarded["trace"]): problems.append("blocked when guards are on")
    return {"name":control.name,"ok":not problems,"problems":problems}


def quality_report(spec:DomainSpec)->dict:
    scenarios=[scenario_check(spec,k) for k in spec.kinds]
    controls=[control_check(spec,c) for c in spec.safe_controls]
    covered={s.policy for s in spec.scenarios}
    uncovered=[p.id for p in spec.policies if p.id not in covered]
    failing=sum(s["ok"] for s in scenarios)
    checks=[
        {"name":"tools","ok":len(spec.tools)>=MIN_TOOLS,"detail":f"{len(spec.tools)} tools, need {MIN_TOOLS}"},
        {"name":"policies","ok":len(spec.policies)>=MIN_POLICIES,"detail":f"{len(spec.policies)} policies, need {MIN_POLICIES}"},
        {"name":"failing_scenarios","ok":failing>=MIN_FAILING_SCENARIOS and failing==len(scenarios),
         "detail":f"{failing} of {len(scenarios)} fixtures fail, shrink and are blocked by guarded replay, need {MIN_FAILING_SCENARIOS}"},
        {"name":"policy_coverage","ok":not uncovered,"detail":"every policy has a failing scenario" if not uncovered else "no scenario for "+", ".join(uncovered)},
        {"name":"shrinking","ok":any(s["ok"] and s["shrunk_actions"]<s["fixture_actions"] for s in scenarios),
         "detail":"at least one fixture trace shrinks to fewer actions"},
        {"name":"safe_controls","ok":len(controls)>=MIN_SAFE_CONTROLS and all(c["ok"] for c in controls),
         "detail":f"{sum(c['ok'] for c in controls)} of {len(controls)} safe controls pass with zero flags, need {MIN_SAFE_CONTROLS}"},
    ]
    return {"domain":spec.name,"passed":all(c["ok"] for c in checks),"checks":checks,"scenarios":scenarios,"safe_controls":controls}


@lru_cache
def domain_quality(name:str)->dict:
    return quality_report(get_spec(name))
