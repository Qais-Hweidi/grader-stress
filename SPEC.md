# Grader stress test: spec

## Goal

Show that the hidden tests in HUD's own sample tasks give reward 1.0 to wrong fixes, and provide verified tests that close those gaps. The output is one HTML report, in HUD's visual language, that the HUD eng team can read and re-check themselves.

## Scope

- Repo: `https://github.com/hud-evals/coding-template-sample`
- Tasks: the 4 in `coding-template/tasks.py`: `sentry-fix`, `notif-bug`, `settings-v2`, `webhook-bug`
- Each task has 3 branches: `{task_id}_baseline` (the bug), `{task_id}_test` (baseline plus the hidden tests), and `{task_id}_golden` (the reference fix).

## Behavior

One command, `uv run stress.py --tasks ../coding-template/tasks.py`, runs these steps for each task (tasks run in parallel):

1. **Validity.** Run the hidden tests on the baseline and expect them to fail (any non-zero exit, like HUD's `baseline_fail` check). Run them on golden and expect them to pass. If either check is wrong, mark the task invalid and stop working on it.
2. **Wrong fixes.** Ask the model for 8 plausible-but-wrong fixes (`--mutants`). If it writes more, keep the first 8.
   - The model sees the task description, the baseline source, and the golden diff.
   - It never sees the hidden tests.
   - Each wrong fix has a title, why an agent would write it, and a concrete input where it differs from golden.
   - Each fix is expressed as exact find/replace edits against baseline files.
   - Rules for the model: no hardcoded test data, no sabotage, no syntax errors.
3. **Grade.** Apply each wrong fix to the baseline, then grade it the way `AgentPatchGrader` does: `git apply` the baseline→test diff, then run `pytest {test_files}` from the repo root. Each fix gets exactly one label:
   - **survived**: pytest exits 0, so the grader would give it reward 1.0.
   - **caught**: pytest exits 1.
   - **broken**: any other exit code, or a timeout (120s).
   - **didn't apply**: the fix has no edits, an edit changes nothing or points outside the repo, a find block doesn't match exactly once, or the hidden tests don't apply on top of it.
   Only survived and caught fixes count toward the totals.
4. **Killer tests.** For each survivor, ask the model for one standalone pytest module.
   - The model sees the description, the golden diff, the wrong-fix diff, and the hidden tests.
   - The module counts as **verified** only if it passes on golden with the hidden tests applied, and fails with exit 1 on the wrong fix.
   - Give the model up to 3 attempts. After each failed attempt, feed back the pytest output.
   - If no attempt is verified, label the fix Unclear and note that no test separates it from golden, so it may be equivalent.
   - The model labels each killer test **required**, **implied** or **ambiguous**, depending on how firmly the description backs it, and quotes the sentence it relies on.

If a task or a single survivor hits an error (an API failure, a git error), the error is recorded in the report and the rest of the run continues.

All checkouts are plain `git archive` exports with no `.git` directory, created in a temp dir that's deleted afterwards.

## Outputs

A run writes to `out/` by default, or to the folder given with `--out`. Each run first clears that folder's `mutants/` and `killer_tests/`. The shipped results are in `out/hud-samples/` (all 4 tasks) and `out/sentry-fix/` (the same run, filtered to the sentry-fix task).

`report.html` is a single self-contained file. It opens straight from disk with no network, and is styled after hud.ai:
- `#fafafa` canvas, thin grid lines with `+` corner markers, a bold serif display face, and Helvetica-style sans for UI text;
- pastel gradient panels, small white product-style cards, and a dark closing band.

It uses plain words throughout: "correct fix" (golden), "HUD's tests" (hidden tests), "new test" (killer test). Each wrong fix gets one of these labels:
- **Caught:** HUD's tests gave it 0.
- **Hole:** HUD's tests passed it, and a verified new test pins behavior the task requires or implies.
- **Unclear:** HUD's tests passed it, but the task doesn't settle the behavior, or no verified new test was found. It's left to the task author.
- **Broken fix** or **Didn't apply.**

It contains:
- **Hero:** a "Proof of concept" tag, the headline "Catch grader holes before the first AI run", a short paragraph on the problem and how the tool works, a "See it on a sample task" button, and the short run command.
- **How it works:** 4 steps: check the task, write wrong fixes, grade them, close the hole.
- **What it found:** a review panel styled like HUD's task review, with every wrong fix and its label. The task list only appears when there's more than one task.
  - Each task gets one badge: the number of holes, Unclear, No holes, Not tested (validity check only), Broken task, or Error.
  - No fix is expanded when the page opens.
  - A caught fix shows its diff, plus which of HUD's tests failed and the error.
  - A hole or unclear fix shows:
    - why it's tempting, and what it gets wrong;
    - how firmly the task backs the new test, with a quote;
    - tabs for the new test, the wrong fix and the correct fix;
    - a "what happened" log.
- **Where it fits:** this tool runs before any AI run; HUD's QA agents run after.
- **Footer:** the run command (with a copy button), the repo, task(s), model, wrong fixes tried, and the author and date.

The other files:
- `report.json`: the raw results that the HTML embeds.
- `mutants/<task>/<id>.diff`: each fix that passed HUD's tests, as a `git apply`-able patch against the baseline.
- `killer_tests/<task>/test_gst_<id>.py`: each verified new test.

## Constraints

- **Model:** `anthropic/claude-sonnet-5.5`, called through OpenRouter (BYOK). Spend is estimated as tokens × OpenRouter list price × 1.05, and reported.
- **Key handling:** the OpenRouter key comes only from `OPENROUTER_API_KEY`. It never gets written to disk, the report or the logs, and it's removed from the environment that task-repo and model-written code runs in.
- **Packaging:** `stress.py`, with PEP 723 inline deps (`openai`, `pytest`) and no dependency on `hud`, plus `report_template.html`. Tasks are read from `tasks.py` by AST, not by importing it. Tests run with the tool's own Python (`pytest` only), so task repos can't need other packages.
- **Flags:**
  - `--tasks` is the tasks file to read (required unless `--render`).
  - `--repo` sets the task repo (default: `hud-evals/coding-template-sample`).
  - `--only` limits the run to the listed task slugs.
  - `--model`, `--mutants` and `--attempts` set the model, the wrong fixes per task and the tries per killer test.
  - `--out` sets the output folder (default: `out/`).
  - `--validate-only` runs step 1 with no model calls and no key.
  - `--render` rebuilds `report.html` from `report.json` without rerunning anything.

## Acceptance criteria

1. `--validate-only` reports all 4 tasks as valid.
2. A full run finishes in under 10 minutes. The estimated spend roughly matches the change in `byok_usage_daily` on the OpenRouter key.
3. Every wrong fix in the report has exactly one label. Each task's caught, hole and unclear counts match its rows, and "Wrong fixes tried" matches `report.json`.
4. Every verified killer test can be re-checked by hand from the outputs:
   - Golden plus the hidden tests plus the killer test: passes.
   - Baseline plus `mutants/<task>/<id>.diff` plus the hidden tests plus the killer test: fails.
   I'll do this re-check for at least one survivor per task that has survivors.
5. Every survivor shows its diff, its spec label and its quoted basis.
6. Searching `out/` and the run logs for the key turns up nothing.
7. Both reports open from disk with no network requests and no console errors. Every number in them matches `report.json`. I check them visually in a browser at desktop width.
