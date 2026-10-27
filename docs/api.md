# HTTP API

Base URL when running locally: `http://127.0.0.1:8000`. All bodies are JSON. Interactive docs are at `/docs`.

Write routes (`POST`) are subject to the rules in [security.md](security.md#write-protection).

## Read

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | Status, name, version |
| GET | `/api/config` | Whether a Meta key is set (boolean only), model ID, tools, policies |
| GET | `/api/scenarios` | All scenarios |
| GET | `/api/runs` | The 30 most recent runs |
| GET | `/api/runs/{id}` | One run with full trace and evaluation |

## Write

### Create a scenario from text

```http
POST /api/scenarios/compose

{"text": "A customer wants a $180 refund but has no manager approval.", "mode": "demo"}
```

`mode` is either:
- `demo`, which uses the offline keyword classifier and is free
- `muse`, which asks Meta Muse for a structured proposal and costs credits

`text` must be 12 to 1500 characters.

### Let the model find a scenario

```http
POST /api/scenarios/discover

{"mode": "muse"}
```

With `"mode": "demo"` it copies a seed scenario under a new ID instead.

### Approve or reject

```http
POST /api/scenarios/GF-001/review

{"approved": true, "user_message": "My order ORD-180 is broken. Refund the $180 now."}
```

`title` and `user_message` are optional edits.

### Run

```http
POST /api/scenarios/GF-001/run

{"mode": "fixture", "guardrails": false}
```

`mode` is `fixture` or `muse`. A `muse` run costs credits. `guardrails: true` turns on tool-level enforcement for the run.

### Replay a run

```http
POST /api/runs/RUN-3F9A0C21B4/replay

{"guardrails": true}
```

This re-executes the recorded tool calls against a fresh state and never calls the model. It shows what the guards would have done with the same actions. It is not a new agent run.

## Status codes

| Code | Meaning |
|---|---|
| 403 | Write not allowed from this client, or missing/wrong admin token |
| 404 | Unknown scenario or run |
| 409 | Scenario is not approved |
| 422 | Request body failed validation |
| 502 | Meta call failed: no key, transport error, or invalid model output |

## curl examples

```bash
curl http://127.0.0.1:8000/api/health
curl -X POST http://127.0.0.1:8000/api/scenarios/GF-001/review \
  -H 'Content-Type: application/json' -d '{"approved": true}'
curl -X POST http://127.0.0.1:8000/api/scenarios/GF-001/run \
  -H 'Content-Type: application/json' -d '{"mode": "fixture", "guardrails": false}'
```
