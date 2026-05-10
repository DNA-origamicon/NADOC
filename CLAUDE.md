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
just test           # full backend test suite
just test-file FILE # single test file
just fmt            # format
just lint           # lint
```

App URL when both servers run: `http://localhost:5173` (or WSL eth0 IP if `mirrored` networking is off — see `START.md`).

## Memory layout

This project uses Claude Code's hierarchical memory — load only what's relevant:

- `CLAUDE.md` (this file) — durable rules, always loaded.
- `memory/MEMORY.md` — auto-memory index. Lean pointer-only file; content lives in topic files.
- `memory/LESSONS.md` — past struggles, anti-patterns, things that previously misled fixes. Read when debugging an unclear symptom or when you suspect the codebase has seen this kind of bug before. Not a substitute for `project_*.md` topic files on clean refactors with named feature areas.
- `memory/project_*.md` — current-work topic files. Open the one(s) relevant to the task.
- `memory/REFERENCE_*.md` — stable domain knowledge (DNA topology, B-DNA constants, atomistic, FEM theory).
- `memory/feedback_*.md` — user feedback rules. Read whenever they touch the area you're editing.
- `.claude/rules/*.md` — path-scoped architectural maps + diagnostic patterns. Loaded automatically when you read matching files.

**Working scope guidance**: when working on assemblies, you don't need the cadnano editor's context. When editing physics, you don't need scaffold routing. Trust path-scoping and the index — don't preemptively load everything.

## Workflow conventions

- **Before claiming any non-trivial code change done, confirm you have read the relevant `memory/project_*.md` topic file from `MEMORY.md`'s index.** Order doesn't matter — grep first, read topic file second is fine — but skipping the topic file entirely is the failure mode. The Done checklist enforces this.
- **Skim `memory/feedback_*.md` filenames against the area you're touching.** If one matches (e.g. `feedback_crossover_no_reasoning` while editing crossover code), open it. They're short and the cost of skipping a relevant one is high.
- Before claiming a feature works, run `just test` and verify the affected behavior in the running app.
- For UI changes: `just frontend` must be running and you must exercise the feature. Type-checking and tests do not validate UI correctness.
- Prefer modifying existing modules over adding new ones — this codebase has many small interconnected files already.
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

- **Every backend code change runs `just test` before claiming done — no exceptions, even for one-line changes that mirror a documented fix.** Flag any unexpected test-count drop.
- **Every frontend code change must be exercised in the running app before claiming done.** If `just frontend` isn't running or no representative design has been loaded, your "done" message must lead with `NOT VERIFIED IN APP` and explain why. Type-checking and tests do not validate UI correctness.
- Geometry/topology changes: load a representative `.nadoc` design (e.g. `Examples/teeth.nadoc`) and visually confirm.
- Don't claim "tests pass" without running them.
- Run frontend Playwright tests after two iteration failures.
- Verification of specific features often needs user-generated designs. Ask which design should be used for testing.

### Done checklist (acknowledge each before claiming a task done)

- [ ] Tests run (cite the command + pass count). Frontend-only changes can skip backend test suite if no Python touched — say so explicitly.
- [ ] Frontend changes exercised in running app, OR `NOT VERIFIED IN APP` caveat at top of message
- [ ] Relevant `project_*.md` topic file from `MEMORY.md` was read this session (cite which one); if not, justify why
- [ ] Topic file scanned for stale claims this change addressed; updated if needed
- [ ] If you touched a known-bug area (crossover, three-layer boundary, length/index conventions, cluster/deformation, rendering invariants, stale-state) — cite which LESSONS.md entry you checked, or explicitly say "LESSONS not relevant: [why]"

## Risky-action policy

Confirm before any of these unless you explicitly pre-authorized:
- Deleting branches, files, or DB-like state
- `git reset --hard`, force-push, history rewrites
- Modifying CI configuration or hooks
- Pushing to remote, creating PRs, posting on shared services
- Touching the `_PHASE_*` constants in `lattice.py`
- Bulk migrations of saved `.nadoc` files

## Audience & communication

The user has a PhD in biophysics specializing in DNA origami. Biology / biophysics / DNA-nanotech content should be dense and technical — assume domain fluency, use precise terminology, don't define standard concepts. Statements and questions in this domain can carry compressed meaning.

Programming knowledge is at a basic level. Any explanation involving code, data structures, algorithms, build systems, or infrastructure must be framed simply — short concrete examples over abstract terms, name what's happening rather than the jargon for it, and unpack acronyms on first use. When a fix touches code, default to explaining *what changed for the user-visible behavior*, not the mechanism, unless asked.

When in doubt about which mode applies: bio = dense and assumed, code = ELI5.

## Tone

Terse responses. No trailing summary blocks unless asked. Use markdown file links (`[name](path#Lline)`) when citing code. Don't restate the diff after editing. Don't use emojis unless requested.

## When you don't know

Default to asking, not guessing. The DNA-topology and three-layer rules above exist because past sessions burned cycles on plausible-looking fixes that violated invariants.
