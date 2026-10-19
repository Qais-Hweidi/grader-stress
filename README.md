# grader-stress

Catch grader holes before the first AI run.

> **Proof of concept.** This is a quick experiment. It's only been run on HUD's 4 sample tasks, so expect rough edges.

In a HUD coding task, the hidden tests are the grader. If an agent's patch passes them, it gets reward 1.0. This tool checks whether those tests pass **only** correct fixes. It has an LLM write plausible-but-wrong fixes, grades each one the way `AgentPatchGrader` does, and writes a new test for every wrong fix that gets through. A new test only counts once pytest proves it passes on the correct fix and fails on the wrong one.

## What it found on HUD's sample tasks

These are the 4 tasks in [`hud-evals/coding-template`](https://github.com/hud-evals/coding-template), run against [`hud-evals/coding-template-sample`](https://github.com/hud-evals/coding-template-sample):

| Task          | Wrong fixes | Caught by HUD's tests | Passed with 1.0 | Holes | Unclear |
|---------------|------------:|----------------------:|----------------:|------:|--------:|
| `sentry-fix`  | 8           | 6                     | 2               | 1     | 1       |
| `notif-bug`   | 8           | 1                     | 7               | 2     | 5       |
| `settings-v2` | 9           | 3                     | 6               | 5     | 1       |
| `webhook-bug` | 8           | 4                     | 4               | 3     | 1       |
| **Total**     | **33**      | **14**                | **19**          | **11**| **8**   |

Every wrong fix that passed has a verified new test.
- **Hole:** the task description requires or implies the behavior the new test checks.
- **Unclear:** the description doesn't settle it, so it's the task author's call.

The full run took about 2 minutes and cost an estimated $0.62 (Claude Sonnet 5.5 via OpenRouter).

## Reports

The reports are single HTML files with no network requests. GitHub shows HTML as source code, so clone the repo (or download the raw file) and open it in a browser:

- [`out/sentry-fix/report.html`](out/sentry-fix/report.html): the same run filtered to one task, the quickest read
- [`out/hud-samples/report.html`](out/hud-samples/report.html): all 4 tasks

Each output folder also has:
- `report.json`: the raw results
- `mutants/<task>/<id>.diff`: each wrong fix that passed, as a patch against the baseline
- `killer_tests/<task>/test_gst_<id>.py`: each verified new test

## How it works

For each task (`{id}_baseline`, `{id}_test` and `{id}_golden` branches):

1. **Check the task.** The hidden tests must fail on baseline and pass on golden.
2. **Write wrong fixes.** The model sees the description, the baseline source and the golden diff, but never the hidden tests.
3. **Grade them.** Apply each fix to baseline, apply the baseline→test diff, then run `pytest {test_files}` from the repo root.
4. **Close the hole.** For each fix that passed, the model writes a standalone pytest module. It gets up to 3 tries, with pytest output fed back after each failure.

See [SPEC.md](SPEC.md) for the full behavior and acceptance criteria.

## Run it

You need:
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and git. uv sets up Python 3.11+ and the two dependencies declared inline in `stress.py` (`openai`, `pytest`).
- An [OpenRouter API key](https://openrouter.ai/keys) with credit, for full runs only. This is the only key. No HUD account or key is needed, because the tool reads `tasks.py` as plain text and clones the task repo with git.

```bash
git clone https://github.com/Qais-Hweidi/grader-stress
git clone https://github.com/hud-evals/coding-template   # for its tasks.py
cd grader-stress

# validity check only: no model calls, no key needed
uv run stress.py --tasks ../coding-template/tasks.py --validate-only

# full run on all 4 tasks: about 2 minutes and ~$0.62
export OPENROUTER_API_KEY=sk-or-...
uv run stress.py --tasks ../coding-template/tasks.py
```

Results go to `out/report.html`. Other options:
- `--only sentry-fix,notif-bug`: run just these tasks
- `--out out/my-run`: write somewhere else
- `--mutants 8`: wrong fixes per task
- `--attempts 3`: tries per new test
- `--model anthropic/claude-sonnet-5.5`: any OpenRouter model ID
- `--repo URL`: another repo with the same three-branch layout
- `--render --out out/hud-samples`: rebuild that folder's `report.html` from its `report.json` without rerunning anything

Limits worth knowing:
- Tests run with the tool's own Python, which only has `pytest`. So for now the task repo's tests can't need other packages. HUD's sample repo doesn't.
- The task repo's code and the model-written fixes and tests run on your machine, with no sandbox. Use a container or VM for repos you don't trust. Your OpenRouter key is removed from the environment that code runs in.

## Re-check a result by hand

For example, `sentry-fix` wrong fix `m5` ("Catch KeyError and TypeError broadly"). Start in the `grader-stress` folder:

```bash
OUT=$PWD/out/hud-samples
git clone https://github.com/hud-evals/coding-template-sample /tmp/sample && cd /tmp/sample

# correct fix + HUD's tests + new test: passes
git checkout origin/sentry_fix_golden
git diff origin/sentry_fix_baseline origin/sentry_fix_test | git apply
cp $OUT/killer_tests/sentry-fix/test_gst_m5.py .
uvx pytest test_user_service.py test_gst_m5.py

# wrong fix + HUD's tests: also passes, so reward 1.0
git reset --hard && git clean -fd
git checkout origin/sentry_fix_baseline
git apply $OUT/mutants/sentry-fix/m5.diff
git diff origin/sentry_fix_baseline origin/sentry_fix_test | git apply
uvx pytest test_user_service.py

# wrong fix + new test: fails
cp $OUT/killer_tests/sentry-fix/test_gst_m5.py .
uvx pytest test_gst_m5.py
```
