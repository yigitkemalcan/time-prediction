# Claude Sonnet 5.5 predicting its own output length (SWE-bench, 50 tasks)

chi025, 2026-10-14. Both runs used Claude Sonnet 5.5 at effort `high`, mini-swe-agent 2.4.6 (`swebench.yaml`, step limit
250), one Cloud Hypervisor microVM per task, 4 tasks in parallel, and the 50 tasks in `tasks/swebench_verified_50.txt`.

| Run | Directory (`~/time-prediction/runs/`) |
|---|---|
| Prediction | `claude-sonnet-5-5-perception-reminder-20261014T213945Z-C9j199` |
| Baseline (no prediction prompt) | `claude-sonnet-5-5-baseline-20261014T214631Z-7qrBNU` |
| Comparison | `comparison-sonnet55-high/` (`summary.json`, `predicted_steps.csv`) |

Each run directory holds `task_metrics/steps.csv`, with one row per agent step: prediction, completion / thinking /
visible / cache tokens, response time, TTFT and decode time. It also holds `api_calls.jsonl` (the raw per-call log)
and `results/eval/` (grading).

## Prompt: what it took to get predictions

- **System prompt only** (`perception.yaml`, the same as the Qwen run): Sonnet wrote `<predicted_output_tokens>`
  only on the first response of each task. After that it went straight to tool calls.
- **Reminder appended to each tool result:** still ignored. Current Claude models treat instructions inside tool
  output as data.
- **One-line reminder as user text after the tool results** ("Begin your next response with
  `<predicted_output_tokens>N</predicted_output_tokens>`."), added by the relay to the whole history so caching
  stays valid: this is the setting used here.
- **Coverage:** 210 of 286 steps (73 %) carry a prediction. That is all 50 first steps and 160 of 236 later steps
  (68 %). Every prediction is at the very start of the response.

## Prediction accuracy (210 steps with a prediction)

Target: `completion_tokens`, everything generated, including hidden thinking. 36 % of steps had some thinking.

| Predictor | Median abs. % error | Median pred / actual | Within 2× | Spearman ρ | Same length bucket* |
|---|---|---|---|---|---|
| **Model's own prediction** | **58 %** | 0.88 | 48 % | **0.37** | **66 %** |
| Previous step's length | 59 % | 1.24 | 54 % | 0.14 | 53 % |
| Running mean of the task | 80 % | 1.49 | 44 % | 0.01 | 41 % |

\*Buckets: < 256, 256–1k, 1k–4k, ≥ 4k tokens. The two naive predictors are scored on the 160 later steps they exist for.

- The model's prediction is the only one that ranks steps meaningfully (ρ 0.37 against 0.14 and 0.01). Its typical
  error is still large: a median of 100 tokens on a median step of ~160 tokens.
- It slightly underestimates (median ratio 0.88), and errors are similar whether or not the step had thinking
  (ρ 0.23 without thinking, 0.39 with it).
- Against visible tokens only (thinking excluded) it does no better: ρ 0.32, median error 59 %.

## Response time

- Per-step response time is almost linear in output tokens: **e2e ≈ 1.14 s + 5.8 ms × tokens** (R² 0.97, about
  173 tokens/s). The fixed part is mostly time to first token: a median of 1.6 s, with prompt caching on.
- Predicting each step's response time from that line:

| Token count used | Median abs. % error | Median abs. error |
|---|---|---|
| Actual tokens (upper bound) | 10 % | 0.20 s |
| **Model's prediction** | **26 %** | **0.61 s** |
| Previous step | 36 % | 0.89 s |
| Running mean | 43 % | 1.04 s |

- The per-step `decode_tps` column is not reliable: streamed chunks arrive in bursts. Use the fitted slope instead.

## Does asking for a prediction change the agent?

| | Prediction run | Baseline |
|---|---|---|
| Resolved (47 gradeable offline†) | 41 / 50 | 42 / 50 |
| Paired: both / only this run | 39 / 2 | 39 / 3 |
| Steps per task (median, mean) | 5, 5.72 | 5, 5.58 |
| Output tokens per step (mean) | 331 | 293 |
| Thinking tokens per step (mean) | 101 | 81 |
| Response time per step (median, mean) | 2.20 s, 3.05 s | 1.95 s, 2.80 s |
| TTFT (median) | 1.60 s | 1.36 s |
| Cost | $2.22 | $1.99 |

†matplotlib-25332, sphinx-7985 and django-13809 cannot pass offline even with the gold patch (their tests need
network), so they count as unresolved in both runs.

There is no measurable quality change: 41 vs 42 resolved, with 2 and 3 tasks flipping. Steps per task are the same.
The prompt costs about 13 % more output tokens per step and about 9 % more response time per step; the extra time is
mostly a 0.24 s higher TTFT.

## Caveats

- The Qwen3-235B comparison is not done yet. Its run outputs are not on chi025: the repo's README refers to
  `/mnt/raid0/jovans/yigit/...` on another host.
- Sonnet solves these tasks in very few steps (median 5 steps, ~17 s per task), so there are only 286 steps.
  The confidence intervals on the numbers above are wide.
- The per-step reminder makes this prompt differ from the Qwen run, which had the system prompt alone.
- One run per arm, default sampling, effort `high`.
