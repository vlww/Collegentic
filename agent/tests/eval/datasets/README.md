# Evaluation Datasets

This directory contains evaluation datasets for testing agent behavior.

## Collegentic's Eval Suite (Milestone 15)

`collegentic-scenarios.json` encodes .agents-cli-spec.md's 10 Success
Criteria test scenarios, collapsed into 3 real orchestrator prompts graded
against 5 behavioral dimensions in one custom metric — see
`../eval_config.yaml`'s header comment and
`../collegentic_behavior_quality.py`'s docstring for the full scenario ->
dimension mapping.

Two of the three cases can't go through the normal `eval generate` path:
Collegentic's real research pipeline routinely goes quiet longer than
`eval generate`'s hardcoded 120s inter-event read timeout during a single
`google_search`-heavy LLM call (no CLI flag overrides this). All three
cases are instead captured directly via `InMemoryRunner` — the exact same
`root_agent`, just bypassing the HTTP layer entirely — so the whole suite
reproduces from two commands:

```bash
# 1. Run all 3 cases through the real orchestrator directly (a few
#    minutes — real live web research for 2 of the 3, same as running the
#    app for real) and write a grade-ready trace file.
uv run python tests/eval/capture_traces.py

# 2. Grade it.
agents-cli eval grade --traces tests/eval/datasets/collegentic-live-traces.json --config tests/eval/eval_config.yaml
```

`collegentic-live-traces.json` is `capture_traces.py`'s own output,
committed so the suite's actual tested behavior is reviewable without
re-running live research. `collegentic-scenarios.json` is the equivalent
prompt-only dataset in the standard `eval generate` inference-input shape
(kept for reference / for re-running the fast clarification-only case
through the normal CLI path if ever needed) — it's not what grading
actually runs against.

## Running Evaluations

### Default Dataset
```bash
# Generate traces using the default dataset
agents-cli eval generate
agents-cli eval grade
```

### Custom Dataset
```bash
# Generate traces for a custom dataset
agents-cli eval generate --dataset tests/eval/datasets/custom-dataset.json --output custom_traces/
agents-cli eval grade --metrics general_quality --traces custom_traces/
```

### Deployed Agent

By default, `eval generate` starts a local HTTP server to run your agent in, dispatches each case in parallel and then tears the server down. Pass `--url <base_url> --app-name <name>` to target an already-running or deployed agent instead.

```bash
agents-cli eval generate --url https://my-agent.run.app --app-name app
```

## Dataset Format

Each dataset file follows the Gemini Enterprise Agent Platform Evaluation
dataset format. An eval case may use **either** of two shapes — both are
valid input to `agents-cli eval generate`:

**Shape A — single-prompt case:**

```json
{
  "eval_cases": [
    {
      "eval_case_id": "unique_case_id",
      "prompt": {
        "role": "user",
        "parts": [{"text": "User message"}]
      }
    }
  ]
}
```

**Shape B — continued-conversation case (the "N+1" pattern):**
The case carries prior turns in `agent_data` and the last turn ends with a
user message; `eval generate` appends the next agent response.

```json
{
  "eval_cases": [
    {
      "eval_case_id": "unique_case_id",
      "agent_data": {
        "turns": [
          {
            "turn_index": 0,
            "events": [
              {"author": "user",  "content": {"role": "user",  "parts": [{"text": "First user message"}]}},
              {"author": "agent", "content": {"role": "model", "parts": [{"text": "First agent reply"}]}},
              {"author": "user",  "content": {"role": "user",  "parts": [{"text": "Follow-up user message"}]}}
            ]
          }
        ]
      }
    }
  ]
}
```

## Key Fields

- `eval_cases`: Array of evaluation cases.
- `eval_case_id`: Unique identifier for the evaluation case (optional).
- `prompt`: A single user message — Shape A.
- `agent_data.turns`: Prior conversation turns ending with a user message — Shape B.

## Creating Custom Datasets

You can create custom datasets in two ways:

1. **By Hand**: Copy `basic-dataset.json` as a template and manually add evaluation cases.
2. **Synthesize**: Use the synthetic dataset generation command to generate conversation scenarios:
   ```bash
   agents-cli eval dataset synthesize --count 10
   ```

## Discovering Metrics

You can discover available out-of-the-box evaluation metrics by running:

```bash
agents-cli eval metric list
```

## Beyond Generate and Grade

Once you have a baseline, the eval surface has a few more commands worth knowing about:

- `agents-cli eval compare BASE CAND` — diff two grade-results files (regression check).
- `agents-cli eval analyze RESULTS` — cluster failure modes from a grade-results file.
- `agents-cli eval optimize` — auto-tune your agent's prompts using eval data.

See the [Evaluation Guide](https://google.github.io/agents-cli/guide/evaluation/) for the full surface and metric reference.
