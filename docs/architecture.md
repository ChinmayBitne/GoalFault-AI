# Architecture

```text
  browser (web/)
      |   propose / review / run / replay
      v
  FastAPI (goalfault/api.py) ---------- SQLite (scenarios, runs, compiled policies)
      |                 \
      |                  Meta Model API, muse-spark-1.3
      |                  (structured proposals, compiled policies, tool calls)
      v                       |
  Sandbox (goalfault/simulator.py) <--+   tool requests
      |   tools, state, policies, metrics come from
      |   domains/*.yaml plus approved compiled policies  (goalfault/spec.py)
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
| `goalfault/spec.py` | Spec models, loader and validator. Parses and checks every rule when a spec loads. Also the registry of every file in `domains/` |
| `goalfault/quality.py` | The quality bar a domain must pass before the dashboard lists it |
| `goalfault/compiler.py` | Policy compiler: checks a draft rule and its examples, and builds the prompt and schema for Muse |
| `goalfault/fixtures.py` | Policy list, tool catalog, seed scenarios and the offline keyword classifier, all read from the spec, plus the pressure texts |
| `goalfault/simulator.py` | The generic `Sandbox`: runs tools and effects from the spec, checks policy rules, replay and greedy trace shrinking |
| `domains/*.yaml` | One file per domain: starting state, tools, policies, metrics, scenarios, fixtures, safe controls and prompts |
| `goalfault/meta.py` | `MetaClient`: chat completions, structured proposals, policy compiling, the agent loop |
| `goalfault/storage.py` | SQLite tables for scenarios, runs, compiled policies and Meta usage |
| `web/` | Static dashboard served at `/` |

## Domains

Every YAML file in `domains/` is loaded when the server first needs one. A file that doesn't validate stops the server instead of being skipped quietly. Each scenario belongs to one domain, and runs, replays, proposals and the Muse prompts all use that scenario's domain. Several domains can be used side by side on one server.

`/api/domains` only lists domains that pass the quality bar in `goalfault/quality.py`:

- at least 4 tools and 3 policies
- at least 3 scenarios whose fixture breaks its own policy, shrinks to a non-empty trace and is blocked when replayed with guards, with every policy covered and at least one fixture that actually gets shorter
- at least 2 safe controls: legitimate workflows that run every step with no policy flagged, guards on or off

Whether the data is realistic and clearly synthetic is something a person still has to check.

## Compiled policies

The domain a run sees is the spec file plus every approved compiled policy for that domain, oldest first (`effective_spec` in `api.py`). The extra policies go through the same validation as a freshly loaded file, so a compiled rule can't do anything a hand-written one couldn't. If a spec file later changes so that an approved rule no longer validates, runs in that domain return `409` until the rule is rejected.

A draft is checked by `check_draft` in `compiler.py`:

1. The rule is added to the spec and validated. Errors are reported with their position.
2. Each `should_pass` and `should_fail` example is replayed from the starting state. The earlier steps are setup and must run. The last step must call the rule's tool, be accepted by the tool itself, and be matched (or not) by the rule as the example claims. At least two of each are required.
3. The domain's safe controls are replayed. If the rule flags any step, the draft can't be approved.
4. The seed fixtures are replayed, and any the rule also flags are listed. This is for information only.

Drafts are checked alongside the other approved rules for the domain, so a clash shows up before approval. Editing an approved rule takes it out of use until it is approved again.

## Lifecycle of a test

**1. Proposal.** A scenario comes from one of three places: an offline keyword template, a Muse structured-output call, or the seed list. In every case it is limited to the kinds defined in the domain spec. The model picks the kind and writes the customer message. The starting state and the invariant to check come from the spec file, never from the model. Output that fails validation is rejected.

**2. Review.** New scenarios are saved as `proposed`. A person can edit the title and customer message, then approve or reject. Only `approved` scenarios can run, and the API returns `409` otherwise.

**3. Execution.** Every run starts from a fresh copy of the starting state. The caller picks the mode:
- `fixture` executes a scripted list of actions.
- `muse` lets the model choose tool calls.

Either way, each call goes through `Sandbox.execute`. It coerces the arguments to the spec's types, checks the policy rules against the state before the call, then the preconditions, then (with `enforce=True`) stops a call that matched a policy with `policy_blocked`, and otherwise runs the effects. It records the tool, the arguments, whether the call was allowed, the result, and every policy the call matched (`matched_policies`). `violation_if_executed` still holds the first one, for older readers.

**4. Checking.** `Sandbox.evaluate` looks only at calls that actually executed. A refused request, a blocked call, or the model merely *saying* it would do something are not violations. The spec's metrics are evaluated on the final state and added to the result.

**5. Repair comparison.** A stored run's actions can be replayed against a fresh state with `enforce=True`. This shows what a guard at the tool layer would have done. It does not show that the model itself would behave differently.

## Starting state

From `domains/customer_support.yaml`:

- Signed-in customer: `CUST-001`
- `ORD-180` belongs to `CUST-001`, $180.00, nothing refunded
- `ORD-OTHER` belongs to `CUST-999`, $74.00
- No manager approvals exist, and the agent has no way to create one
- `TICK-1` belongs to `CUST-001` and is open and unresolved, with no notes

The other domains are described in [scenarios.md](scenarios.md#other-domains).

## Where this is heading

- more domain packs: clinic scheduling and banking operations
- pressure sweeps across levels for one scenario
- proposing a guard for a confirmed failure and checking it against the safe controls
