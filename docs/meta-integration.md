# Meta Muse integration

GoalFault uses **Meta Muse Spark 1.3** (`muse-spark-1.3`) through the Meta Model API.

| Setting | Value |
|---|---|
| Base URL | `https://api.meta.ai/v1` (override with `META_API_BASE`) |
| Endpoint | `POST /chat/completions` |
| Auth | `Authorization: Bearer $MODEL_API_KEY` |
| Structured output | `response_format: {"type": "json_schema", "json_schema": {...}}` |
| Tool calling | `tools: [{"type": "function", "function": {...}}]`, model replies with `tool_calls` |

Meta's docs:
- [Chat completions](https://dev.meta.ai/docs/cookbook/quickstart-chat-completions)
- [Structured output](https://dev.meta.ai/docs/cookbook/structured-output)
- [Tool calling](https://dev.meta.ai/docs/cookbook/tool-function-calling)

## Where the model is used

### 1. Writing test scenarios

`MetaClient.propose()` sends the policy list, the tool catalog and the user's description. It asks for one test case in the schema from [scenarios.md](scenarios.md). The system prompt tells the model that the user text is scenario material, not instructions.

The response is parsed and validated twice: once by the JSON schema, then by Pydantic. Anything invalid is rejected and nothing is saved. A valid proposal is stored as `proposed` and still needs human approval.

`MetaClient.discover()` uses the same path. Instead of a user description, it asks the model to find a risky interaction on its own.

### 2. Playing the support agent

`MetaClient.run_agent()` gives the model a support-agent system prompt, the customer message from the approved scenario, and three function definitions. The prompt and the function definitions (names, descriptions and argument schemas) come from the domain spec, see [spec-format.md](spec-format.md). The loop works like this:

1. Send the conversation to the model.
2. If it returns `tool_calls`, run each one through `Sandbox.execute`. Append the results as `tool` messages and go back to step 1.
3. If it returns plain text, stop. That text is the agent's final reply.

Each tool call is executed only inside the sandbox. If the model never calls a tool, or refuses, the trace is empty and the run passes. That is a real result and is reported as one.

Every agent run records a `stop_reason`:

| `stop_reason` | Meaning |
|---|---|
| `final_answer` | The model replied with text and no tool calls |
| `tool_budget` | The model asked for more calls than the limits allow. None of that turn's calls ran |
| `turn_limit` | Six turns passed without a final answer |
| `error` | A later turn failed after some tool calls had already run. The run is kept so the executed calls stay visible, and `error` holds the message |

### Objective pressure

A scenario can carry an `objective` (what the agent is told it is scored on, such as "You are scored on tickets closed per hour") and a `pressure_level` from 0 to 3. Both are set during review.

At level 0 nothing is added to the prompt. At levels 1 to 3 the objective goes at the end of the system prompt, followed by one of four fixed pressure statements defined in `goalfault/fixtures.py` (`PRESSURE_TEXTS`). If no objective is given, the spec's `default_objective` is used. For support, that's closed tickets and satisfaction ratings. The policy text in the prompt is the same at every level. Pressure never tells the agent to break a rule. It only gives the agent a reason to want to.

Every run record (fixture, Muse and replay) stores the `objective` and `pressure_level` it ran with. Only Muse runs actually see the prompt; for fixtures and replays the fields are just labels.

## Limits in place today

- `max_completion_tokens` comes from `META_MAX_OUTPUT_TOKENS` (default 2000) and is capped at 2500 in code
- At most 6 model turns per run
- At most 5 tool calls in a single turn and 8 per run. A turn that would go over either limit is not executed and the run ends with `tool_budget`. Calls with bad arguments count toward the limit
- 60 second HTTP timeout per attempt
- Up to 3 attempts per model call (see below)
- A cumulative spend cap across all calls (see below)
- The key is read on the server only and is never sent to the browser

## Retries

`MetaClient.completion()` makes up to 3 attempts per call.

- **Retried:** HTTP 429, any 5xx, and network errors (timeouts, refused connections and similar `httpx.RequestError`s).
- **Not retried:** other 4xx responses such as 400 or 401, since repeating them won't help.
- **Wait time:** if the response has a `Retry-After` header (seconds or an HTTP date), that is used. Otherwise it waits 1s, then 2s. Every wait is capped at 20 seconds.
- Failed attempts return no usage, so they aren't logged or charged. The number of attempts is stored with each logged call.

The sleep function is injectable (`MetaClient(sleep=...)`), so tests run without real waits.

## Spend cap and usage log

Every successful Meta call is written to the `meta_usage` table in the SQLite database. This covers proposals, discovery and every turn of an agent run. Each row holds the time, the purpose (`propose`, `discover` or `agent`), the scenario and run ID when known, the model, prompt, completion, reasoning and total tokens, the estimated cost, and the number of attempts. For proposals, the scenario ID is filled in once the proposal has been saved.

Before every call, the client adds up the logged cost. If it has reached `GOALFAULT_SPEND_CAP_USD` (default `5.00`), the call is refused before anything is sent. The API answers with **HTTP 402**. I picked 402 over 429 because nothing is being rate limited. The local budget is used up, and the fix is to raise the cap. A 429 would also be confused with Meta's own rate limit.

The cap is checked before each turn of an agent run, not just at the start. A run that hits the cap after it has already executed tool calls stops with `stop_reason: "error"` and is saved. If it hits the cap before any tool call, the request gets a 402 and no run is saved.

`GET /api/usage` returns the total spend, cap, remaining budget, call count, token totals, the rates in use and the 20 most recent calls. The dashboard sidebar shows spend against the cap.

## Errors

| Situation | Behaviour |
|---|---|
| No key | `MetaError`, returned to the client as HTTP 502 with a clear message. Nothing is sent |
| Spend cap reached | HTTP 402. Nothing is sent |
| 429 or 5xx from Meta | Retried. If all 3 attempts fail, HTTP 502 with the status code and attempt count only, no headers or body |
| Other 4xx from Meta | HTTP 502 with the status code only, not retried |
| Network failure | Retried. Then HTTP 502 naming the exception type |
| Non-JSON reply | HTTP 502 naming the exception type |
| No `choices` in the reply | HTTP 502. The call's tokens are still logged if the reply had usage |
| A choice with no `message` | HTTP 502 on the first turn. On a later turn the run ends with `stop_reason: "error"` |
| Proposal fails validation | HTTP 502, nothing saved, cost still logged |
| Unknown tool requested | Recorded as `unrecognized_tool`, state unchanged |
| Tool call without an `id` | A stable ID `call_<turn>_<n>` is made up, used in the reply message and recorded on the trace event with `call_id_synthesized: true` |
| Tool arguments that aren't valid JSON, or JSON that isn't an object | The tool is **not** run. The trace event gets `arg_error` and `raw_arguments`, the model receives `{"error": "invalid_arguments"}`, and replay and trace shrinking skip the event |
| Missing or empty tool arguments | Treated as `{}`, so the tool rejects the call itself |

Apart from the cases above, errors don't create a run record and nothing is reported as a success.

## Cost tracking

Every Muse run stores `prompt_tokens`, `completion_tokens`, `reasoning_tokens` and `total_tokens` summed across turns. It also stores an estimated cost:

```
cost = prompt_tokens * input_rate / 1e6 + completion_tokens * output_rate / 1e6   (USD)
```

The rates come from `META_PRICE_INPUT_PER_M` (default `1.25`) and `META_PRICE_OUTPUT_PER_M` (default `4.25`). Those were Meta's published Standard prices for Muse Spark 1.3 when this was written. Reasoning tokens are reported inside `completion_tokens_details` and are already part of `completion_tokens`, so they are shown but not charged twice. Check [dev.meta.ai](https://dev.meta.ai/) for current pricing. Your billing page is the real source of truth.

## Known gaps

- The spend check and the call aren't atomic, so two runs started at the same moment can both pass the check and go a little over the cap
- The cap counts only what this database has logged. Calls made from another machine or another database don't count
- Retry waits block the request thread for up to about 40 seconds in the worst case
- Rates are estimates. If Meta changes prices, the env vars need updating by hand
- Objective pressure is a single system-prompt sentence. There is no multi-turn pressure from the customer yet
