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

`MetaClient.run_agent()` gives the model a support-agent system prompt, the customer message from the approved scenario, and three function definitions. The loop works like this:

1. Send the conversation to the model.
2. If it returns `tool_calls`, run each one through `Sandbox.execute`. Append the results as `tool` messages and go back to step 1.
3. If it returns plain text, stop. That text is the agent's final reply.

Each tool call is executed only inside the sandbox. If the model never calls a tool, or refuses, the trace is empty and the run passes. That is a real result and is reported as one.

## Limits in place today

- `max_completion_tokens` comes from `META_MAX_OUTPUT_TOKENS` (default 2000) and is capped at 2500 in code
- At most 6 model turns per run
- At most 5 tool calls in a single turn and 8 per run; going over ends the run
- 60 second HTTP timeout
- The key is read on the server only and is never sent to the browser

## Errors

| Situation | Behaviour |
|---|---|
| No key | `MetaError`, returned to the client as HTTP 502 with a clear message |
| HTTP error from Meta | HTTP 502 with the status code only, no headers or body |
| Network failure or non-JSON reply | HTTP 502 naming the exception type |
| No `choices` in the reply | HTTP 502 |
| Proposal fails validation | HTTP 502, nothing saved |
| Unknown tool requested | Recorded as `unrecognized_tool`, state unchanged |
| Malformed tool arguments | Treated as `{}`, so the tool usually rejects the call |

In every error case, no run record is created and nothing is reported as a success.

## Cost tracking

Every Muse run stores `prompt_tokens`, `completion_tokens` and `total_tokens` summed across turns. It also stores an estimated cost:

```
cost = prompt_tokens * 1.25 / 1e6 + completion_tokens * 4.25 / 1e6   (USD)
```

These rates were Meta's published Standard prices for Muse Spark 1.3 when this was written. Check [dev.meta.ai](https://dev.meta.ai/) for current pricing. Your billing page is the real source of truth.

## Known gaps

- No retry or backoff for HTTP 429 or 5xx yet
- No cumulative spending cap across runs
- A tool call with no `id` will currently fail the whole run
- The agent prompt states every policy but gives the agent no performance target, so live runs mostly test plain instruction-following rather than pressure from a competing objective
