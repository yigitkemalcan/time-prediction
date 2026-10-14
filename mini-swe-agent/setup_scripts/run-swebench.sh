#!/usr/bin/env bash
set -euo pipefail
usage() {
    cat <<'HELP'
Usage: bash run-swebench.sh [--instance ID ... | --all | --filter REGEX] [--slice START:STOP] [--workers N] [--shuffle]
                          [--perception]
Runs SWE-Bench Verified, test split, against this project's vLLM (start-vllm.sh).
Choose instances explicitly, or supply a slice. Default workers: one.
Examples:
  bash run-swebench.sh --instance '<INSTANCE_ID>'
  bash run-swebench.sh --slice 0:5 --workers 2
  bash run-swebench.sh --all --workers 1
Slices are zero-based and exclude STOP. They apply after filtering.
--shuffle uses seed 42 before filtering and slicing. Every invocation creates a fresh run directory.
--perception adds characterization/perception.yaml: the system prompt asks the model to start every response
with <predicted_output_tokens>N</predicted_output_tokens>. Without it the run is the unmodified baseline.
Both runs on the same instances: --shuffle --slice 0:50, once with and once without --perception.
Per-call vLLM timing (TTFT, mean ITL, queue time) is stored in each trajectory step at
messages[i].extra.response.metrics; client-side inference/tool times are in step_timings.
When the runner exits, RUN_DIRECTORY/task_metrics/{tasks.csv,steps.csv,analysis.json} are written.
ITP_PROJECT_ROOT overrides the project root; ITP_PORT overrides the vLLM port (default 8100).
HELP
}
filter=''
selection=''
instances=()
slice=''
workers=1
experiment=baseline
extra=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --instance)
            [[ -z "$selection" || "$selection" == --instance ]] || { echo 'Do not combine --instance with --all or --filter.' >&2; exit 1; }
            selection=--instance
            instances+=("${2:?--instance requires an instance ID}")
            shift 2 ;;
        --all|--filter)
            [[ -z "$selection" ]] || { echo 'Do not mix selectors.' >&2; exit 1; }
            selection="$1"
            if [[ "$1" == --all ]]; then filter=''; shift
            else filter="${2:?--filter requires a regex}"; shift 2; fi ;;
        --slice) slice="${2:?--slice requires START:STOP}"; shift 2 ;;
        --workers|-w) workers="${2:?--workers requires a positive integer}"; shift 2 ;;
        --shuffle) extra+=(--shuffle); shift ;;
        --perception) experiment=perception; shift ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done
[[ -n "$selection" || -n "$slice" ]] || { usage >&2; exit 1; }
[[ "$workers" =~ ^[1-9][0-9]*$ ]] || { echo 'Workers must be a positive integer.' >&2; exit 1; }
[[ -z "$slice" || "$slice" =~ ^[0-9]*:[0-9]*$ ]] || { echo 'Use a slice such as 0:5.' >&2; exit 1; }
if [[ "$selection" == --instance ]]; then
    for instance in "${instances[@]}"; do
        [[ "$instance" =~ ^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-[0-9]+$ ]] || { echo "Invalid instance ID: $instance" >&2; exit 1; }
    done
fi
project="${ITP_PROJECT_ROOT:-/mnt/raid0/jovans/yigit/time-prediction/inference-time-prediction}"
port="${ITP_PORT:-8100}"
agent_root="$project/mini-swe-agent"
export MSWEA_GLOBAL_CONFIG_DIR="$project/config/mini-swe-agent"
export HF_HOME="$project/cache/huggingface"
export XDG_CACHE_HOME="$project/cache/xdg"
export UV_CACHE_DIR="$project/cache/uv"
mkdir -p "$MSWEA_GLOBAL_CONFIG_DIR"
source "$agent_root/.venv/bin/activate"
cd "$agent_root"
if [[ "$selection" == --instance ]]; then
    filter=$("$agent_root/.venv/bin/python" -c 'import re,sys; print("^(?:"+"|".join(map(re.escape,sys.argv[1:]))+")$")' "${instances[@]}")
fi
curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:$port/v1/models" |
    "$agent_root/.venv/bin/python" -c 'import json,sys; assert any(m["id"]=="Qwen/Qwen3-235B-A22B-Instruct-2507" for m in json.load(sys.stdin)["data"]), "Expected Qwen model is not served"'
mkdir -p "$project/runs"
run_dir=$(mktemp -d "$project/runs/qwen-$experiment-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
cat > "$run_dir/local-qwen.yaml" <<YAML
model:
  model_name: hosted_vllm/Qwen/Qwen3-235B-A22B-Instruct-2507
  cost_tracking: ignore_errors
  model_kwargs:
    api_base: http://127.0.0.1:$port/v1
    num_retries: 0
YAML
configs=(-c "$agent_root/src/minisweagent/config/benchmarks/swebench.yaml")
if [[ "$experiment" == perception ]]; then configs+=(-c "$agent_root/characterization/perception.yaml"); fi
configs+=(-c "$run_dir/local-qwen.yaml")
command=("$agent_root/.venv/bin/mini-extra" swebench "${configs[@]}"
    -m hosted_vllm/Qwen/Qwen3-235B-A22B-Instruct-2507
    -o "$run_dir/results" --subset verified --split test
    --filter "$filter" --slice "$slice" --workers "$workers")
if [[ ${#extra[@]} -gt 0 ]]; then command+=("${extra[@]}"); fi
printf '%q ' "${command[@]}" > "$run_dir/agent-command.txt"
printf '\n' >> "$run_dir/agent-command.txt"
analyze() {
    status=$?
    trap - EXIT
    if ! "$agent_root/.venv/bin/python" "$agent_root/characterization/analyze_task_metrics.py" "$run_dir"; then
        echo "Task analysis failed; raw trajectories remain in $run_dir/results." >&2
    fi
    exit "$status"
}
trap analyze EXIT
echo "Run directory: $run_dir"
"${command[@]}"
echo "Runner finished. Inspect exit statuses in $run_dir/results."
