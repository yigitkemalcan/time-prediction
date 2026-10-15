# Claude Opus 5.5 vs Sonnet 5.5: predicting their own output length (SWE-bench, 50 tasks)

chi025, 2026-10-15. The setup is identical for both models: effort `high`, mini-swe-agent 2.4.6 (`swebench.yaml`),
one microVM per task, 4 tasks in parallel, and the same 50 tasks.

- **Prediction arm:** `perception.yaml` system prompt plus a one-line user reminder after every step's tool results.
- **Baseline arm:** no prediction prompt.
- **Results on chi025, under `~/time-prediction/runs/`:**
  - `comparison-opus55-high/` (summary.json, predicted_steps.csv, prediction_errors.png)
  - `comparison-sonnet55-high/`
  - run directories `claude-opus-5-5-{perception-reminder,baseline}-20261015T*`

## Prediction accuracy (steps with a prediction; target = all output tokens incl. hidden thinking)

| | Sonnet 5.5 | Opus 5.5 |
|---|---|---|
| Steps with a prediction | 210 / 286 (73 %) | 159 / 350 (45 %) |
| … first steps / later steps | 50/50, 160/236 | 50/50, 109/300 |
| Median predicted − actual | −18 tokens | **+502 tokens** |
| Median predicted ÷ actual | 0.88 | **3.39** |
| … first step / later steps | 2.5 / 0.63 | **13.0 / 2.4** |
| Within 2× | 48 % | 23 % |
| Median abs. % error | 58 % | 239 % |
| Spearman ρ (prediction vs actual) | 0.37 | 0.34 |
| Spearman ρ, previous-step baseline | 0.14 | 0.33 |
| Same length bucket | 66 % | 24 % |

- **Opus over-predicts heavily.** Its first-step predictions have a median of 2000 tokens, for responses of about
  130 tokens. Later steps have a median of 400 tokens, still 2.4× the actual length. It appears to estimate the
  remaining work, or a much longer reply than it writes.
- **Ranking survives:** ρ 0.34, about the same as Sonnet. A per-model scale correction would remove most of the
  bias, but the absolute numbers are not usable as they are.
- **Coverage drops on Opus.** Steps where Opus thinks come back with empty text and empty `thinking` blocks:
  Opus 5.5 returns text written between tool calls as hidden progress-update thinking. The tag is lost whenever
  that happens, which is part of why only 109 of 300 later steps carry one.

## Response time

| | Sonnet 5.5 | Opus 5.5 |
|---|---|---|
| e2e fit (all steps) | 1.14 s + 5.8 ms/token (R² 0.97) | 1.39 s + 8.1 ms/token (R² 0.90) |
| Time-prediction error, true tokens (upper bound) | 10 % | 14 % |
| … model's prediction | 26 % | **128 %** |
| … previous step's length | 36 % | 32 % |
| … running mean | 43 % | 46 % |

For Opus, the previous step's length predicts response time far better than the model's own prediction.

## Does asking for a prediction change the agent?

| | Sonnet pred. | Sonnet base | Opus pred. | Opus base |
|---|---|---|---|---|
| Resolved (47 gradeable offline) | 41 | 42 | 46 | 46 |
| Paired: both / only this arm | 39 / 2 | 39 / 3 | 46 / 0 | 46 / 0 |
| Steps per task (median, mean) | 5, 5.72 | 5, 5.58 | 7, 7.00 | 7, 8.52 |
| Output tokens per step (mean) | 331 | 293 | 336 | 378 |
| Thinking tokens per step (mean) | 101 | 81 | 101 | 140 |
| Response time per step (median, mean) | 2.20, 3.05 s | 1.95, 2.80 s | 2.84, 4.11 s | 2.79, 4.40 s |
| Task wall time (median) | 17 s | 17 s | 30 s | 32 s |
| Cost | $2.22 | $1.99 | $5.19 | $7.31 |

Opus resolves the same 46 tasks with and without the prompt. With the prompt it takes fewer steps (mean 7.0 vs 8.5)
and thinks less per step. So for Opus the prompt, if anything, shortens the run. One run per arm, so this may be
noise.

## Caveats

- One run per arm, a small number of steps (286–426), and short tasks.
- The Opus coverage loss is partly an API effect: hidden progress-update text. It could be recovered with
  `thinking.display: "updates"` (summaries only) or by asking for the prediction as a tool argument.
- The Qwen3-235B comparison is still pending: its run outputs are not on chi025.
