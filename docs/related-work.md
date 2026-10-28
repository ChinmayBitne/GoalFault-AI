# Related work

None of the underlying ideas are new: reward hacking, red-teaming agents, and checking state invariants. GoalFault's contribution is putting them together into one workflow:

1. Scenarios are derived from what the tools allow and what the policies forbid, rather than from generic jailbreak prompts.
2. A person approves every scenario before it runs.
3. Pass or fail is decided by checking executed state changes, not by asking a model.
4. The metric the agent is judged on is measured separately from the real outcome.
5. Failing traces are shrunk and can be replayed with tool-level guards.

Today the project has basic versions of 2, 3 and 5 across four domains and fourteen seed scenarios. Item 1 is wired up through Muse but hasn't been validated against the live API yet. Item 4 currently amounts to comparing closed tickets with resolved tickets.

## Background

- **Specification gaming and Goodhart's law.** Optimizing a measurable proxy can drift away from the intended goal. See Krakovna et al., *Specification gaming: the flip side of AI ingenuity* (DeepMind, 2020), and the broader reward hacking literature.
- **τ-bench** ([sierra-research/tau-bench](https://github.com/sierra-research/tau-bench)). Benchmarks tool-using agents that follow domain policies in retail and airline settings, by comparing final database state. It's the closest relative. GoalFault differs in two ways: it targets proxy-objective pressure and human-approved, generated stress cases, and it adds trace shrinking and guarded replay rather than task-success scoring.
- **AgentDojo** ([ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo)). An environment for prompt-injection attacks and defences on tool-using agents.
- **promptfoo red teaming** ([docs](https://www.promptfoo.dev/docs/red-team/)). A practical tool for generating adversarial test cases against LLM apps.
- **Property-based testing and test-case reduction**, as in QuickCheck and Hypothesis. This is the source of the idea of shrinking a failing input to a smaller one that still fails.

## Claims I avoid

- That this approach is globally unique.
- That passing GoalFault tests means an agent is safe.
- That a guarded replay means the model has been fixed. It only shows the tool layer would have blocked those actions.
