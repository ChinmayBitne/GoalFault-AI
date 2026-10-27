# Architecture

```text
  browser (web/)
      |   propose / review / run / replay
      v
  FastAPI (goalfault/api.py) ---------- SQLite (scenarios, runs)
      |                 \
      |                  Meta Model API, muse-spark-1.3
      |                  (structured proposals, tool calls)
      v                       |
  Sandbox (goalfault/simulator.py) <--+   tool requests
      |  lookup_order | issue_refund | close_ticket
      v
  event log for the run
      |
  policy checks  ->  trace shrinking  ->  replay with / without guards
```

Everything runs on CPU. The only external call is to the Meta Model API, and only when you choose a Muse mode.

## Modules

| File | Responsibility |
|---|---|
| `goalfault/api.py` | HTTP routes, the approval gate, write protection |
| `goalfault/models.py` | Pydantic models for scenarios and requests |
| `goalfault/fixtures.py` | Policies, tool catalog, starting state, seed scenarios, scripted fixture actions, offline keyword classifier |
| `goalfault/simulator.py` | The `Sandbox` class, policy evaluation, replay and greedy trace shrinking |
| `goalfault/meta.py` | `MetaClient`: chat completions, structured proposals, the agent loop |
| `goalfault/storage.py` | SQLite tables for scenarios and runs |
| `web/` | Static dashboard served at `/` |

## Lifecycle of a test

**1. Proposal.** A scenario comes from one of three places: an offline keyword template, a Muse structured-output call, or the seed list. In every case it is limited to the three known kinds. The model picks the kind and writes the customer message. The starting state and the invariant to check come from trusted code, never from the model. Output that fails validation is rejected.

**2. Review.** New scenarios are saved as `proposed`. A person can edit the title and customer message, then approve or reject. Only `approved` scenarios can run, and the API returns `409` otherwise.

**3. Execution.** Every run starts from a fresh copy of the starting state. The caller picks the mode:
- `fixture` executes a scripted list of actions.
- `muse` lets the model choose tool calls.

Either way, each call goes through `Sandbox.execute`, which records the tool, the arguments, whether it was allowed, and the result.

**4. Checking.** `Sandbox.evaluate` looks only at calls that actually executed. A refused request, a blocked call, or the model merely *saying* it would do something are not violations.

**5. Repair comparison.** A stored run's actions can be replayed against a fresh state with `enforce=True`. This shows what a guard at the tool layer would have done. It does not show that the model itself would behave differently.

## Starting state

- Signed-in customer: `CUST-001`
- `ORD-180` belongs to `CUST-001`, $180.00, nothing refunded
- `ORD-OTHER` belongs to `CUST-999`, $74.00
- No manager approvals exist, and the agent has no way to create one
- `TICK-1` belongs to `CUST-001` and is open and unresolved

## Where this is heading

The three scenario kinds are hard-coded today. The plan is a validated scenario spec covering actors, resources, tool signatures, preconditions, starting state, customer messages and invariants. It would be interpreted by a small allowlisted rule engine, so a new domain can be added without new Python, and model output is never executed as code.
