"""Domain specs: tools, starting state, policies and scenarios as data.

A spec is loaded with yaml.safe_load, validated by Pydantic (unknown fields are rejected),
and every rule, binding, effect and result template is parsed and checked against the
spec's own tools and state before anything can run.
"""
from __future__ import annotations
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal as TypeLiteral
import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator
from . import rules
from .rules import Attr, Index, Name, RuleSyntaxError, is_finite_number

DOMAINS_DIR=Path(__file__).resolve().parent.parent/"domains"
DEFAULT_DOMAIN="customer_support"
IDENT=r"^[a-z][a-z0-9_]*$"
MAX_NESTING=50
RESERVED=rules.KEYWORDS|{"args","state",rules.ITEM}
EVALUATION_KEYS={"passed","violations","tool_calls","executed_tool_calls"}
PARAM_TYPES={"string":"string","number":"number","integer":"integer","boolean":"boolean"}
EFFECT_OPS=("set","increment","append","remove")

class SpecError(ValueError):
    """A spec that failed to load or validate. The message lists every problem found."""

class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid")

class Param(Strict):
    type: TypeLiteral["string","number","integer","boolean"]
    required: bool=True

class Check(Strict):
    when: str=Field(min_length=1,max_length=rules.MAX_RULE_LENGTH)
    error: str=Field(pattern=IDENT,max_length=60)

class Effect(Strict):
    set: str|None=None
    to: Any=None
    increment: str|None=None
    by: Any=None
    append: str|None=None
    value: Any=None
    remove: str|None=None

    @model_validator(mode="after")
    def one_operation(self):
        ops=[op for op in EFFECT_OPS if getattr(self,op) is not None]
        if len(ops)!=1:
            raise ValueError(f"an effect needs exactly one of {', '.join(EFFECT_OPS)}")
        op=ops[0]
        needs={"set":"to","increment":"by","append":"value"}.get(op)
        given={k for k in ("to","by","value") if k in self.model_fields_set}
        if given!=({needs} if needs else set()):
            raise ValueError(f"'{op}' takes {repr(needs) if needs else 'no other field'}, got {sorted(given) or 'none'}")
        return self

    @property
    def op(self)->str: return next(op for op in EFFECT_OPS if getattr(self,op) is not None)

    @property
    def operand(self)->Any: return {"set":self.to,"increment":self.by,"append":self.value}.get(self.op)

class Tool(Strict):
    name: str=Field(pattern=IDENT,max_length=60)
    description: str=Field(min_length=5,max_length=300)
    agent_description: str=Field(min_length=5,max_length=300)
    params: dict[str,Param]={}
    let: dict[str,str]={}
    preconditions: list[Check]=[]
    effects: list[Effect]=[]
    result: dict[str,Any]={}

    def normalize_args(self,raw:dict)->dict:
        """Coerce untrusted arguments to the declared types. Anything that doesn't fit becomes null."""
        out={}
        for name,p in self.params.items():
            v=raw.get(name)
            if p.type=="string": out[name]=str(v) if isinstance(v,(str,int,float)) and not isinstance(v,bool) else None
            elif p.type=="number": out[name]=float(v) if is_finite_number(v) else None
            elif p.type=="integer": out[name]=int(v) if is_finite_number(v) and v==int(v) else None
            else: out[name]=v if isinstance(v,bool) else None
        return out

    def json_schema(self)->dict:
        return {"type":"object","properties":{k:{"type":PARAM_TYPES[p.type]} for k,p in self.params.items()},
                "required":[k for k,p in self.params.items() if p.required],"additionalProperties":False}

class Policy(Strict):
    id: str=Field(pattern=r"^[A-Z][A-Z0-9]*-\d+$",max_length=20)
    text: str=Field(min_length=5,max_length=500)
    invariant: str=Field(pattern=IDENT,max_length=60)
    rule: str=Field(min_length=5,max_length=rules.MAX_RULE_LENGTH)

class FixtureAction(Strict):
    tool: str
    args: dict[str,Any]={}

class ScenarioSpec(Strict):
    kind: str=Field(pattern=IDENT,max_length=60)
    policy: str
    title: str=Field(min_length=5,max_length=120)
    description: str=Field(min_length=5,max_length=500)
    user_message: str=Field(min_length=5,max_length=1500)
    risk: TypeLiteral["high","critical"]
    template_title: str=Field(min_length=5,max_length=120)
    keywords: list[str]=[]
    fixture: list[FixtureAction]=Field(min_length=1)

class SafeControl(Strict):
    name: str=Field(pattern=IDENT,max_length=60)
    title: str=Field(min_length=5,max_length=120)
    description: str=Field(min_length=5,max_length=500)
    actions: list[FixtureAction]=Field(min_length=1)

class Prompts(Strict):
    agent: str=Field(min_length=20,max_length=4000)
    proposal: str=Field(min_length=20,max_length=2000)
    discover: str=Field(min_length=20,max_length=2000)

class CompiledTool:
    def __init__(self,tool:Tool):
        self.tool=tool
        self.lets:list[tuple[str,Any]]=[]
        self.checks:list[tuple[Any,str]]=[]
        self.effects:list[tuple[str,Any,Any]]=[]
        self.result:Any=None
        self.policies:list[tuple[Policy,Any]]=[]

class DomainSpec(Strict):
    version: TypeLiteral[1]=1
    name: str=Field(pattern=IDENT,max_length=60)
    # Seed scenario IDs become GF-<code>-001; a domain without a code uses GF-001.
    code: str|None=Field(default=None,pattern=r"^[A-Z]{2,6}$")
    title: str=Field(min_length=3,max_length=120)
    description: str=Field(min_length=5,max_length=1000)
    default_objective: str=Field(min_length=5,max_length=300)
    # Optional replacements for the generic pressure statements, by level 1-3.
    pressure: dict[int,str]={}
    prompts: Prompts
    initial_state: dict[str,Any]
    tools: list[Tool]=Field(min_length=1)
    policies: list[Policy]=Field(min_length=1)
    metrics: dict[str,str]={}
    scenarios: list[ScenarioSpec]=Field(min_length=1)
    safe_controls: list[SafeControl]=[]
    default_kind: str
    _tools: dict[str,CompiledTool]=PrivateAttr(default_factory=dict)
    _metrics: dict[str,Any]=PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def compile_and_check(self):
        errors:list[str]=[]
        def unique(label,values):
            seen=set()
            for v in values:
                if v in seen: errors.append(f"duplicate {label} {v!r}")
                seen.add(v)
        unique("tool",[t.name for t in self.tools])
        unique("policy id",[p.id for p in self.policies])
        unique("invariant",[p.invariant for p in self.policies])
        unique("scenario kind",[s.kind for s in self.scenarios])
        errors+=[f"initial_state.{e}" for e in json_problems(self.initial_state)]
        state_keys=set(self.initial_state)

        def parse(source,where,roots,params=None):
            try: node=rules.parse_expression(source)
            except RuleSyntaxError as exc:
                errors.append(f"{where}: {exc}")
                return None
            check_names(node,where,roots,params)
            return node

        def check_names(node,where,roots,params):
            for name,path in rules.names_used(node):
                if name not in roots:
                    errors.append(f"{where}: unknown name {name!r}; allowed here: {', '.join(sorted(roots))}")
                elif name=="args" and path and path[0] not in (params or {}):
                    errors.append(f"{where}: unknown argument {path[0]!r}")
                elif name=="state" and path and path[0] not in state_keys:
                    errors.append(f"{where}: unknown state field {path[0]!r}")

        def template(value,where,roots,params):
            if isinstance(value,str): return parse(value,where,roots,params)
            if isinstance(value,dict): return {k:template(v,f"{where}.{k}",roots,params) for k,v in value.items()}
            if isinstance(value,list): return [template(v,f"{where}[{i}]",roots,params) for i,v in enumerate(value)]
            if value is None or isinstance(value,(bool,int,float)): return rules.Literal(value)
            errors.append(f"{where}: unsupported value {type(value).__name__}")
            return None

        tools:dict[str,CompiledTool]={}
        for t in self.tools:
            where=f"tool {t.name}"
            c=CompiledTool(t)
            if t.name in rules.KEYWORDS: errors.append(f"{where}: {t.name!r} is a rule keyword and cannot be a tool name")
            for p in t.params:
                if not re.match(IDENT,p) or p in RESERVED: errors.append(f"{where}: bad parameter name {p!r}")
            roots={"args","state"}
            for name,source in t.let.items():
                if not re.match(IDENT,name) or name in RESERVED or name in roots:
                    errors.append(f"{where}: bad binding name {name!r}")
                c.lets.append((name,parse(source,f"{where}.let.{name}",set(roots),t.params)))
                roots.add(name)
            for i,check in enumerate(t.preconditions):
                c.checks.append((parse(check.when,f"{where}.preconditions[{i}]",roots,t.params),check.error))
            for i,effect in enumerate(t.effects):
                at=f"{where}.effects[{i}]"
                target=parse(getattr(effect,effect.op),at,roots,t.params)
                if target is not None and not assignable(target,roots-{"args"}):
                    errors.append(f"{at}: target must be a field of state or of a binding, e.g. order.refunded")
                c.effects.append((effect.op,target,template(effect.operand,at,roots,t.params) if effect.op!="remove" else None))
            c.result=template(t.result,f"{where}.result",roots,t.params)
            tools[t.name]=c

        for p in self.policies:
            where=f"policy {p.id}"
            try: rule=rules.parse_rule(p.rule)
            except RuleSyntaxError as exc:
                errors.append(f"{where}: {exc}")
                continue
            c=tools.get(rule.tool)
            if c is None:
                errors.append(f"{where}: unknown tool {rule.tool!r}")
                continue
            check_names(rule.condition,where,{"args","state",*(n for n,_ in c.lets)},c.tool.params)
            c.policies.append((p,rule.condition))

        metrics={}
        for name,source in self.metrics.items():
            if not re.match(IDENT,name) or name in EVALUATION_KEYS: errors.append(f"bad metric name {name!r}")
            metrics[name]=parse(source,f"metric {name}",{"state"})

        def check_actions(actions,where):
            for i,action in enumerate(actions):
                c=tools.get(action.tool)
                if c is None: errors.append(f"{where}[{i}]: unknown tool {action.tool!r}")
                else: errors.extend(f"{where}[{i}]: unknown argument {k!r}" for k in action.args if k not in c.tool.params)

        policy_ids={p.id for p in self.policies}
        for s in self.scenarios:
            where=f"scenario {s.kind}"
            if s.policy not in policy_ids: errors.append(f"{where}: unknown policy {s.policy!r}")
            check_actions(s.fixture,f"{where}.fixture")
        unique("safe control",[c.name for c in self.safe_controls])
        for control in self.safe_controls:
            check_actions(control.actions,f"safe control {control.name}.actions")
        for level,text in self.pressure.items():
            if level not in (1,2,3): errors.append(f"pressure: level {level} is not 1, 2 or 3")
            elif not 5<=len(text)<=300: errors.append(f"pressure.{level}: text must be 5 to 300 characters")
        if self.default_kind not in {s.kind for s in self.scenarios}:
            errors.append(f"default_kind {self.default_kind!r} is not a scenario kind")
        if errors: raise ValueError("; ".join(errors))
        self._tools,self._metrics=tools,metrics
        return self

    def tool(self,name:str)->CompiledTool|None: return self._tools.get(name)

    @property
    def metric_rules(self)->dict[str,Any]: return self._metrics

    def policy(self,id:str)->Policy: return next(p for p in self.policies if p.id==id)

    def scenario(self,kind:str)->ScenarioSpec: return next(s for s in self.scenarios if s.kind==kind)

    @property
    def kinds(self)->tuple[str,...]: return tuple(s.kind for s in self.scenarios)

    def invariant_for(self,kind:str)->str: return self.policy(self.scenario(kind).policy).invariant

    def fresh_state(self)->dict: return deepcopy(self.initial_state)

    def seed_id(self,index:int)->str: return f"GF-{self.code}-{index:03}" if self.code else f"GF-{index:03}"

    def with_policies(self,extra:list)->DomainSpec:
        """A copy of this spec with more policies, validated from scratch like a freshly loaded file."""
        data=self.model_dump(exclude_unset=True)
        data["policies"]=[*data["policies"],*(p.model_dump(exclude_unset=True) if isinstance(p,Policy) else p for p in extra)]
        return validate(data)


def assignable(node,roots:set)->bool:
    if not isinstance(node,(Attr,Index)): return False
    while isinstance(node,(Attr,Index)): node=node.obj
    return isinstance(node,Name) and node.id in roots

def json_problems(value,path="")->list[str]:
    if value is None or isinstance(value,(str,bool,int,float)): return []
    if isinstance(value,list): return [e for i,v in enumerate(value) for e in json_problems(v,f"{path}[{i}]")]
    if isinstance(value,dict):
        bad=[f"{path or 'root'}: keys must be strings" for k in value if not isinstance(k,str)][:1]
        return bad+[e for k,v in value.items() for e in json_problems(v,f"{path}.{k}" if path else str(k))]
    return [f"{path}: {type(value).__name__} is not allowed; quote dates and other special values"]

def render(template,env:dict)->Any:
    """Evaluate a compiled result or effect template into plain data."""
    if isinstance(template,dict): return {k:render(v,env) for k,v in template.items()}
    if isinstance(template,list): return [render(v,env) for v in template]
    return deepcopy(rules.evaluate(template,env))

def shape_problem(value)->str|None:
    """YAML anchors can build self-referencing or absurdly deep data; refuse both before walking it."""
    active:set[int]=set()
    def walk(v,depth):
        if not isinstance(v,(dict,list)): return None
        if id(v) in active: return "Spec contains a recursive YAML alias"
        if depth>MAX_NESTING: return f"Spec is nested more than {MAX_NESTING} levels deep"
        active.add(id(v))
        for child in (v.values() if isinstance(v,dict) else v):
            problem=walk(child,depth+1)
            if problem: return problem
        active.discard(id(v))
        return None
    return walk(value,0)

def parse_spec(text:str)->DomainSpec:
    try: data=yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"Spec is not valid YAML: {exc}") from exc
    except RecursionError as exc:
        raise SpecError(f"Spec is nested more than {MAX_NESTING} levels deep") from exc
    if not isinstance(data,dict): raise SpecError("Spec must be a YAML mapping")
    problem=shape_problem(data)
    if problem: raise SpecError(problem)
    return validate(data)

def validate(data:dict)->DomainSpec:
    try: return DomainSpec.model_validate(data)
    except ValidationError as exc:
        raise SpecError("Spec is invalid:\n"+"\n".join(
            f"- {'.'.join(str(x) for x in e['loc']) or 'spec'}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors())) from exc

def load_spec(path:str|Path)->DomainSpec:
    return parse_spec(Path(path).read_text(encoding="utf-8"))

class UnknownDomain(KeyError):
    pass

@lru_cache
def registry()->dict[str,DomainSpec]:
    """Every spec in domains/, keyed by name. One broken file stops the server rather than being skipped."""
    specs:dict[str,DomainSpec]={}
    seed_ids:set[str]=set()
    for path in sorted(DOMAINS_DIR.glob("*.yaml")):
        try: spec=load_spec(path)
        except SpecError as exc: raise SpecError(f"{path.name}: {exc}") from exc
        if spec.name!=path.stem: raise SpecError(f"{path.name}: name {spec.name!r} must match the file name")
        ids={spec.seed_id(i) for i in range(1,len(spec.scenarios)+1)}
        if ids&seed_ids: raise SpecError(f"{path.name}: seed scenario IDs clash with another domain; set a unique code")
        seed_ids|=ids
        specs[spec.name]=spec
    if DEFAULT_DOMAIN not in specs: raise SpecError(f"domains/{DEFAULT_DOMAIN}.yaml is missing")
    return specs

def get_spec(name:str)->DomainSpec:
    try: return registry()[name]
    except KeyError: raise UnknownDomain(name) from None

def default_spec()->DomainSpec:
    return get_spec(DEFAULT_DOMAIN)
