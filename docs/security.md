# Security

GoalFault is a research prototype for a single user. It is not a hardened multi-user service. This page covers what it protects, how, and what is still missing.

## What needs protecting

- The Meta API key and the credits behind it
- The integrity of stored scenarios and run traces
- The human approval step
- The line between simulated tool calls and anything real

## Threats and mitigations

| Threat | What's in place | Still missing |
|---|---|---|
| Model asks for a dangerous real-world action | Only the in-memory fake tools declared in `domains/` exist, and they can only change the run's own state | Any future tool adapter needs its own review |
| Model output gets executed | Output is validated against JSON schema and Pydantic, never `eval`'d. Domain specs are read with `yaml.safe_load`, and rules are parsed and interpreted by our own code, with a fixed list of five functions and length and depth limits. Rules from the policy compiler go through the same parser and spec validation, are tested against examples and safe controls, and only apply after a person approves them | A person can still approve a rule that is valid but too loose. The examples make that less likely, not impossible |
| Prompt injection via the policy text | The compile prompt tells the model the policy text is data. Whatever comes back is only ever a candidate rule that has to pass the checks above | No adversarial tests of the compile prompt yet |
| Prompt injection via scenario text | Scenario text is treated as data. Policies, state and invariants come from the domain spec in `domains/`, never from the model | No multi-turn indirect injection tests yet |
| Running without consent | `proposed` scenarios cannot run (HTTP 409) | Per-approval run limits |
| Runaway spending | Turn, tool-call and output-token caps per run. At most 3 attempts per call. Every call logged, and a cumulative spend cap refuses new calls with HTTP 402 | Concurrency limit. The cap check isn't atomic across simultaneous runs |
| Key leak | Key read from server env, `.env` is git-ignored, errors don't echo headers | Use a secret manager when hosted |
| Unauthorized writes | Writes are loopback-only unless an admin token is set | A single shared token is not real auth |
| Lost results after deploy | None | SQLite is ephemeral on Cloud Run, so a hosted demo needs a durable store |

## Write protection

All `POST` routes go through `require_write`:

- **No `GOALFAULT_ADMIN_TOKEN` set:** writes are only accepted from `127.0.0.1`, `::1` or the test client. They are always refused on Cloud Run, which is detected through `K_SERVICE`. Forwarded headers are ignored.
- **Token set:** every write needs the header `X-GoalFault-Token: <token>`.

Don't turn on public writes for convenience. A public demo should have real authentication, per-visitor quotas and a spending cap first.

## Sandbox rules

- Tools only change a fresh in-memory dictionary for that run, and only through the four effect types a spec allows (set, increment, append, remove).
- All IDs, customers, employees, shoppers, amounts, tickets and one-time codes are made up.
- No files, shell, SQL, network, browser, payments or email from any tool.
- Unknown tools return `unrecognized_tool` and change nothing.
- Missing or mistyped arguments are rejected by the tool. Arguments that aren't a valid JSON object are never passed to a tool at all. They are recorded with `arg_error` instead.
- A violation is only counted if the forbidden call actually executed.

## Before making anything public

- [ ] Key absent from the repo, logs, screenshots and video
- [ ] Key and admin token stored in a secret manager for hosting
- [ ] Authentication and per-visitor limits on write endpoints
- [ ] Durable storage for runs and approvals
- [ ] Error messages checked for leaked headers
- [ ] A test asserting no real endpoints are contacted
- [ ] Timeouts, tool-call and spend limits reviewed
- [ ] No real personal or customer data anywhere
- [ ] Event terms re-read

## Reporting a problem

Please report security issues privately to the maintainer rather than in a public issue.
