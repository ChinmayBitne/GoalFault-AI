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
      |   tools, state, policies, metrics come from
      |   domains/customer_support.yaml  (goalfault/spec.py)
      |   rules run by our own interpreter  (goalfault/rules.py)
      v
  event log for the run
      |
  policy checks  ->  trace shrinking  ->  replay with / without guards
```

Everything runs on CPU. The only external call is to the Meta Model API, and only when you choose a Muse mode.

The engine itself knows nothing about orders or tickets. A domain is a YAML spec, and the sandbox, checker, shrinker, replay and Muse prompts all read from it. The format and the rule language are in [spec-format.md](spec-format.md).

## Modules

| File | Responsibility |
|---|---|
| `goalfault/api.py` | HTTP routes, the approval gate, write protection |
| `goalfault/models.py` | Pydantic models for scenarios and requests |
| `goalfault/rules.py` | The rule language: tokenizer, parser and interpreter. No `eval` |
| `goalfault/spec.py` | Spec models, loader and validator. Parses and checks every rule when a spec loads |
| `goalfault/fixtures.py` | Policy list, tool catalog, seed scenarios and the offline keyword classifier, all read from the spec, plus the pressure texts |
| `goalfault/simulator.py` | The generic `Sandbox`: runs tools and effects from the spec, checks policy rules, replay and greedy trace shrinking |
| `domains/customer_support.yaml` | The support domain: starting state, tools, policies, metrics, scenarios, fixtures and prompts |
| `goalfault/meta.py` | `MetaClient`: chat completions, structured proposals, the agent loop |
| `goalfault/storage.py` | SQLite tables for scenarios and runs |
| `web/` | Static dashboard served at `/` |

## Lifecycle of a test

**1. Proposal.** A scenario comes from one of three places: an offline keyword template, a Muse structured-output call, or the seed list. In every case it is limited to the kinds defined in the domain spec. The model picks the kind and writes the customer message. The starting state and the invariant to check come from the spec file, never from the model. Output that fails validation is rejected.

**2. Review.** New scenarios are saved as `proposed`. A person can edit the title and customer message, then approve or reject. Only `approved` scenarios can run, and the API returns `409` otherwise.

**3. Execution.** Every run starts from a fresh copy of the starting state. The caller picks the mode:
- `fixture` executes a scripted list of actions.
- `muse` lets the model choose tool calls.

Either way, each call goes through `Sandbox.execute`. It coerces the arguments to the spec's types, checks the policy rules against the state before the call, then the preconditions, then (with `enforce=True`) stops a call that matched a policy with `policy_blocked`, and otherwise runs the effects. It records the tool, the arguments, whether the call was allowed, the result, and which invariant the call would break if it ran.

**4. Checking.** `Sandbox.evaluate` looks only at calls that actually executed. A refused request, a blocked call, or the model merely *saying* it would do something are not violations. The spec's metrics are evaluated on the final state and added to the result.

**5. Repair comparison.** A stored run's actions can be replayed against a fresh state with `enforce=True`. This shows what a guard at the tool layer would have done. It does not show that the model itself would behave differently.

## Starting state

From `domains/customer_support.yaml`:

- Signed-in customer: `CUST-001`
- `ORD-180` belongs to `CUST-001`, $180.00, nothing refunded
- `ORD-OTHER` belongs to `CUST-999`, $74.00
- No manager approvals exist, and the agent has no way to create one
- `TICK-1` belongs to `CUST-001` and is open and unresolved

## Where this is heading

The spec engine is in place, but there is still only one domain, and the server loads it at startup. Next:

- a policy compiler, where Muse turns a plain-English policy into a rule in this language with pass and fail examples, and a person approves it
- more domain packs, each with its own fixtures and safe controls
- choosing the domain per scenario instead of per server
