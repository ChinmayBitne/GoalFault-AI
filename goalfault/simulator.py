from __future__ import annotations
from copy import deepcopy
from typing import Any
from . import rules
from .rules import Attr, Index, is_number
from .spec import CompiledTool, DomainSpec, default_spec, render

class EffectError(Exception): pass

class Sandbox:
    """Pure in-memory fake business system driven by a domain spec. No network, payments or user databases."""
    def __init__(self, kind: str, enforce: bool=False, spec: DomainSpec|None=None):
        self.spec=spec or default_spec()
        self.state=self.spec.fresh_state()
        self.enforce=enforce
        self.events=[]

    def execute(self, tool: str, args: dict[str,Any]) -> dict:
        # Arguments are untrusted, even for calls originating from a model.
        event={"step":len(self.events)+1,"tool":tool,"args":deepcopy(args),"allowed":False,"result":{},
               "violation_if_executed":None,"matched_policies":[]}
        compiled=self.spec.tool(tool)
        if compiled is None:
            result={"error":"unrecognized_tool"}
        else:
            env={"state":self.state,"args":compiled.tool.normalize_args(args if isinstance(args,dict) else {})}
            for name,node in compiled.lets:
                env[name]=rules.evaluate(node,env)
            # Policies are judged on the state before the call, whether or not it goes on to run.
            broken=[policy for policy,condition in compiled.policies if rules.evaluate(condition,env)]
            event["matched_policies"]=[{"policy":p.id,"invariant":p.invariant} for p in broken]
            event["violation_if_executed"]=broken[0].invariant if broken else None
            failed=next((error for condition,error in compiled.checks if rules.evaluate(condition,env)),None)
            if failed:
                result={"error":failed}
            elif broken and self.enforce:
                result={"error":"policy_blocked","rule":broken[0].id}
            else:
                try:
                    result=self.apply(compiled,env)
                    event["allowed"]=True
                except EffectError:
                    result={"error":"effect_failed"}
        event["result"]=result
        self.events.append(event)
        return deepcopy(result)

    def apply(self, compiled: CompiledTool, env: dict) -> dict:
        """Run the tool's effects in order; if any cannot apply, the state is left exactly as it was."""
        before=deepcopy(self.state)
        try:
            for op,target,value in compiled.effects:
                apply_effect(op,target,value,env)
        except EffectError:
            self.state.clear()
            self.state.update(before)
            raise
        return render(compiled.result,env)

    def reject(self, tool: str, raw_args: Any, error: str, **extra) -> dict:
        """Record a requested call whose arguments could not be used; the tool is not executed."""
        result={"error":"invalid_arguments","detail":error}
        self.events.append({"step":len(self.events)+1,"tool":tool,"args":{},"raw_arguments":str(raw_args)[:500],
            "arg_error":error,"allowed":False,"result":result,"violation_if_executed":None,"matched_policies":[],**extra})
        return deepcopy(result)

    def evaluate(self) -> dict:
        violations=[{"step":event["step"],"invariant":m["invariant"],"policy":m["policy"],"tool":event["tool"]}
                    for event in self.events if event["allowed"] for m in event["matched_policies"]]
        metrics={name:rules.evaluate(node,{"state":self.state}) for name,node in self.spec.metric_rules.items()}
        return {"passed":len(violations)==0,"violations":violations,**metrics,
                "tool_calls":len(self.events),"executed_tool_calls":sum(e["allowed"] for e in self.events)}


def resolve_target(target, env: dict) -> tuple[Any,Any]:
    parent=rules.evaluate(target.obj,env)
    key=target.name if isinstance(target,Attr) else rules.evaluate(target.key,env)
    if isinstance(parent,dict) and isinstance(key,str):
        return parent,key
    if isinstance(target,Index) and isinstance(parent,list) and is_number(key) and int(key)==key and -len(parent)<=key<len(parent):
        return parent,int(key)
    raise EffectError("effect target does not exist")


def apply_effect(op: str, target, value, env: dict):
    parent,key=resolve_target(target,env)
    if op=="set":
        parent[key]=render(value,env)
    elif op=="increment":
        current,by=parent.get(key) if isinstance(parent,dict) else parent[key],render(value,env)
        if not (is_number(current) and is_number(by)): raise EffectError("increment needs numbers")
        parent[key]=current+by
    elif op=="append":
        items=parent.get(key) if isinstance(parent,dict) else parent[key]
        if not isinstance(items,list): raise EffectError("append needs a list")
        items.append(render(value,env))
    elif op=="remove":
        if isinstance(parent,dict) and key not in parent: raise EffectError("nothing to remove")
        parent.pop(key)


def executable_actions(trace: list[dict]) -> list[dict]:
    return [{"tool":e["tool"],"args":e["args"]} for e in trace if not e.get("arg_error")]


def fixture_actions(kind: str, spec: DomainSpec|None=None) -> list[dict]:
    """Explicit test stimuli, not purported model actions."""
    return [a.model_dump() for a in (spec or default_spec()).scenario(kind).fixture]


def replay_actions(kind: str, actions: list[dict], guardrails: bool=False, spec: DomainSpec|None=None) -> dict:
    sandbox=Sandbox(kind,enforce=guardrails,spec=spec)
    for action in actions:
        sandbox.execute(action["tool"], action["args"])
    return {"trace":sandbox.events,"evaluation":sandbox.evaluate(),"final_state":sandbox.state}


def fixture_run(kind: str, guardrails: bool=False, spec: DomainSpec|None=None) -> dict:
    return replay_actions(kind,fixture_actions(kind,spec),guardrails,spec)


def minimize_failure(kind: str, trace: list[dict], spec: DomainSpec|None=None) -> list[dict]:
    """Greedy trace reduction with deterministic state replay; no claim of global minimum."""
    actions=executable_actions(trace)
    if replay_actions(kind,actions,spec=spec)["evaluation"]["passed"]:
        return []
    i=0
    while i<len(actions):
        candidate=actions[:i]+actions[i+1:]
        if not replay_actions(kind,candidate,spec=spec)["evaluation"]["passed"]:
            actions=candidate
        else:
            i+=1
    return actions
