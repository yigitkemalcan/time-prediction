# Task list

`swebench_verified_50.txt` holds the 50 SWE-Bench Verified (test split) instances used by both the baseline and the
perception (PiA) runs, one instance ID per line, in the order they were run.

They are what `run-swebench.sh --shuffle --slice 0:50` selected: the dataset shuffled with seed 42, first 50.
Listing them explicitly keeps the set fixed even if the dataset or the shuffle changes.

`django__django-15957` is in the list but was left out of the 49-task analysis: in the baseline run it timed out
after about 4.7 h of client-side stalls near a 146k-token context.

Run the same instances, in the same order:

```bash
# run-swebench.sh: one --instance per task; --shuffle keeps the original order (shuffling happens before filtering)
bash mini-swe-agent/setup_scripts/run-swebench.sh --shuffle $(sed 's/^/--instance /' tasks/swebench_verified_50.txt)

# mini-extra directly: the same set as a --filter regex
mini-extra swebench --subset verified --split test --shuffle \
    --filter "^($(paste -sd'|' tasks/swebench_verified_50.txt))$" ...
```
