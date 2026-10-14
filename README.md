# Inference-time prediction (separate project)

Goal: predict GPU-side LLM inference time for agent steps, starting with asking the model
to guess its own number of output tokens ("perception in advance").

Shares no code, venv, cache or port with the CPU-memory projects in `/mnt/raid0/jovans/yigit/agent-characterization/` (moved out of there on 2026-10-12).
The only shared things are the read-only Qwen weights, the Docker daemon and the SWE-Bench images.

```text
inference-time-prediction/
├── mini-swe-agent/            upstream clone (SWE-agent/mini-swe-agent @ 04d809ce, v2.4.6+3)
│   ├── .venv/                 agent venv: mini-swe-agent 2.4.6, litellm 1.104.1
│   └── setup_scripts/
│       ├── start-vllm.sh      run in tmux; serves on 127.0.0.1:8100
│       └── run-swebench.sh    SWE-Bench Verified runner -> ../runs/
├── envs/vllm/                 vLLM 0.31.0+cu129, torch 2.13.0+cu129, transformers 5.17.0
├── cache/                     uv, python 3.12.14, huggingface, vllm, triton, flashinfer caches
├── config/                    mini-swe-agent global config, vLLM config root
└── runs/                      one directory per run-swebench.sh invocation
```

## vLLM notes

- The PyPI default for vLLM 0.31.0 is built for CUDA 13.0, which needs driver >= 580. This host has driver 560.35 (CUDA 12.6),
  so the `+cu129` wheel is installed instead (it relies on CUDA minor-version compatibility):
  ```bash
  UV_CACHE_DIR=cache/uv UV_PYTHON_INSTALL_DIR=cache/python UV_PYTHON_PREFERENCE=only-managed \
    uv pip install --python envs/vllm/bin/python 'vllm==0.31.0' --torch-backend=cu129 \
    --extra-index-url https://wheels.vllm.ai/0.31.0/cu129 --index-strategy unsafe-best-match
  ```
- The server runs with `--enable-per-request-metrics`. Every chat completion then carries
  `metrics: {time_to_first_token_ms, mean_itl_ms, queue_time_ms, generation_time_ms, tokens_per_second}`.
  TTFT is measured from scheduling, not from queueing. litellm keeps this field, so mini-swe-agent stores it in
  every trajectory step at `messages[i].extra.response.metrics`.
- Prefix caching is on by default in vLLM V1, so the TTFT of later agent steps reflects cache hits.

## Usage

```bash
# Terminal 1 (tmux). The GPUs must be free: stop the old server on port 8000 first.
bash mini-swe-agent/setup_scripts/start-vllm.sh
# Terminal 2
bash mini-swe-agent/setup_scripts/run-swebench.sh --instance django__django-11099
```

## Experiments (same 50 instances each)

```bash
bash mini-swe-agent/setup_scripts/run-swebench.sh --shuffle --slice 0:50                # runs/qwen-baseline-*
bash mini-swe-agent/setup_scripts/run-swebench.sh --shuffle --slice 0:50 --perception   # runs/qwen-perception-*
```

`--perception` layers `mini-swe-agent/characterization/perception.yaml` on top of `swebench.yaml`. It changes only
`agent.system_template`, which asks the model to start each response with `<predicted_output_tokens>N</predicted_output_tokens>`.
The prediction is not enforced: a response without it runs normally and its prediction is logged as null.
`task_metrics/steps.csv` holds `predicted_output_tokens` and `prediction_in_advance`, next to vLLM's `completion_tokens`.
