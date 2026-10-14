import json

import pandas as pd
import pytest
import typer
from typer.testing import CliRunner

from characterization.analyze_task_metrics import main
from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel, make_output


def with_response(output: dict, completion_tokens: int, ttft_ms: float, content: str | None = None) -> dict:
    output["extra"]["response"] = {
        "choices": [{"finish_reason": "tool_calls", "message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": completion_tokens},
        "metrics": {"time_to_first_token_ms": ttft_ms, "mean_itl_ms": 20.0, "queue_time_ms": 1.0},
    }
    return output


def run_analysis(run_dir):
    app = typer.Typer()
    app.command()(main)
    result = CliRunner().invoke(app, [str(run_dir)])
    assert result.exit_code == 0, result.output


def test_steps_join_vllm_metrics_and_task_totals(tmp_path):
    trajectory = tmp_path / "results/t1/t1.traj.json"
    agent = DefaultAgent(
        DeterministicModel(outputs=[
            with_response(make_output("", [{"command": "sleep 0.02"}, {"command": "echo hi"}]), 7, 50.0,
                          "\n<predicted_output_tokens> 40 </predicted_output_tokens>\nTHOUGHT: run it"),
            with_response(make_output("", [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]), 3, 60.0,
                          "Done. <predicted_output_tokens>9</predicted_output_tokens>"),
        ]),
        LocalEnvironment(), system_template="", instance_template="{{task}}", cost_limit=0, output_path=trajectory,
    )
    assert agent.run("test")["exit_status"] == "Submitted"
    start = agent.step_timings[0]["inference"]["start_mono_ns"]
    agent.save(trajectory, {"instance_id": "t1", "info": {"task_timing": {
        "start_mono_ns": start - 2_000_000_000, "environment_ready_mono_ns": start - 1_000_000_000,
        "end_mono_ns": agent.step_timings[-1]["tools"][-1]["end_mono_ns"],
    }}})
    run_analysis(tmp_path)
    steps = pd.read_csv(tmp_path / "task_metrics/steps.csv")
    assert steps.step.tolist() == [1, 2]
    assert steps.action_count.tolist() == [2, 1]
    assert steps.ttft_ms.tolist() == [50.0, 60.0]
    assert steps.completion_tokens.tolist() == [7, 3]
    assert steps.tool_s[0] >= 0.02
    assert steps.tool_outcomes.tolist() == ["returned;returned", "Submitted"]
    assert steps.predicted_output_tokens.tolist() == [40, 9]
    assert steps.prediction_in_advance.tolist() == [True, False]
    task = pd.read_csv(tmp_path / "task_metrics/tasks.csv").iloc[0]
    assert task.steps == task.timed_steps == 2
    assert task.environment_setup_s == pytest.approx(1.0)
    assert task.task_duration_s == pytest.approx(2.0 + (steps.end_mono_ns.iloc[-1] - start) / 1e9)
    assert task.inference_total_s + task.tool_total_s + task.other_s == pytest.approx(task.task_duration_s - 1.0)
    assert task.completion_tokens_total == 10
    assert task.predicted_steps == 2


def test_missing_timings_and_responses_stay_null(tmp_path):
    folder = tmp_path / "results/old"
    folder.mkdir(parents=True)
    (folder / "old.traj.json").write_text(json.dumps({
        "instance_id": "old", "info": {"model_stats": {"api_calls": 1}},
        "step_timings": [{"step": 1, "inference": {"elapsed_s": 1.0, "outcome": "ValueError",
                                                    "start_mono_ns": 0, "end_mono_ns": 1}, "tools": []}],
    }))
    run_analysis(tmp_path)
    step = pd.read_csv(tmp_path / "task_metrics/steps.csv").iloc[0]
    assert pd.isna(step.ttft_ms) and step.tool_s == 0 and step.inference_outcome == "ValueError"
    assert pd.isna(step.predicted_output_tokens) and not step.prediction_in_advance
    task = pd.read_csv(tmp_path / "task_metrics/tasks.csv").iloc[0]
    assert pd.isna(task.task_duration_s) and pd.isna(task.other_s) and bool(task.timing_complete)
