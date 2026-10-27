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
| Model asks for a dangerous real-world action | Only three in-memory fake tools exist | Any future tool adapter needs its own review |
| Model output gets executed | Output is validated against JSON schema and Pydantic, never `eval`'d | A richer scenario spec will need a strict interpreter |
| Prompt injection via scenario text | Scenario text is treated as data. Policies, state and invariants come from code | No multi-turn indirect injection tests yet |
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

- Tools only change a fresh in-memory dictionary for that run.
- All IDs, customers, amounts and tickets are made up.
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
