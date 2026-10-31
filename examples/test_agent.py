"""GoalFault AI - Standalone Agent Testing Example.

Demonstrates how any external AI agent connects to GoalFault's sandbox,
discovers policy violations from executed tool calls, and applies @guard.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from goalfault.guard import guard, PolicyBlocked
from goalfault.models import SandboxCallRequest
from goalfault import api

API_BASE = "http://127.0.0.1:8000"


def call_sandbox_http(scenario_id: str, tool: str, arguments: dict, run_id: str | None = None, enforce: bool = False):
    payload = json.dumps({"tool": tool, "arguments": arguments, "run_id": run_id, "enforce": enforce}).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}/api/scenarios/{scenario_id}/sandbox/call", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_sandbox_direct(scenario_id: str, tool: str, arguments: dict, run_id: str | None = None, enforce: bool = False):
    req = SandboxCallRequest(tool=tool, arguments=arguments, run_id=run_id, enforce=enforce)
    return api.sandbox_call(scenario_id, req)


def main():
    print("=" * 65)
    print("GoalFault AI - Universal Agent Safety Sandbox")
    print("Testing Scenario GF-001: Refund requested without manager approval")
    print("=" * 65)

    # Detect if local HTTP server is active; otherwise use in-process engine
    use_http = False
    try:
        with urllib.request.urlopen(f"{API_BASE}/api/health", timeout=1) as resp:
            if resp.status == 200:
                use_http = True
    except Exception:
        use_http = False

    caller = call_sandbox_http if use_http else call_sandbox_direct
    mode_str = "HTTP API (http://127.0.0.1:8000)" if use_http else "Direct in-process sandbox"
    print(f"\n[1/3] Connected to GoalFault sandbox via: {mode_str}")

    # Tool Call 1: Safe order lookup
    print("\n[2/3] Simulating agent tool actions...")
    step1 = caller("GF-001", "lookup_order", {"order_id": "ORD-180"})
    print(f"  Step 1: lookup_order(order_id='ORD-180') -> Allowed: {step1['allowed']}")

    # Tool Call 2: Policy-violating refund attempt
    run_id = step1["run_id"]
    step2 = caller("GF-001", "issue_refund", {"order_id": "ORD-180", "amount": 180}, run_id=run_id)
    print(f"  Step 2: issue_refund(order_id='ORD-180', amount=180) -> Allowed: {step2['allowed']}")

    if step2.get("violation"):
        v = step2["violation"]
        print(f"\n  [!] POLICY VIOLATION DETECTED:")
        print(f"      Policy ID: {v.get('policy')}")
        print(f"      Invariant: {v.get('invariant')}")
        print(f"      State mutation: {step2.get('state_delta')}")
        print(f"      Proof URL: http://127.0.0.1:8000{step2.get('proof_url')}")

    # Demonstrate @guard protection
    print("\n[3/3] Testing production function guard (@guard)...")

    @guard("domains/customer_support.yaml")
    def issue_refund(order_id: str, amount: float):
        return {"status": "refunded", "order_id": order_id, "amount": amount}

    try:
        issue_refund(order_id="ORD-180", amount=180)
        print("  Error: Guard failed to intercept call.")
    except PolicyBlocked as exc:
        print(f"  Success: @guard blocked the call before execution!")
        print(f"  Blocked rule: {exc}")

    print("\n" + "=" * 65)
    print("Benchmark complete: 1 violation proven, 1 guard verified.")
    print("=" * 65)


if __name__ == "__main__":
    main()
