"""Run a domain file's policies in front of ordinary Python functions. No server and no database."""
from __future__ import annotations
from pathlib import Path
from .simulator import Sandbox
from .spec import load_spec

class PolicyBlocked(Exception):
    def __init__(self, rule: str):
        self.rule = rule
        super().__init__(rule)

def guard(spec_path: str | Path):
    """Decorate tool functions. They share one sandbox, so a later call sees effects from an earlier one.

    shortcut: the YAML file only, not approved policies that exist only in the database; keyword arguments only; the function name must be the tool name. Copy a database rule into the file when the export should enforce it.
    """
    spec = load_spec(spec_path)
    box = Sandbox(spec.default_kind, enforce=True, spec=spec)

    def decorate(fn):
        def wrapped(**kwargs):
            result = box.execute(fn.__name__, kwargs)
            if result.get("error") == "policy_blocked":
                raise PolicyBlocked(result["rule"])
            if result.get("error"):
                return result
            return fn(**kwargs)
        wrapped.decisions = box.events
        return wrapped
    return decorate
