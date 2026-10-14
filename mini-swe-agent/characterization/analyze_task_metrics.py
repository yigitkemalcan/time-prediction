#!/usr/bin/env python3
"""Summarize step timings: python analyze_task_metrics.py RUN_DIR.

Writes task_metrics/{tasks.csv,steps.csv,analysis.json}.
inference_s wraps model.query() (request, response, parsing); tool_s sums env.execute() calls.
Both are client-side wall-clock times. ttft_ms, mean_itl_ms (TBT), queue_ms and generation_ms
are vLLM's server-side per-request metrics (--enable-per-request-metrics); TTFT starts at scheduling,
so it excludes queue_ms. The k-th model response in the trajectory belongs to step k.
predicted_output_tokens is N from the first <predicted_output_tokens>N</predicted_output_tokens> in the
response text (perception runs); prediction_in_advance is true when the response starts with that tag.
Compare it with completion_tokens, which also counts the tag's own tokens.
other_s = task_duration_s - environment_setup_s - inference_total_s - tool_total_s (agent loop overhead).
Missing measurements remain null, never zero.
"""
import json
import re
from pathlib import Path

import pandas as pd
import typer

STEP_COLUMNS = [
    "task_id", "step", "inference_s", "tool_s", "action_count", "inference_outcome", "tool_outcomes",
    "prompt_tokens", "completion_tokens", "predicted_output_tokens", "prediction_in_advance", "finish_reason",
    "ttft_ms", "mean_itl_ms", "queue_ms", "generation_ms",
    "start_mono_ns", "end_mono_ns",
]
PREDICTION = re.compile(r"<predicted_output_tokens>\s*(\d+)\s*</predicted_output_tokens>")


def llm_fields(response: dict | None) -> dict:
    response = response if isinstance(response, dict) else {}
    usage, metrics = response.get("usage") or {}, response.get("metrics") or {}
    choice = (response.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""
    prediction = PREDICTION.search(content)
    return {
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        "predicted_output_tokens": int(prediction.group(1)) if prediction else None,
        "prediction_in_advance": prediction is not None and prediction.start() == len(content) - len(content.lstrip()),
        "finish_reason": choice.get("finish_reason"),
        "ttft_ms": metrics.get("time_to_first_token_ms"), "mean_itl_ms": metrics.get("mean_itl_ms"),
        "queue_ms": metrics.get("queue_time_ms"), "generation_ms": metrics.get("generation_time_ms"),
    }


def step_rows(trajectory: dict, task_id: str) -> list[dict]:
    responses = [m["extra"]["response"] for m in trajectory.get("messages", []) if "response" in m.get("extra", {})]
    return [
        {
            "task_id": task_id, "step": timing["step"],
            "inference_s": timing["inference"]["elapsed_s"],
            "tool_s": sum(tool["elapsed_s"] for tool in timing["tools"]),
            "action_count": len(timing["tools"]),
            "inference_outcome": timing["inference"]["outcome"],
            "tool_outcomes": ";".join(tool["outcome"] for tool in timing["tools"]),
            **llm_fields(responses[i] if i < len(responses) else None),
            "start_mono_ns": timing["inference"]["start_mono_ns"],
            "end_mono_ns": (timing["tools"] or [timing["inference"]])[-1]["end_mono_ns"],
        }
        for i, timing in enumerate(trajectory.get("step_timings", []))
    ]


def task_record(trajectory: dict, task_id: str, task_steps: list[dict]) -> dict:
    info = trajectory["info"]
    count = info["model_stats"]["api_calls"]
    record = {
        "task_id": task_id, "exit_status": info.get("exit_status"), "steps": count,
        "timed_steps": len(task_steps), "timing_complete": len(task_steps) == count,
        "task_duration_s": None, "environment_setup_s": None,
        "inference_total_s": sum(s["inference_s"] for s in task_steps) if task_steps else None,
        "tool_total_s": sum(s["tool_s"] for s in task_steps) if task_steps else None,
        "other_s": None,
        "completion_tokens_total": sum(s["completion_tokens"] or 0 for s in task_steps) if task_steps else None,
        "predicted_steps": sum(s["predicted_output_tokens"] is not None for s in task_steps),
    }
    if window := info.get("task_timing"):
        start, ready, end = window["start_mono_ns"], window.get("environment_ready_mono_ns"), window["end_mono_ns"]
        record["task_duration_s"] = (end - start) / 1e9
        if ready is not None:
            record["environment_setup_s"] = (ready - start) / 1e9
            if task_steps:
                record["other_s"] = (end - ready) / 1e9 - record["inference_total_s"] - record["tool_total_s"]
    return record


def main(run_dir: Path):
    """Analyze a run's trajectories in RUN_DIR/results/*/*.traj.json."""
    tasks, steps = [], []
    for path in sorted((run_dir / "results").glob("*/*.traj.json")):
        trajectory = json.loads(path.read_text())
        task_id = trajectory.get("instance_id", path.parent.name)
        task_steps = step_rows(trajectory, task_id)
        tasks.append(task_record(trajectory, task_id, task_steps))
        steps.extend(task_steps)
    if not tasks:
        raise typer.BadParameter("No task trajectories found in results/*/*.traj.json")
    output = run_dir / "task_metrics"
    output.mkdir(exist_ok=True)
    pd.DataFrame(tasks).to_csv(output / "tasks.csv", index=False)
    pd.DataFrame(steps, columns=STEP_COLUMNS).to_csv(output / "steps.csv", index=False)
    (output / "analysis.json").write_text(json.dumps({"definitions": __doc__, "tasks": tasks, "steps": steps}, indent=2) + "\n")
    typer.echo(f"Wrote {len(tasks)} tasks and {len(steps)} timed steps to {output}")


if __name__ == "__main__":
    typer.run(main)
