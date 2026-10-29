"""Rebuild a stored run into action, state change, rule, and policy line.

State is not saved on the run. It is replayed from the spec. The matched rules
are the ones stored on the run, not a fresh judgment.
"""
from __future__ import annotations
import html
import json
from copy import deepcopy
from .simulator import Sandbox
from .spec import DomainSpec

# shortcut: only the first 12 changed fields are listed, raise this when a tool mutates more
MAX_CHANGES = 12

SOURCE_NOTE = {
    "demo_fixture": "Scripted fixture. These calls were written in the spec, not chosen by a model.",
    "muse": "Live Muse run. The calls are model requests executed in the fake sandbox.",
    "replay": "Replay of recorded calls, not a new model decision.",
}


def _shown(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    text = json.dumps(value, default=str)
    return text if len(text) <= 180 else text[:177] + "..."


def state_changes(before, after, prefix=""):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        found = []
        keys = list(before)
        for key in after:
            if key not in before:
                keys.append(key)
        for key in keys:
            path = f"{prefix}.{key}" if prefix else str(key)
            found.extend(state_changes(before.get(key), after.get(key), path))
        return found
    return [{"path": prefix or "state", "before": _shown(before), "after": _shown(after)}]


def _policies(matched, by_id):
    rows = []
    for item in matched or []:
        policy = by_id.get(item.get("policy"))
        rows.append({
            "id": item.get("policy"),
            "invariant": item.get("invariant"),
            "text": policy.text if policy else None,
            "rule": policy.rule if policy else None,
        })
    return rows


def _step(event, changes, by_id, matches, skipped):
    result = event.get("result") or {}
    return {
        "step": event.get("step"),
        "tool": event.get("tool"),
        "args": event.get("args") or {},
        "allowed": bool(event.get("allowed")),
        "result": result,
        "state_changes": changes,
        "policies": _policies(event.get("matched_policies"), by_id),
        "replay_matches": None if skipped else matches,
        "blocked": isinstance(result, dict) and result.get("error") == "policy_blocked",
        "not_executed": skipped,
    }


def steps_without_replay(trace: list[dict], spec: DomainSpec | None) -> list[dict]:
    """Policies from the stored events. No state, because the trace was not replayed."""
    by_id = {policy.id: policy for policy in spec.policies} if spec else {}
    steps = []
    for event in trace:
        skipped = bool(event.get("arg_error"))
        step = _step(event, [], by_id, True, skipped)
        if not skipped:
            step["replay_matches"] = None
        steps.append(step)
    return steps


def proof_steps(kind: str, trace: list[dict], spec: DomainSpec, guardrails: bool = False) -> list[dict]:
    by_id = {policy.id: policy for policy in spec.policies}
    sandbox = Sandbox(kind, enforce=bool(guardrails), spec=spec)
    steps = []
    for event in trace:
        if event.get("arg_error"):
            steps.append(_step(event, [], by_id, True, True))
            continue
        before = deepcopy(sandbox.state)
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        sandbox.execute(event.get("tool"), args)
        replayed = sandbox.events[-1]
        changes = state_changes(before, sandbox.state)[:MAX_CHANGES]
        matches = replayed.get("result") == event.get("result") and replayed.get("allowed") == bool(event.get("allowed"))
        steps.append(_step(event, changes, by_id, matches, False))
    return steps


def evidence_html(proof: dict) -> str:
    """One run as a page. Every value is escaped."""
    def esc(value):
        return html.escape(str(value), quote=True)
    title = esc(proof.get("run_id"))
    note = esc(SOURCE_NOTE.get(proof.get("source"), "Stored run."))
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        f"<title>GoalFault evidence {title}</title>",
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:740px;margin:32px auto;padding:0 16px;color:#142033}",
        "article{border-top:1px solid #d5dde8;padding:12px 0}code{font-size:14px}</style></head><body>",
        "<p>GoalFault evidence</p>",
        f"<h1>{title}</h1>",
        f"<p>{note} Scenario {esc(proof.get('scenario_id'))}.</p>",
    ]
    if not proof.get("replayed"):
        parts.append("<p>State was not replayed. The rules below are the ones stored on the run.</p>")
    for step in proof.get("steps") or []:
        changes = step.get("state_changes") or []
        change_text = "; ".join(
            f"{c['path']}: {json.dumps(c['before'])} → {json.dumps(c['after'])}" for c in changes
        ) or "no change"
        parts.append("<article>")
        parts.append(f"<h2>{esc(step.get('step'))} · {esc(step.get('tool'))}</h2>")
        parts.append(f"<p>Action: <code>{esc(json.dumps(step.get('args') or {}))}</code></p>")
        parts.append(f"<p>State: {esc(change_text)}</p>")
        if step.get("not_executed"):
            parts.append("<p>This call was not run.</p>")
        if step.get("blocked"):
            parts.append("<p>Blocked before the tool ran.</p>")
        if step.get("replay_matches") is False:
            parts.append("<p>State replay did not match the stored tool result.</p>")
        policies = step.get("policies") or []
        if not policies:
            parts.append("<p>Rule: none</p>")
        for policy in policies:
            rule = policy.get("rule") or policy.get("invariant") or ""
            parts.append(f"<p>Rule {esc(policy.get('id'))}: <code>{esc(rule)}</code></p>")
            if policy.get("text"):
                parts.append(f"<p>Policy: {esc(policy.get('text'))}</p>")
        parts.append("</article>")
    parts.append("</body></html>")
    return "".join(parts)
