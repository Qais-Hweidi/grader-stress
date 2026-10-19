# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "pytest>=8"]
# ///
"""Grader stress test for HUD coding-template tasks.

A task is three branches: ``{id}_baseline`` (bug), ``{id}_test`` (+ hidden
tests), ``{id}_golden`` (reference fix). The hidden tests are the grader: an
agent's patch scores 1.0 if they pass. This checks whether they pass *only*
correct patches:

  1. validity  hidden tests fail on baseline, pass on golden
  2. mutants   an LLM writes plausible-but-wrong fixes (sees the golden fix,
               never the hidden tests)
  3. grade     each wrong fix runs against the hidden tests, like
               AgentPatchGrader does; a pass means the grader would score it 1.0
  4. killers   for each survivor, an LLM writes a test that should pass on golden
               and fail on the wrong fix; both are checked by running pytest

    OPENROUTER_API_KEY=... uv run stress.py --tasks ../coding-template/tasks.py
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_REPO = "https://github.com/hud-evals/coding-template-sample"
KILLER_NAME = "test_gst_killer.py"
MAX_CONTEXT_BYTES = 120_000


# ----------------------------------------------------------------------------
# Tasks
# ----------------------------------------------------------------------------

@dataclass
class Task:
    slug: str
    task_id: str
    description: str
    test_files: list[str]


def parse_tasks(path: Path) -> list[Task]:
    """Read ``coding_bug(...)`` calls from a coding-template tasks file (no import, no hud dep)."""
    tree = ast.parse(path.read_text())
    calls: dict[str, dict] = {}
    slugs: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if isinstance(value, ast.Call) and getattr(value.func, "id", getattr(value.func, "attr", "")) == "coding_bug":
            kw = {k.arg: ast.literal_eval(k.value) for k in value.keywords
                  if k.arg in ("task_id", "description", "test_files")}
            calls[target.id] = kw
        elif isinstance(target, ast.Attribute) and target.attr == "slug":
            slugs[target.value.id] = ast.literal_eval(value)
    return [Task(slug=slugs.get(var, kw["task_id"]), **kw) for var, kw in calls.items()]


# ----------------------------------------------------------------------------
# Git / pytest plumbing
# ----------------------------------------------------------------------------

def git(*args: str, cwd: Path, input: str | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, input=input, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


# Plain a/ b/ patches whatever the user's git config says (noprefix, external diff tools, color).
DIFF_FLAGS = ("--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/")


class Repo:
    def __init__(self, url: str, workdir: Path):
        self.path = workdir / "clone"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout", url, str(self.path)], check=True)

    def diff(self, a: str, b: str) -> str:
        return git("diff", *DIFF_FLAGS, f"origin/{a}", f"origin/{b}", cwd=self.path)

    def changed(self, a: str, b: str) -> list[str]:
        return git("diff", "--name-only", f"origin/{a}", f"origin/{b}", cwd=self.path).split()

    def files(self, ref: str) -> list[str]:
        return git("ls-tree", "-r", "--name-only", f"origin/{ref}", cwd=self.path).split()

    def show(self, ref: str, path: str) -> str:
        return git("show", f"origin/{ref}:{path}", cwd=self.path)

    def checkout(self, ref: str, dest: Path) -> Path:
        """Export ``ref`` into ``dest`` as a plain directory (no .git, so nothing to peek at)."""
        dest.mkdir(parents=True)
        tar = subprocess.run(["git", "archive", f"origin/{ref}"], cwd=self.path,
                             capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)
        return dest


def apply_patch(dest: Path, patch: str) -> None:
    git("apply", "--verbose", cwd=dest, input=patch)


def run_pytest(cwd: Path, files: list[str], timeout: int = 120) -> tuple[str, str]:
    """Return ("pass" | "fail" | "error", output tail). "error" = couldn't collect/run."""
    # Repo and model-written code runs here, so it doesn't get the key.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("OPENROUTER_API_KEY", None)
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files],
                           cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return "error", f"timed out after {timeout}s"
    status = {0: "pass", 1: "fail"}.get(r.returncode, "error")
    return status, "\n".join((r.stdout + r.stderr).strip().splitlines()[-25:])


# ----------------------------------------------------------------------------
# LLM (OpenRouter, OpenAI-compatible)
# ----------------------------------------------------------------------------

class LLM:
    def __init__(self, model: str):
        from openai import OpenAI
        import urllib.request

        self.model, self.spent = model, 0.0
        self.calls = 0
        self._lock = threading.Lock()
        self.client = OpenAI(base_url="https://openrouter.ai/api/v1",
                             api_key=os.environ["OPENROUTER_API_KEY"], timeout=300, max_retries=2)
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as r:
            models = {m["id"]: m for m in json.load(r)["data"]}
        if model not in models:
            raise SystemExit(f"unknown OpenRouter model: {model}")
        p = models[model]["pricing"]
        self.price_in, self.price_out = float(p["prompt"]), float(p["completion"])

    def __call__(self, system: str, user: str, max_tokens: int = 16_000) -> str:
        r = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        u = r.usage
        # Token-priced estimate + 5% for OpenRouter's BYOK fee.
        cost = 1.05 * (u.prompt_tokens * self.price_in + u.completion_tokens * self.price_out)
        with self._lock:
            self.spent += cost
            self.calls += 1
        return r.choices[0].message.content or ""


def tag(text: str, name: str) -> str | None:
    m = re.search(rf"<{name}>\n?(.*?)\n?</{name}>", text, re.S)
    return m.group(1) if m else None


# ----------------------------------------------------------------------------
# Prompts
# ----------------------------------------------------------------------------

MUTANT_SYSTEM = """You audit the hidden-test graders of coding tasks used to evaluate and train AI agents.

Given a bug-fix task, the repository, and the reference fix, write plausible WRONG fixes: patches a capable but hurried engineer or AI agent could realistically submit after reading only the task description. Each wrong fix must:
- address the reported symptom in a believable way,
- behave differently from the reference fix on at least one realistic input that the task description covers or clearly implies,
- be one coherent fix, not sabotage: no hardcoded test data, no special-cased names, no unrelated breakage, no syntax errors.

Prefer the mistakes real agents make: partial fixes, fixing at the wrong layer, handling one case of several, wrong defaults, unsafe lookups left in place, shared mutable state, over-broad or over-narrow conditions. Make them diverse; don't repeat one idea with cosmetic changes."""

MUTANT_FORMAT = """Reply with exactly {n} blocks in this format and nothing else:

<mutant>
<title>a few words naming the mistake</title>
<plausible>one sentence: why an agent would write this</plausible>
<difference>one sentence: a concrete input where it differs from the reference fix, and how</difference>
<edit path="relative/path.py">
<find>
exact, contiguous lines copied from the BASELINE file (unique in that file)
</find>
<replace>
the replacement lines
</replace>
</edit>
</mutant>

A mutant may contain several <edit> blocks. Edits apply to the baseline (buggy) code, not to the reference fix."""

KILLER_SYSTEM = """You write regression tests that pin down a bug fix.

You get a task description, the reference fix, a WRONG fix that still passes the task's hidden tests, and the hidden test file. Write ONE small, standalone pytest module that passes on the reference fix and fails on the wrong fix.

Rules:
- Test behavior the task description requires or clearly implies. Don't pin incidental details of the reference implementation.
- The module is saved as {killer} at the repo root, next to the hidden tests. Copy whatever setup you need from them; don't import the hidden test module.
- Deterministic and fast: no network, no sleeps, no randomness.
- Assert on behavior (return values, state, raised errors), never on source text.

Then judge how firmly the task description backs the behavior you assert:
- required: the description states it.
- implied: a reasonable reader would expect it from the description.
- ambiguous: the description doesn't settle it; a human should decide.

Reply in exactly this format:
<spec>required|implied|ambiguous</spec>
<basis>the description sentence(s) you rely on, quoted, or what's missing</basis>
<test>
the full python module
</test>"""


# ----------------------------------------------------------------------------
# Stress test
# ----------------------------------------------------------------------------

@dataclass
class Mutant:
    id: str
    title: str
    plausible: str
    difference: str
    edits: list[tuple[str, str, str]]
    diff: str = ""
    hidden: str = ""          # pass (survived) | fail (caught) | error (broken) | invalid (edit didn't apply)
    hidden_tail: str = ""
    killer: dict = field(default_factory=dict)


def parse_mutants(text: str) -> list[Mutant]:
    out = []
    for i, block in enumerate(re.findall(r"<mutant>(.*?)</mutant>", text, re.S), 1):
        edits = [(path, tag(body, "find") or "", tag(body, "replace") or "")
                 for path, body in re.findall(r'<edit path="([^"]+)">(.*?)</edit>', block, re.S)]
        out.append(Mutant(id=f"m{i}", title=(tag(block, "title") or "").strip(),
                          plausible=(tag(block, "plausible") or "").strip(),
                          difference=(tag(block, "difference") or "").strip(), edits=edits))
    return out


def apply_edits(root: Path, edits: list[tuple[str, str, str]]) -> str | None:
    """Apply find/replace edits in place. Returns an error message, or None on success."""
    if not edits:
        return "no edits"
    root = root.resolve()
    for path, find, replace in edits:
        f = (root / path).resolve()
        if not f.is_relative_to(root):
            return f"{path}: outside the repo"
        if not f.is_file():
            return f"{path}: no such file"
        if find == replace:
            return f"{path}: edit changes nothing"
        text = f.read_text()
        n = text.count(find)
        if n != 1:
            return f"{path}: find block matched {n} times"
        f.write_text(text.replace(find, replace, 1))
    return None


def unified_diff(a: Path, b: Path, paths: list[str]) -> str:
    chunks = []
    for p in paths:
        r = subprocess.run(["git", "diff", "--no-index", *DIFF_FLAGS, str(a / p), str(b / p)],
                           capture_output=True, text=True)
        chunks.append(r.stdout.replace(str(a) + "/", "/").replace(str(b) + "/", "/"))
    return "".join(chunks)


def source_bundle(repo: Repo, ref: str, first: list[str]) -> str:
    """Repo source for the prompt: files the golden fix touches first, then the rest, up to a cap."""
    existing = repo.files(ref)
    files = [f for f in existing if f.endswith((".py", ".md", ".sql", ".toml", ".txt", ".cfg"))]
    # Files the golden fix adds don't exist at baseline yet.
    files = [f for f in first if f in existing] + [f for f in files if f not in first]
    parts, size = [], 0
    for f in files:
        body = repo.show(ref, f)
        if size + len(body) > MAX_CONTEXT_BYTES:
            parts.append(f"(... {len(files) - len(parts)} more files omitted)")
            break
        parts.append(f"### {f}\n```\n{body}\n```")
        size += len(body)
    return "\n\n".join(parts)


class Stress:
    def __init__(self, repo: Repo, task: Task, llm: LLM | None, n_mutants: int, attempts: int, scratch: Path):
        self.repo, self.t, self.llm = repo, task, llm
        self.n, self.attempts = n_mutants, attempts
        self.scratch = scratch / task.slug
        self.base, self.test, self.golden = (f"{task.task_id}_{s}" for s in ("baseline", "test", "golden"))
        self.result: dict = {"slug": task.slug, "task_id": task.task_id, "test_files": task.test_files,
                             "description": task.description}

    def log(self, msg: str) -> None:
        print(f"[{self.t.slug}] {msg}", flush=True)

    def tree(self, name: str, ref: str, edits=None) -> tuple[Path, str | None]:
        """Export ``ref``, apply ``edits`` if given, then the hidden tests. Returns (dir, error)."""
        d = self.repo.checkout(ref, self.scratch / name)
        err = apply_edits(d, edits) if edits is not None else None
        if not err:
            try:
                apply_patch(d, self.hidden_patch)
            except RuntimeError as e:
                err = f"hidden tests didn't apply: {e}"
        return d, err

    def run(self) -> dict:
        try:
            self._run()
        except Exception as e:  # keep the other tasks' results
            self.log(f"ERROR: {e}")
            self.result["error"] = str(e)
            self.result.setdefault("validity", {"baseline": "error", "golden": "error", "valid": False,
                                                "golden_tail": ""})
            self.result.setdefault("hidden_tests", 0)
            for m in self.result.get("mutants", []):
                if not m["hidden"]:
                    m["hidden"], m["hidden_tail"] = "error", "not graded: the task stopped with an error"
        return self.result

    def _run(self) -> None:
        t = self.t
        self.hidden_patch = self.repo.diff(self.base, self.test)
        self.golden_diff = self.repo.diff(self.base, self.golden)
        self.result["golden_diff"] = self.golden_diff
        golden_files = self.repo.changed(self.base, self.golden)
        hidden_files = self.repo.changed(self.base, self.test)

        # 1. validity (like HUD's baseline_fail check, any non-zero exit counts as failing)
        base_dir, _ = self.tree("baseline", self.base)
        gold_dir, _ = self.tree("golden", self.golden)
        b_status, b_tail = run_pytest(base_dir, t.test_files)
        g_status, g_tail = run_pytest(gold_dir, t.test_files)
        valid = b_status != "pass" and g_status == "pass"
        self.result["validity"] = {"baseline": b_status, "golden": g_status, "valid": valid,
                                   "golden_tail": g_tail if g_status != "pass" else ""}
        self.result["hidden_tests"] = self._count_tests(gold_dir)
        self.log(f"validity: baseline={b_status} golden={g_status} -> {'ok' if valid else 'INVALID'}")
        if not valid or self.llm is None:
            return

        # 2. mutants
        hidden_src = "\n\n".join(f"### {f}\n```\n{self.repo.show(self.test, f)}\n```" for f in hidden_files)
        prompt = (f"## Task description (what the agent sees)\n{t.description}\n\n"
                  f"## Repository at baseline\n{source_bundle(self.repo, self.base, golden_files)}\n\n"
                  f"## Reference fix\n```diff\n{self.golden_diff}\n```\n\n"
                  + MUTANT_FORMAT.format(n=self.n))
        mutants = parse_mutants(self.llm(MUTANT_SYSTEM, prompt))[: self.n]
        self.result["mutants"] = [m.__dict__ for m in mutants]  # live views, filled in below
        self.log(f"generated {len(mutants)} wrong fixes")

        # 3. grade each wrong fix with the hidden tests
        clean = self.repo.checkout(self.base, self.scratch / "baseline-clean")  # to diff mutants against
        for m in mutants:
            d, err = self.tree(f"mutant-{m.id}", self.base, edits=m.edits)
            if err:
                m.hidden, m.hidden_tail = "invalid", err
            else:
                m.diff = unified_diff(clean, d, sorted({e[0] for e in m.edits}))
                m.hidden, m.hidden_tail = run_pytest(d, t.test_files)
            self.log(f"  {m.id} {m.title!r}: hidden tests -> "
                     + {"pass": "PASSED (survived)", "fail": "failed (caught)",
                        "error": "error (broken)", "invalid": "edit didn't apply"}[m.hidden])

        # 4. killer tests for survivors
        survivors = [m for m in mutants if m.hidden == "pass"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda m: self._kill(m, hidden_src), survivors))

    def _count_tests(self, d: Path) -> int:
        _, tail = run_pytest(d, ["--collect-only", *self.t.test_files])
        m = re.search(r"(\d+) tests? collected", tail)
        return int(m.group(1)) if m else 0

    def _kill(self, m: Mutant, hidden_src: str) -> None:
        base = (f"## Task description\n{self.t.description}\n\n"
                f"## Reference fix (relative to the buggy baseline)\n```diff\n{self.golden_diff}\n```\n\n"
                f"## Wrong fix (relative to the same baseline); passes all hidden tests\n"
                f"Claimed difference: {m.difference}\n```diff\n{m.diff}\n```\n\n"
                f"## Hidden tests\n{hidden_src}")
        system = KILLER_SYSTEM.format(killer=KILLER_NAME)
        feedback = ""
        attempt = 0
        try:
            for attempt in range(1, self.attempts + 1):
                reply = self.llm(system, base + feedback, max_tokens=8_000)
                code = tag(reply, "test") or ""
                code = re.sub(r"^```(?:python)?\n|\n```$", "", code.strip())
                spec = (tag(reply, "spec") or "").strip().lower().rstrip(".")
                basis = (tag(reply, "basis") or "").strip()

                g_dir, _ = self.tree(f"k-{m.id}-{attempt}-golden", self.golden)
                m_dir, _ = self.tree(f"k-{m.id}-{attempt}-mutant", self.base, edits=m.edits)
                b_dir, _ = self.tree(f"k-{m.id}-{attempt}-baseline", self.base)
                for d in (g_dir, m_dir, b_dir):
                    (d / KILLER_NAME).write_text(code)
                g, g_tail = run_pytest(g_dir, [KILLER_NAME])
                mu, mu_tail = run_pytest(m_dir, [KILLER_NAME])
                b, _ = run_pytest(b_dir, [KILLER_NAME])
                if g == "pass" and mu == "fail":
                    m.killer = {"verified": True, "attempts": attempt, "spec": spec, "basis": basis,
                                "code": code, "on_baseline": b, "mutant_tail": mu_tail}
                    self.log(f"  {m.id}: killer verified (attempt {attempt}, spec={spec})")
                    return
                feedback = (f"\n\n## Your previous test didn't work\n```python\n{code}\n```\n"
                            f"On the reference fix it should PASS; got {g}:\n```\n{g_tail}\n```\n"
                            f"On the wrong fix it should FAIL (assertion or exception, not a collection error); "
                            f"got {mu}:\n```\n{mu_tail}\n```\nWrite a corrected module.")
        except Exception as e:  # keep the other survivors' results
            m.killer = {"verified": False, "attempts": attempt, "note": f"error while writing a new test: {e}"}
            self.log(f"  {m.id}: killer error: {e}")
            return
        m.killer = {"verified": False, "attempts": self.attempts,
                    "note": "no test separates it from the reference; may be equivalent"}
        self.log(f"  {m.id}: no killer found after {self.attempts} attempts")


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

TEMPLATE = Path(__file__).with_name("report_template.html")


def write_report(out: Path, results: list[dict], meta: dict) -> None:
    """report.json + each survivor as a git-apply-able diff + each verified killer test."""
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("mutants", "killer_tests"):  # drop files from an earlier run into the same folder
        shutil.rmtree(out / sub, ignore_errors=True)
    (out / "report.json").write_text(json.dumps({"meta": meta, "tasks": results}, indent=2))
    for r in results:
        for m in r.get("mutants", []):
            if m["hidden"] != "pass":
                continue
            (out / "mutants" / r["slug"]).mkdir(parents=True, exist_ok=True)
            (out / "mutants" / r["slug"] / f"{m['id']}.diff").write_text(m["diff"])
            if m["killer"].get("verified"):
                (out / "killer_tests" / r["slug"]).mkdir(parents=True, exist_ok=True)
                (out / "killer_tests" / r["slug"] / f"test_gst_{m['id']}.py").write_text(m["killer"]["code"].rstrip() + "\n")
    render_html(out)


def render_html(out: Path) -> Path:
    """Embed report.json into the HTML template. Self-contained; opens from disk."""
    # No raw "<" inside the <script>, so "</script>" or "<!--" in a diff can't break out of it.
    data = (out / "report.json").read_text().replace("<", "\\u003c")
    html = TEMPLATE.read_text().replace("/*__REPORT_JSON__*/null", data)
    (out / "report.html").write_text(html)
    return out / "report.html"


def strip_credentials(url: str) -> str:
    """Drop any user:token@ from a repo URL before it goes into the shareable report."""
    parts = urllib.parse.urlsplit(url)
    return parts._replace(netloc=parts.netloc.rpartition("@")[2]).geturl() if "@" in parts.netloc else url


# ----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=DEFAULT_REPO, help="git URL or path with {id}_baseline/_test/_golden branches")
    ap.add_argument("--tasks", type=Path, help="coding-template tasks file (e.g. tasks.py)")
    ap.add_argument("--only", help="comma-separated task slugs")
    ap.add_argument("--model", default="anthropic/claude-sonnet-5.5", help="OpenRouter model ID")
    ap.add_argument("--mutants", type=int, default=8, help="wrong fixes per task")
    ap.add_argument("--attempts", type=int, default=3, help="tries per killer test")
    ap.add_argument("--validate-only", action="store_true", help="only check baseline fails / golden passes")
    ap.add_argument("--out", type=Path, default=Path("out"), help="output folder")
    ap.add_argument("--render", action="store_true", help="only rebuild report.html from OUT/report.json")
    args = ap.parse_args()
    if args.render:
        if not (args.out / "report.json").is_file():
            ap.error(f"{args.out / 'report.json'} not found (try --out out/hud-samples)")
        print(f"report: {render_html(args.out)}")
        return

    if not args.tasks:
        ap.error("--tasks is required")
    tasks = parse_tasks(args.tasks)
    if not tasks:
        ap.error(f"no coding_bug(...) tasks found in {args.tasks}")
    if len({t.slug for t in tasks}) < len(tasks):
        ap.error(f"duplicate task slugs in {args.tasks}")
    if args.only:
        keep = set(args.only.split(","))
        if unknown := keep - {t.slug for t in tasks}:
            ap.error(f"unknown task slug(s): {', '.join(sorted(unknown))} "
                     f"(available: {', '.join(t.slug for t in tasks)})")
        tasks = [t for t in tasks if t.slug in keep]
    if not args.validate_only and not os.environ.get("OPENROUTER_API_KEY"):
        ap.error("OPENROUTER_API_KEY is not set (get one at https://openrouter.ai/keys), "
                 "or pass --validate-only to skip model calls")
    llm = None if args.validate_only else LLM(args.model)

    start = time.time()
    scratch = Path(tempfile.mkdtemp(prefix="gst-"))
    try:
        repo = Repo(args.repo, scratch)
        with ThreadPoolExecutor(max_workers=len(tasks) or 1) as pool:
            results = list(pool.map(
                lambda t: Stress(repo, t, llm, args.mutants, args.attempts, scratch).run(), tasks))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    meta = {"repo": strip_credentials(args.repo), "model": args.model, "mutants": args.mutants,
            "calls": llm.calls if llm else 0, "spent": llm.spent if llm else 0.0,
            "seconds": time.time() - start, "date": time.strftime("%Y-%m-%d")}
    write_report(args.out, results, meta)
    print(f"\nreport: {args.out / 'report.html'}  (spent ~${meta['spent']:.2f}, {meta['calls']} calls)")


if __name__ == "__main__":
    main()
