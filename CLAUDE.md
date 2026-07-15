# NADOC — Project Instructions

Personal research-grade DNA-origami CAD. Python 3.12 + FastAPI backend, Three.js + Vite frontend, vanilla ES modules. `uv` for Python deps.

## Three-Layer Law (CRITICAL — applies to every task)

1. **Topological** — strand graph + crossover graph. Ground truth. Edits go here only.
2. **Geometric** — helix axes, nucleotide positions derived from topology + B-DNA constants. Read-only output.
3. **Physical** — XPBD/oxDNA relaxed positions. Display state only. Never written back to topology.

Never let physical/geometric layers mutate topology. If a "fix" tempts you to write back, stop and check assumptions.

## DNA Topology — Ask First

Any confusion about strand polarity, helix orientation, domain traversal, or scaffold path → **ask the user first, implement nothing**. Reasoning about geometry/topology/directionality alone consistently produces wrong results in this codebase. See `memory/REFERENCE_DNA_TOPOLOGY.md`.

Helical phase constants (`_PHASE_FORWARD`, `_PHASE_REVERSE`, `_SQ_PHASE_FORWARD`, `_SQ_PHASE_REVERSE`) are **locked**. Never change without explicit approval. They affect every downstream system.

## Commands

```bash
# Always export PATH for uv first (or use the explicit path):
export PATH="$HOME/.local/bin:$PATH"

just dev            # backend (FastAPI on :8000)
just frontend       # Vite dev server (:5173)
just test-smart     # DEFAULT per-change loop: fast suite, scoped. ~60s; 90s backstop.
just test-affected FILE... # tightest inner loop: point pytest at the area you edit
just test-file FILE # single test file (fast tests only)
just test-frontend  # JS unit tests (Vitest)
just fmt            # format
just lint           # lint

# TEST-DEDICATED SESSION ONLY (the user opens the window; see below):
just test-session   # USER runs this in THEIR terminal — 4h window, TTY-only
just test-slow      # only the heavy sims/solves
just test           # FULL suite (minutes) — the pre-push gate
just test-status    # session open? which heavy groups are owed?
```

## Test policy (THE LAW)

**Heavy (`slow`) tests — real oxDNA/NAMD/mrdna sims, CanDo-FEM solves, trajectory
benchmarks — never run in an ordinary coding session.** They take minutes, and the cost
of Claude reflexively escalating to the full suite after a change that "distantly touches
simulations" is what killed dev velocity. They now run **only inside a test-dedicated
session**: a window the *user* opens in *their own* terminal with `just test-session`
(TTY-only, expiring). `scripts/test_guard.sh` refuses `just test` / `just test-slow` /
`just test-all` outside one.

As an agent:

- **Your loop is `just test-smart`** (no confirm needed any more; it's fast-only). It runs
  the fast suite and, if your change made a heavy group stale, *parks* that group in
  `.nadoc-slow-pending` and tells you — it does not run it. Say so in your done message
  ("deferred slow[cando] — needs a test-dedicated session"); that is a complete and
  correct verification for a normal change, not a gap you should try to close.
- **If you believe the heavy suite really must run, ASK the user to open a
  test-dedicated session.** Do not work around the guard: never hand-write
  `.nadoc-test-session`, never set `NADOC_TEST_FORCE=1`, never invoke pytest directly to
  dodge the wrapper (`uv run pytest tests/` bare, no `-m "not slow"`, is exactly the move
  this policy forbids).
- **Budget — the gate is PER-TEST, not total time.** Any *unmarked* test over ~5s
  (`NADOC_PER_TEST_BUDGET_SEC`) is heavy and must be relegated: the guard prints `HEAVY
  TEST IN THE FAST SUITE` and lists the offenders in `.nadoc-slow-candidates.json`. You
  must then **launch a triage subagent** (Agent tool, `general-purpose`, following
  `.claude/skills/triage-slow-tests/SKILL.md`) that relegates them to the slow suite
  (`slow` + area marker in `tests/conftest.py`). Never raise the budget, never just move on.
- **Total wall-clock is a backstop only (90s), not a target.** Total time grows with the
  *number* of tests (which only goes up) and with whatever else is using the CPU, so a
  fixed ceiling on it just ratchets healthy tests out of the fast suite — that churn cost
  more time than it ever saved. A run between 60s and 90s prints a note and **requires
  nothing**. Only above 90s with no single over-budget test does the guard ask for triage
  (`FAST SUITE TOO SLOW` — the suite got fat in aggregate).
- Pytest runs under `nice -n 10` so a test run doesn't make the app stutter while the user
  is actually using NADOC (`NADOC_TEST_NICE=0` opts out).

The lock still applies: overlapping `just test*` runs saturate the CPU, so a second run
refuses while one is live. Heavy tests additionally auto-skip while a production
NAMD/oxDNA/mrDNA job is running (`NADOC_IGNORE_SIM_GUARD=1` overrides). See
`memory/project_test_parallelization.md`.

App URL when both servers run: `http://localhost:5173` (or WSL eth0 IP if `mirrored` networking is off — see `START.md`).

## Memory layout

This project uses Claude Code's hierarchical memory — load only what's relevant:

- `CLAUDE.md` (this file) — durable rules, always loaded.
- `memory/MEMORY.md` — auto-memory index. Lean pointer-only file; content lives in topic files. **Edit it rarely** — it sits in the always-loaded prompt prefix, so every change invalidates the prompt cache for all sessions. Feature updates go in the topic file, not here.
- `memory/LESSONS.md` — **index** of past struggles and anti-patterns, one line per entry with a symptom hook. Scan it when debugging an unclear symptom; open only the matching entry's detail in `memory/LESSONS_archive.md`. Not a substitute for `project_*.md` topic files on clean refactors with named feature areas.
- **`*_archive.md` (anywhere) — history, never read in a routine loop.** Every large ledger and topic file is split into a lean *head* (current state, invariants, open items, handoff) and an archive holding the completed/superseded history. Read the head. Open an archive only to mine a specific past decision you know is in there. Reading archives by reflex is the single largest avoidable token cost in this repo.
- `memory/project_*.md` — current-work topic files. Open the one(s) relevant to the task.
- `memory/REFERENCE_*.md` — stable domain knowledge (DNA topology, B-DNA constants, atomistic, FEM theory).
- `memory/feedback_*.md` — user feedback rules. Read whenever they touch the area you're editing.
- `.claude/rules/*.md` — path-scoped architectural maps + diagnostic patterns. Loaded automatically when you read matching files.
- `.claude/skills/*/SKILL.md` — the session loops (`/carve-router`, `/automate-feature`, `/continue-coverage`, …).

**What syncs between the two computers.** `.gitignore` uses `.claude/*` plus negations, so **`.claude/rules/` and `.claude/skills/` are versioned and shared** — edit them like any other source file and they reach the other machine on push. **`.claude/settings.local.json` (permission allowlist) and `.claude/worktrees/` stay machine-local** and are never committed. `memory/` is tracked too, and `~/.claude/projects/-home-joshua-NADOC/memory/` is a **symlink** to it, so there is exactly one copy of every memory file to maintain. Consequence: a rule or skill edited on one computer and not pushed will silently diverge — if you change guidance, commit it.

**Working scope guidance**: when working on assemblies, you don't need the cadnano editor's context. When editing physics, you don't need scaffold routing. Trust path-scoping and the index — don't preemptively load everything.

## Workflow conventions

- **Before claiming done on a change that alters behavior in a subsystem with a `memory/project_*.md` topic file, confirm you have read that topic file's head.** Order doesn't matter — grep first, read topic file second is fine — but skipping it entirely is the failure mode. Changes that do *not* alter subsystem behavior (renames, comments, test-only edits, formatting, a fix wholly described by the prompt) don't need it — say so in the done message instead of reading it. Never read the topic file's `*_archive.md` for this.
- **Skim `memory/feedback_*.md` filenames against the area you're touching.** If one matches (e.g. `feedback_crossover_no_reasoning` while editing crossover code), open it. They're short and the cost of skipping a relevant one is high.
- Before claiming a feature works, run `just test-smart` (it scopes to what your change affects) and verify the affected behavior in the running app.
- For UI changes: `just frontend` must be running and you must exercise the feature. Type-checking and tests do not validate UI correctness.
- Prefer modifying existing modules over adding new ones — this codebase has many small interconnected files already. **But never grow `main.js` (or any composition root) with new cohesive logic** (see next bullet): the precedence is existing module > new module > *never* a new block in the closure.
- **Module-first law (anti-backslip — read [FEATURE_DEVELOPMENT.md](FEATURE_DEVELOPMENT.md) before adding any feature).** The carve-up shrank `main.js` 16.5k→~7.5k by pulling cohesive subsystems into modules. Feature work must not re-grow it. New cohesive logic (multi-function behavior, owned state, subscribers) lands in a **new/existing tested module** (`initX({deps})→{api}`); `main.js` gains ONLY an import + a one-line factory init + thin per-action wiring (Feathers' Sprout Method). A feature commit leaves `main.js` LOC **flat or lower** — a net rise that isn't pure wiring means a cohesive block crept in; extract it before committing. Cite `main.js` LOC Δ in the done message.
- Three-Layer Law violations are silent and corrupting. When unsure which layer a change belongs in, ask.
- **When you finish a code change in an area with a `project_*.md` topic file, scan it for stale claims** (TODOs, "deferred", "not yet wired", line numbers, "still has bug") that your change has addressed. Update the file. Same for code comments referencing "TODO/FIXME/not yet" in files you touched.

## Git conventions

Solo dev, two computers (work happens on either), GitHub remote `origin` at `DNA-origamicon/NADOC`. Default branch is `master`.

### Default workflow

Commit straight to `master`. Branches are overhead for solo work and mostly aren't needed. Create a branch only when:
- The work is risky and might be thrown away (so master stays clean)
- A feature spans many commits and master needs to stay shippable in between
- An experimental approach is unsure and you want a clean discard path

When branching: `git checkout -b <short-name>`, commit, then either fast-forward merge to master (`git checkout master && git merge --ff-only <name>`) or delete the branch if it's not worth keeping. Branch naming barely matters — keep it short and descriptive.

### Two-computer protocol (critical)

Two rules, every session:

1. **Pull before you start.** First action on either computer:
   ```bash
   git pull --rebase origin master
   ```
2. **Push before you stop.** Last action:
   ```bash
   git status   # confirm clean
   git push origin master
   ```

`--rebase` keeps history linear. If both computers committed before pulling, the rebase replays local commits on top of remote — resolve any conflicts and continue.

### My defaults

- Commit only when explicitly asked ("commit", "make a commit"). Never preemptively.
- Never push without being asked.
- Never create a branch without asking, unless I tell you why first and you confirm.
- Never amend, rebase published commits, or force-push (especially to master).
- Never use `--no-verify` or skip hooks.
- Run `git status` and `git log -1` at the start of any git work to confirm we're where we expect.
- **More than one Claude session may be working in this tree at once.** Never run `git stash`, `git reset`, `git checkout -- <path>`, or `git restore` without asking — they revert the *whole tree* and will clobber the other session's in-flight work (and yours). Read files from disk, not from `git show HEAD:<path>`. **Forbid git commands explicitly in every subagent prompt.** Dirty files in `git status` may not be yours. If a file you just wrote reverts to its committed state, check `git stash list` / `git reflog` before re-applying anything. Snapshot to the scratchpad before bulk rewrites — git is not a safe backup here.

### Commit message style

Follow recent `git log`: `area: summary` (`feat:`, `fix:`, `perf:`, `docs:`). One-line subject; body for the "why" if non-obvious.

### Newbie gotchas to flag

If any of these come up, I'll stop and explain rather than charge ahead:
- `git push` rejected as non-fast-forward → `git pull --rebase`, **never** `-f`
- Uncommitted changes blocking a pull → `git stash` / pull / `git stash pop`, or commit first
- "HEAD detached at..." → `git checkout -b temp-save` immediately, then sort out
- Untracked scratch files that didn't sync — either commit or `.gitignore` them
- ~30 stale local-only branches from past work exist; safe to prune with `git fetch --prune` + targeted `git branch -D`, but I'll ask first

## Verification expectations

- **Every backend code change runs `just test-smart` before claiming done — no exceptions, even for one-line changes that mirror a documented fix.** It runs the fast suite (always) and finishes in under a minute. Cite the decision it printed (`FAST` / `fast+slow[area]`) **and** the pass count; flag any unexpected drop. If it says heavy groups were **DEFERRED**, report that verbatim — deferring is the correct outcome, not a gap. Never escalate to `just test` / `just test-slow` yourself: those need a test-dedicated session the *user* opens (see Test policy). Frontend-only changes touch no Python → `just test-smart` returns `FAST`; run `just test-frontend` for the JS.
- **An unmarked test over ~5s is a process failure; a slow *total* is usually not.** When the guard says `HEAVY TEST IN THE FAST SUITE` (or `FAST SUITE TOO SLOW`, its 90s aggregate backstop), launch a triage subagent (`.claude/skills/triage-slow-tests/SKILL.md`) to relegate the offenders before claiming done. A run that merely passes the 60s soft mark needs no action — say the time and move on.
- **Every frontend code change must be exercised in the running app before claiming done.** If `just frontend` isn't running or no representative design has been loaded, your "done" message must lead with `NOT VERIFIED IN APP` and explain why. Type-checking and tests do not validate UI correctness.
- Geometry/topology changes: load a representative `.nadoc` design (e.g. `Examples/26hb_platform_v3.nadoc`) and visually confirm.
- Don't claim "tests pass" without running them.
- **Refactor extractions (closure → module): every pure function extracted gets ≥1 vitest test asserting its input→output behavior; `just test-frontend` must be green before claiming the extraction done.** This is the fast loop (`just test-frontend-watch` to iterate). See the streamlined extraction-loop in [.claude/rules/main-init.md](.claude/rules/main-init.md). Stateful (DOM/scene/store) extractions additionally need one app exercise + `just smoke` (the console-error commit gate) before commit — this is the *one* sanctioned routine use of Playwright.
  - **Prove the pin for ADAPTED code (test-ordering).** A test written against the *moved* code and passing first-run only proves behavior preservation for a **verbatim lift** (byte-identical body — the cut-paste itself preserves behavior). For **adapted** code — get/set shims, alias rewiring, lazy-arrow wrapping, any non-byte-identical change — "green first run" is *not* proof: either get the test green against the code **in place** first then move test+code together, or run the new test once against a `git stash`'d copy of the old code. State in the log row how each adapted pin was proven.
  - **"Extraction done" is judged by coupling + cohesion, not LOC.** Done = the new module has ONE reason to change and a small, countable dep surface (the dep list you already write in the log row). LOC-Δ is *narrative only* — never the pass criterion or the goal. The carve-up's terminal state is reached when the residual closure is composition-root glue (imports + factory inits + thin per-action wiring) you're no longer *touching* — that's done, not unfinished.
- **Playwright/E2E is NOT part of the routine dev cycle — it's too slow for tight iteration.** Default frontend verification is exercising the running app directly. Reach for Playwright only to (a) reproduce or troubleshoot a specific error/bug, or (b) clarify behavior when you're unsure what the user is describing. Do not write or run E2E specs as a default "done" step. See [REFERENCE_PLAYWRIGHT](memory/REFERENCE_PLAYWRIGHT.md).
- Verification of specific features often needs user-generated designs. Ask which design should be used for testing.

### Done checklist (acknowledge each before claiming a task done)

- [ ] Tests run: `just test-smart` (cite its decision — `FAST`/`fast+slow[area]` — the pass count, and any `DEFERRED` heavy groups). Frontend-only changes get `FAST` (no Python touched → no backend tests); run `just test-frontend` and say so explicitly. `just test` / `just test-slow` are test-dedicated-session only — never run them, ask the user
- [ ] Budget honoured: no unmarked test over ~5s, and the run stayed under the 90s backstop. If either tripped, a triage subagent (`/triage-slow-tests`) ran and the offenders were relegated. Between 60s and 90s = fine, no action
- [ ] Frontend changes exercised in running app, OR `NOT VERIFIED IN APP` caveat at top of message
- [ ] If the change alters subsystem behavior: relevant `project_*.md` topic file **head** was read this session (cite which one). If it doesn't alter behavior, say "no topic file needed: [why]" — don't read one to satisfy the checklist
- [ ] Topic file **head** scanned for stale claims this change addressed; updated if needed (update the head, not the archive)
- [ ] If you touched a known-bug area (crossover, three-layer boundary, length/index conventions, cluster/deformation, rendering invariants, stale-state) — scan the `LESSONS.md` index and cite the entry you checked, or explicitly say "LESSONS not relevant: [why]". Open `LESSONS_archive.md` only for the one entry that matches
- [ ] No `*_archive.md` was read unless you were mining a specific past decision (name it)
- [ ] If this was a refactor extraction from a closure: ≥1 vitest test per extracted pure function, `just test-frontend` green (cite count); stateful extractions also ran `just smoke` + one app exercise. **Adapted (non-verbatim) code: cite how the pin was proven** (in-place-first / stash-rerun). **Done judged by coupling+cohesion** (one reason to change, small dep surface), not LOC.

## Risky-action policy

Confirm before any of these unless you explicitly pre-authorized:
- Deleting branches, files, or DB-like state
- `git reset --hard`, force-push, history rewrites
- Modifying CI configuration or hooks
- Pushing to remote, creating PRs, posting on shared services
- Touching the `_PHASE_*` constants in `lattice.py`
- Anything that unlocks or weakens the test guard: creating `.nadoc-test-session`, setting `NADOC_TEST_FORCE=1`/`NADOC_TEST_BUDGET_SEC`, calling `pytest` outside the `just` recipes without `-m "not slow"`. Ask the user to open a test-dedicated session instead
- Bulk migrations of saved `.nadoc` files

## Audience & communication

The user has a PhD in biophysics specializing in DNA origami. Biology / biophysics / DNA-nanotech content should be dense and technical — assume domain fluency, use precise terminology, don't define standard concepts. Statements and questions in this domain can carry compressed meaning.

Programming knowledge is at a basic level. Any explanation involving code, data structures, algorithms, build systems, or infrastructure must be framed simply — short concrete examples over abstract terms, name what's happening rather than the jargon for it, and unpack acronyms on first use. When a fix touches code, default to explaining *what changed for the user-visible behavior*, not the mechanism, unless asked.

When in doubt about which mode applies: bio = dense and assumed, code = ELI5.

## Tone

Terse responses. No trailing summary blocks unless asked. Use markdown file links (`[name](path#Lline)`) when citing code. Don't restate the diff after editing. Don't use emojis unless requested.

## When you don't know

Default to asking, not guessing. The DNA-topology and three-layer rules above exist because past sessions burned cycles on plausible-looking fixes that violated invariants.
