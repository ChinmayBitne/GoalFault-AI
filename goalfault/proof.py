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
    """One run as a modern security audit page. Every value is escaped."""
    def esc(value):
        return html.escape(str(value), quote=True)
    title = esc(proof.get("run_id"))
    note = esc(SOURCE_NOTE.get(proof.get("source"), "Stored run."))
    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        f"<title>GoalFault evidence {title}</title>",
        "<style>",
        "body{font:14px/1.6 system-ui,-apple-system,sans-serif;max-width:800px;margin:32px auto;padding:0 20px;background:#080d14;color:#e7eff9}",
        "h1{font-size:24px;margin:8px 0;letter-spacing:-0.5px}",
        "h2{font-size:16px;margin:0 0 10px;color:#c5f16e}",
        "p{margin:6px 0;color:#9eb1cf}",
        "a{color:#c5f16e;text-decoration:none}",
        "article{background:#101a27;border:1px solid #243144;border-radius:10px;padding:16px 20px;margin:16px 0}",
        "article.violated{border-left:4px solid #ff827f;background:#171116}",
        "code{font-family:monospace;font-size:13px;background:#0a1420;border:1px solid #283a4f;border-radius:4px;padding:2px 6px;color:#a5d6a7;word-break:break-all}",
        ".tag-viol{display:inline-block;background:#49272d;color:#ffa3a5;font-weight:700;font-size:10px;padding:3px 8px;border-radius:4px;margin-left:8px;vertical-align:middle}",
        ".rule-box{background:#1f1317;border:1px solid #5a272e;border-radius:8px;padding:10px 14px;margin-top:10px}",
        ".rule-box code{background:#130b0f;border-color:#5a272e;color:#ffa3a5}",
        ".back-btn{display:inline-block;margin-bottom:18px;font-size:12px;font-weight:700}",
        "</style></head><body>",
        "<a href='/' class='back-btn'>&larr; Back to GoalFault Dashboard</a>",
        "<p style='color:#7f9df9;font-weight:700;font-size:11px;letter-spacing:1px;text-transform:uppercase;'>GoalFault Evidence & Verification Report</p>",
        f"<h1>{title}</h1>",
        f"<p>{note} Scenario {esc(proof.get('scenario_id'))}.</p>",
    ]
    if not proof.get("replayed"):
        parts.append("<p style='color:#ffd385'>State was not replayed. The rules below are the ones stored on the run.</p>")
    for step in proof.get("steps") or []:
        changes = step.get("state_changes") or []
        change_text = "; ".join(
            f"{c['path']}: {json.dumps(c['before'])} → {json.dumps(c['after'])}" for c in changes
        ) or "no change"
        policies = step.get("policies") or []
        is_violated = bool(policies)
        viol_tag = "<span class='tag-viol'>POLICY VIOLATION</span>" if is_violated else ""
        art_cls = "article violated" if is_violated else "article"
        parts.append(f"<{art_cls}>")
        parts.append(f"<h2>Step {esc(step.get('step'))} · {esc(step.get('tool'))}{viol_tag}</h2>")
        parts.append(f"<p>Action: <code>{esc(json.dumps(step.get('args') or {}))}</code></p>")
        parts.append(f"<p>State: <code>{esc(change_text)}</code></p>")
        if step.get("not_executed"):
            parts.append("<p style='color:#ffa3a5'>This call was not run.</p>")
        if step.get("blocked"):
            parts.append("<p style='color:#ffa3a5'>Blocked before the tool ran.</p>")
        if step.get("replay_matches") is False:
            parts.append("<p style='color:#ffd385'>State replay did not match the stored tool result.</p>")
        if not policies:
            parts.append("<p>Rule: none</p>")
        for policy in policies:
            rule = policy.get("rule") or policy.get("invariant") or ""
            parts.append("<div class='rule-box'>")
            parts.append(f"<p style='margin:0 0 4px;font-weight:700;color:#ffa3a5;'>Rule {esc(policy.get('id'))}: <code>{esc(rule)}</code></p>")
            if policy.get("text"):
                parts.append(f"<p style='margin:0;color:#e7eff9;'><strong>Policy:</strong> {esc(policy.get('text'))}</p>")
            parts.append("</div>")
        parts.append("</article>")
    parts.append("</body></html>")
    return "".join(parts)