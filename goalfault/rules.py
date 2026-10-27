"""A tiny rule language for domain specs.

Rules are parsed by our own tokenizer and recursive-descent parser into a small AST,
then interpreted. Nothing is ever passed to Python's eval or exec, so a rule written
by a person or proposed by a model can only do what this grammar allows.

    rule     := 'deny' NAME 'when' expr
    expr     := and ('or' and)*
    and      := not ('and' not)*
    not      := 'not' not | compare
    compare  := sum (('=='|'!='|'<'|'<='|'>'|'>='|'in') sum)?
    sum      := unary (('+'|'-') unary)*
    unary    := '-' unary | postfix
    postfix  := primary ('.' NAME | '[' expr ']')*
    primary  := NUMBER | STRING | true | false | null | NAME | NAME '(' args ')' | '(' expr ')' | '[' args ']'

Evaluation never raises on bad data: a missing field is null, ordering comparisons
between mismatched types are false, and arithmetic on non-numbers is null.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any

MAX_RULE_LENGTH=2000
MAX_DEPTH=40
KEYWORDS={"and","or","not","in","true","false","null","deny","when"}
ITEM="item"
# name -> (min args, max args, whether the second argument is evaluated once per item)
FUNCTIONS={"exists":(2,2,True),"all":(2,2,True),"count":(1,2,True),"sum":(2,2,True),"len":(1,1,False)}
COMPARE_OPS=("==","!=","<=",">=","<",">","in")

class RuleSyntaxError(ValueError):
    def __init__(self,message:str,source:str="",position:int|None=None):
        self.message,self.source,self.position=message,source,position
        where=f" at column {position+1}" if position is not None else ""
        super().__init__(f"{message}{where}: {source}" if source else message)

@dataclass(frozen=True)
class Literal:
    value: Any
@dataclass(frozen=True)
class Name:
    id: str
@dataclass(frozen=True)
class Attr:
    obj: Any
    name: str
@dataclass(frozen=True)
class Index:
    obj: Any
    key: Any
@dataclass(frozen=True)
class Unary:
    op: str
    operand: Any
@dataclass(frozen=True)
class Binary:
    op: str
    left: Any
    right: Any
@dataclass(frozen=True)
class Call:
    fn: str
    args: tuple
@dataclass(frozen=True)
class Array:
    items: tuple
@dataclass(frozen=True)
class Rule:
    tool: str
    condition: Any
    source: str

TOKEN=re.compile(r"""\s*(?:
    (?P<number>\d+(?:\.\d+)?)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|<=|>=|<|>|\+|-|\(|\)|\[|\]|\.|,)
)""",re.VERBOSE)

def tokenize(source:str)->list[tuple[str,Any,int]]:
    if len(source)>MAX_RULE_LENGTH:
        raise RuleSyntaxError(f"Rule is longer than {MAX_RULE_LENGTH} characters")
    tokens,pos=[],0
    while pos<len(source):
        if source[pos:].strip()=="": break
        m=TOKEN.match(source,pos)
        if not m or m.end()==pos:
            start=len(source)-len(source[pos:].lstrip())
            raise RuleSyntaxError(f"Unexpected character {source[start]!r}",source,start)
        kind=m.lastgroup
        text=m.group(kind)
        start=m.start(kind)
        if kind=="number": value=float(text) if "." in text else int(text)
        elif kind=="string": value=re.sub(r"\\(.)",r"\1",text[1:-1])
        else: value=text
        if kind=="name" and text in KEYWORDS: kind="keyword"
        tokens.append((kind,value,start))
        pos=m.end()
    tokens.append(("end",None,len(source)))
    return tokens

class Parser:
    def __init__(self,source:str):
        self.source=source
        self.tokens=tokenize(source)
        self.i=0
        self.depth=0

    def peek(self): return self.tokens[self.i]

    def error(self,message:str,token=None):
        token=token or self.peek()
        return RuleSyntaxError(message,self.source,token[2])

    def take(self,kind:str,value=None):
        tok=self.peek()
        if tok[0]!=kind or (value is not None and tok[1]!=value):
            want=repr(value) if value is not None else kind
            got="end of rule" if tok[0]=="end" else repr(tok[1])
            raise self.error(f"Expected {want}, found {got}")
        self.i+=1
        return tok

    def at(self,kind:str,value=None)->bool:
        tok=self.peek()
        return tok[0]==kind and (value is None or tok[1]==value)

    def nested(self):
        self.depth+=1
        if self.depth>MAX_DEPTH: raise self.error("Rule is nested too deeply")

    def finish(self):
        if not self.at("end"): raise self.error(f"Unexpected {self.peek()[1]!r}")

    def rule(self)->Rule:
        self.take("keyword","deny")
        tool=self.take("name")[1]
        self.take("keyword","when")
        condition=self.expr()
        self.finish()
        return Rule(tool,condition,self.source)

    def expr(self):
        self.nested()
        node=self.and_()
        while self.at("keyword","or"):
            self.i+=1
            node=Binary("or",node,self.and_())
        self.depth-=1
        return node

    def and_(self):
        node=self.not_()
        while self.at("keyword","and"):
            self.i+=1
            node=Binary("and",node,self.not_())
        return node

    def not_(self):
        if self.at("keyword","not"):
            self.i+=1
            self.nested()
            node=Unary("not",self.not_())
            self.depth-=1
            return node
        return self.compare()

    def compare(self):
        node=self.sum()
        tok=self.peek()
        if (tok[0]=="op" and tok[1] in COMPARE_OPS) or (tok[0]=="keyword" and tok[1]=="in"):
            self.i+=1
            node=Binary(tok[1],node,self.sum())
            nxt=self.peek()
            if (nxt[0]=="op" and nxt[1] in COMPARE_OPS) or (nxt[0]=="keyword" and nxt[1]=="in"):
                raise self.error("Chained comparisons are not allowed; join them with 'and'")
        return node

    def sum(self):
        node=self.unary()
        while self.peek()[0]=="op" and self.peek()[1] in ("+","-"):
            op=self.take("op")[1]
            node=Binary(op,node,self.unary())
        return node

    def unary(self):
        if self.at("op","-"):
            self.i+=1
            self.nested()
            node=Unary("-",self.unary())
            self.depth-=1
            return node
        return self.postfix()

    def postfix(self):
        node=self.primary()
        while True:
            if self.at("op","."):
                self.i+=1
                node=Attr(node,self.take("name")[1])
            elif self.at("op","["):
                self.i+=1
                node=Index(node,self.expr())
                self.take("op","]")
            else:
                return node

    def primary(self):
        tok=self.peek()
        kind,value=tok[0],tok[1]
        if kind in ("number","string"):
            self.i+=1
            return Literal(value)
        if kind=="keyword" and value in ("true","false","null"):
            self.i+=1
            return Literal({"true":True,"false":False,"null":None}[value])
        if kind=="name":
            self.i+=1
            if self.at("op","("):
                return self.call(value,tok)
            return Name(value)
        if self.at("op","("):
            self.i+=1
            node=self.expr()
            self.take("op",")")
            return node
        if self.at("op","["):
            self.i+=1
            items=[]
            if not self.at("op","]"):
                items.append(self.expr())
                while self.at("op",","):
                    self.i+=1
                    items.append(self.expr())
            self.take("op","]")
            return Array(tuple(items))
        if kind=="end": raise self.error("Rule ended early")
        raise self.error(f"Unexpected {value!r}")

    def call(self,fn:str,tok):
        if fn not in FUNCTIONS:
            raise self.error(f"Unknown function {fn!r}; allowed: {', '.join(sorted(FUNCTIONS))}",tok)
        self.take("op","(")
        args=[]
        if not self.at("op",")"):
            args.append(self.expr())
            while self.at("op",","):
                self.i+=1
                args.append(self.expr())
        self.take("op",")")
        low,high,_=FUNCTIONS[fn]
        if not low<=len(args)<=high:
            expected=str(low) if low==high else f"{low} or {high}"
            raise self.error(f"{fn}() takes {expected} argument(s), got {len(args)}",tok)
        return Call(fn,tuple(args))


def parse_expression(source:str):
    if not isinstance(source,str) or not source.strip():
        raise RuleSyntaxError("Expression is empty")
    p=Parser(source)
    node=p.expr()
    p.finish()
    return node

def parse_rule(source:str)->Rule:
    if not isinstance(source,str) or not source.strip():
        raise RuleSyntaxError("Rule is empty")
    return Parser(source).rule()


def is_number(v)->bool:
    return isinstance(v,(int,float)) and not isinstance(v,bool)

def items_of(v)->list:
    if isinstance(v,dict): return list(v.values())
    if isinstance(v,list): return v
    return []

def equal(a,b)->bool:
    # true is not 1 here, unlike Python.
    if isinstance(a,bool) or isinstance(b,bool):
        return isinstance(a,bool) and isinstance(b,bool) and a==b
    return a==b

def compare(op:str,a,b)->bool:
    if op=="==": return equal(a,b)
    if op=="!=": return not equal(a,b)
    if op=="in":
        if isinstance(b,dict): return isinstance(a,(str,int,float)) and not isinstance(a,bool) and a in b
        if isinstance(b,list): return any(equal(a,x) for x in b)
        if isinstance(b,str): return isinstance(a,str) and a in b
        return False
    if not ((is_number(a) and is_number(b)) or (isinstance(a,str) and isinstance(b,str))):
        return False
    return {"<":a<b,"<=":a<=b,">":a>b,">=":a>=b}[op]

def evaluate(node,env:dict)->Any:
    """Evaluate a parsed expression. Values found in `env` are returned by reference."""
    if isinstance(node,Literal): return node.value
    if isinstance(node,Name): return env.get(node.id)
    if isinstance(node,Attr):
        obj=evaluate(node.obj,env)
        return obj.get(node.name) if isinstance(obj,dict) else None
    if isinstance(node,Index):
        obj,key=evaluate(node.obj,env),evaluate(node.key,env)
        if isinstance(obj,dict):
            return obj.get(key) if key is None or isinstance(key,(str,int,float,bool)) else None
        if isinstance(obj,list) and is_number(key) and int(key)==key and -len(obj)<=key<len(obj):
            return obj[int(key)]
        return None
    if isinstance(node,Unary):
        value=evaluate(node.operand,env)
        if node.op=="not": return not bool(value)
        return -value if is_number(value) else None
    if isinstance(node,Binary):
        if node.op=="and": return bool(evaluate(node.left,env)) and bool(evaluate(node.right,env))
        if node.op=="or": return bool(evaluate(node.left,env)) or bool(evaluate(node.right,env))
        a,b=evaluate(node.left,env),evaluate(node.right,env)
        if node.op in ("+","-"):
            if not (is_number(a) and is_number(b)): return None
            return a+b if node.op=="+" else a-b
        return compare(node.op,a,b)
    if isinstance(node,Call): return call(node,env)
    if isinstance(node,Array): return [evaluate(x,env) for x in node.items]
    raise TypeError(f"Not a rule node: {node!r}")

def call(node:Call,env:dict):
    fn=node.fn
    if fn=="len":
        v=evaluate(node.args[0],env)
        return len(v) if isinstance(v,(dict,list,str)) else 0
    collection=items_of(evaluate(node.args[0],env))
    if fn=="count" and len(node.args)==1: return len(collection)
    per_item=node.args[1]
    values=[evaluate(per_item,{**env,ITEM:x}) for x in collection]
    if fn=="exists": return any(bool(v) for v in values)
    if fn=="all": return all(bool(v) for v in values)
    if fn=="count": return sum(1 for v in values if bool(v))
    if fn=="sum": return sum(v for v in values if is_number(v))
    raise TypeError(f"Unknown function {fn}")


def names_used(node,bound:frozenset=frozenset())->list[tuple[str,tuple[str,...]]]:
    """Every free name with the attribute path that follows it, e.g. ('args', ('amount',))."""
    found:list=[]
    def path_of(n):
        parts=[]
        while isinstance(n,Attr):
            parts.append(n.name)
            n=n.obj
        return n,tuple(reversed(parts))
    def walk(n,bound):
        if isinstance(n,Literal): return
        if isinstance(n,Name):
            if n.id not in bound: found.append((n.id,()))
            return
        if isinstance(n,Attr):
            root,parts=path_of(n)
            if isinstance(root,Name):
                if root.id not in bound: found.append((root.id,parts))
            else: walk(root,bound)
            return
        if isinstance(n,Index): walk(n.obj,bound); walk(n.key,bound); return
        if isinstance(n,Unary): walk(n.operand,bound); return
        if isinstance(n,Array):
            for x in n.items: walk(x,bound)
            return
        if isinstance(n,Binary): walk(n.left,bound); walk(n.right,bound); return
        if isinstance(n,Call):
            walk(n.args[0],bound)
            for a in n.args[1:]: walk(a,bound|{ITEM} if FUNCTIONS[n.fn][2] else bound)
    walk(node,bound)
    return found
